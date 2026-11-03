"""Opt-in Android acceptance with disposable account credentials."""

import asyncio
import json
import os
import secrets
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import delete
from test_account_security_database import seed_account

from nxtrep_backend.db.models import User
from nxtrep_backend.db.session import SessionFactory

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_ACCOUNT_SECURITY_DEVICE_TESTS") != "1",
    reason="Requires running local API, Android emulator and Flutter SDK",
)
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_android_account_security_end_to_end():
    user_id, username, password = await seed_account()
    defines = ROOT / ".local/account-security-device-defines.json"
    log = ROOT / ".local/account-security-device.log"
    try:
        defines.write_text(
            json.dumps(
                {
                    "E2E_USERNAME": username,
                    "E2E_PASSWORD": password,
                    "E2E_NEXT_PASSWORD": secrets.token_urlsafe(24),
                    "API_BASE_URL": "http://10.0.2.2:8000/api/v1",
                }
            ),
            encoding="utf-8",
        )
        flutter = Path("D:/develop/flutter/bin/flutter.bat")
        assert flutter.is_file()
        environment = dict(os.environ)
        environment["JAVA_TOOL_OPTIONS"] = (
            environment.get("JAVA_TOOL_OPTIONS", "")
            + " -Djdk.net.unixdomain.tmpdir=C:\\Windows\\Temp"
        ).strip()

        def run():
            with log.open("w", encoding="utf-8") as output:
                return subprocess.run(
                    [
                        str(flutter),
                        "--no-version-check",
                        "test",
                        "--no-pub",
                        "integration_test/local_account_security_test.dart",
                        "-d",
                        "emulator-5554",
                        "--dart-define-from-file=" + str(defines),
                        "--reporter",
                        "expanded",
                    ],
                    cwd=ROOT / "frontend",
                    env=environment,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    timeout=480,
                    check=False,
                ).returncode

        code = await asyncio.to_thread(run)
        assert code == 0, "Inspect .local/account-security-device.log; test credentials omitted"
    finally:
        defines.unlink(missing_ok=True)
        async with SessionFactory.begin() as session:
            await session.execute(delete(User).where(User.id == user_id))
