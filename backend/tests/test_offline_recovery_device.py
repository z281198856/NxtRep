"""Two Android processes: persist offline, force-stop, recover and submit once."""

import asyncio
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete
from test_account_security_database import seed_account

from nxtrep_backend.db.models import User
from nxtrep_backend.db.session import SessionFactory

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_OFFLINE_DEVICE_TESTS") != "1",
    reason="Explicit Android offline acceptance required",
)
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_android_offline_records_survive_process_restart():
    user_id, username, password = await seed_account()
    defines = ROOT / ".local/offline-device-defines.json"
    evidence = []
    day = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    try:
        for phase in ("write", "recover"):
            defines.write_text(
                json.dumps(
                    {
                        "E2E_USERNAME": username,
                        "E2E_PASSWORD": password,
                        "OFFLINE_PHASE": phase,
                        "OFFLINE_DATE": day,
                        "API_BASE_URL": "http://10.0.2.2:8000/api/v1",
                    }
                ),
                encoding="utf-8",
            )
            environment = dict(os.environ)
            environment["JAVA_TOOL_OPTIONS"] = (
                environment.get("JAVA_TOOL_OPTIONS", "")
                + " -Djdk.net.unixdomain.tmpdir=C:\\Windows\\Temp"
            ).strip()

            def run(phase=phase, environment=environment):
                with (ROOT / f".local/offline-device-{phase}.log").open(
                    "w", encoding="utf-8"
                ) as log:
                    return subprocess.run(
                        [
                            "D:/develop/flutter/bin/flutter.bat",
                            "--no-version-check",
                            "test",
                            "--no-pub",
                            "--no-uninstall",
                            "integration_test/local_offline_recovery_test.dart",
                            "-d",
                            "emulator-5554",
                            "--dart-define-from-file=" + str(defines),
                            "--reporter",
                            "expanded",
                        ],
                        cwd=ROOT / "frontend",
                        env=environment,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=480,
                        check=False,
                    ).returncode

            code = await asyncio.to_thread(run)
            evidence.append({"phase": phase, "exit_code": code})
            assert code == 0, f"Inspect offline-device-{phase}.log; credentials omitted"
            if phase == "write":
                installed = subprocess.run(
                    [
                        "C:/Android/Sdk/platform-tools/adb.exe",
                        "-s",
                        "emulator-5554",
                        "shell",
                        "pm",
                        "path",
                        "com.zengsiqi.nxtrep",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=20,
                )
                assert installed.returncode == 0 and installed.stdout.startswith("package:"), (
                    "Integration runner must preserve installed application data"
                )
                evidence.append({"event": "installation_retained", "verified": True})
                stopped = subprocess.run(
                    [
                        "C:/Android/Sdk/platform-tools/adb.exe",
                        "-s",
                        "emulator-5554",
                        "shell",
                        "am",
                        "force-stop",
                        "com.zengsiqi.nxtrep",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=20,
                )
                assert stopped.returncode == 0
                evidence.append({"event": "process_force_stopped", "exit_code": 0})
    finally:
        defines.unlink(missing_ok=True)
        async with SessionFactory.begin() as session:
            await session.execute(delete(User).where(User.id == user_id))
        (ROOT / ".local/offline-device-evidence.json").write_text(
            json.dumps(
                {
                    "events": evidence,
                    "temporary_credentials_removed": not defines.exists(),
                    "disposable_account_deleted": True,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
