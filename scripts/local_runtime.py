"""Local Windows launcher support; never used by the production API."""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND / "src"))


class LocalSetupError(ValueError):
    """Safe, credential-free diagnostic intended for the local console."""


def fingerprint(area: str) -> str:
    base = ROOT / area
    if area == "frontend":
        folders = ("lib", "assets", "android")
        names = ("pubspec.yaml", "pubspec.lock", ".metadata")
    else:
        folders = ("src", "migrations")
        names = (".env", "pyproject.toml", "uv.lock", "alembic.ini")
    files = {base / name for name in names if (base / name).is_file()}
    for folder in folders:
        for path in (base / folder).rglob("*"):
            relative = path.relative_to(base)
            if path.is_file() and not set(relative.parts) & {
                "build",
                ".gradle",
                ".cxx",
                "__pycache__",
            }:
                files.add(path)
    digest = hashlib.sha256(b"nxtrep-local-v1-main-debug-10.0.2.2:8000")
    for path in sorted(files):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    digest.update(Path(__file__).read_bytes())
    return digest.hexdigest()


def local_settings():
    from dotenv import dotenv_values
    from nxtrep_backend.core.config import get_settings
    from sqlalchemy.engine import make_url

    os.chdir(BACKEND)
    configured = dotenv_values(BACKEND / ".env").get("NXTREP_DATABASE_URL")
    if not configured:
        raise LocalSetupError("backend/.env must explicitly set NXTREP_DATABASE_URL")
    override = os.environ.get("NXTREP_DATABASE_URL")
    if override and override != configured:
        raise LocalSetupError(
            "NXTREP_DATABASE_URL overrides backend/.env; clear it before local startup"
        )
    settings = get_settings()
    url = make_url(settings.database_url)
    if settings.environment != "local" or url.host not in {"localhost", "127.0.0.1"}:
        raise LocalSetupError(
            "This launcher requires environment=local and a loopback database"
        )
    if (url.port or 5432) != 5432:
        raise LocalSetupError(
            "This launcher manages the PostgreSQL service on port 5432 only"
        )
    return settings, url


async def inspect_database() -> dict:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    settings, url = local_settings()
    engine = create_async_engine(settings.database_url, connect_args={"timeout": 8})
    try:
        async with engine.connect() as connection:
            actual = (
                await connection.execute(text("SELECT current_database()"))
            ).scalar_one()
            revision = await connection.execute(
                text("SELECT version_num FROM alembic_version")
            )
            current = sorted(revision.scalars().all())
        heads = sorted(ScriptDirectory.from_config(Config("alembic.ini")).get_heads())
        if current != heads:
            raise LocalSetupError(
                "Database migrations are pending; run alembic upgrade head in backend"
            )
        identity = f"{url.host}:{url.port or 5432}/{actual}/{url.username}"
        return {
            "database": actual,
            "host": url.host,
            "port": url.port or 5432,
            "binding": hashlib.sha256(identity.encode()).hexdigest(),
            "revision": current,
        }
    finally:
        await engine.dispose()


async def ensure_account(payload: dict) -> dict:
    local_settings()
    from nxtrep_backend.core.security import verify_password
    from nxtrep_backend.db.session import SessionFactory, engine
    from nxtrep_backend.repositories.goals import SqlAlchemyGoalsRepository
    from nxtrep_backend.repositories.user import SqlAlchemyUserRepository
    from nxtrep_backend.services.account import AccountService
    from nxtrep_backend.services.goals import GoalsService, GoalsUpdateData

    username, password = payload["username"], payload["password"]
    if not (username.isascii() and username.isdigit() and 6 <= len(username) <= 20):
        raise LocalSetupError("Local test usernames must be 6-20 ASCII digits")
    if not (password.isascii() and password.isdigit() and 16 <= len(password) <= 64):
        raise LocalSetupError("Local test passwords must be 16-64 random ASCII digits")
    try:
        async with SessionFactory.begin() as session:
            repository = SqlAlchemyUserRepository(session)
            user = await repository.get_by_username(username)
            if user is not None:
                if (
                    user.is_admin
                    or user.password_setup_required
                    or user.status != "active"
                ):
                    raise LocalSetupError(
                        "Existing account is not a usable non-admin test account"
                    )
                if not user.credential or not verify_password(
                    password, user.credential.password_hash or ""
                ):
                    raise LocalSetupError(
                        "Saved test credential does not match; no password was reset"
                    )
                return {"username": username, "created": False}
            service = AccountService(repository)
            created = await service.precreate_user(
                username=username, display_name="E2E Test"
            )
            await service.setup_password(
                username=username,
                setup_token=created.setup_token,
                new_password=password,
            )
            profile = created.user.profile
            profile.sex = "male"
            profile.height_cm = 173
            profile.experience_level = "beginner"
            profile.weekly_training_days = 3
            profile.session_duration_minutes = 45
            await GoalsService(
                SqlAlchemyGoalsRepository(session)
            ).update_goals_and_constraints(
                user_id=created.user.id,
                expected_version=None,
                data=GoalsUpdateData(
                    goal_type="fat_loss_retain",
                    target_date=None,
                    target_weight_kg=None,
                    equipment=["dumbbell", "bodyweight"],
                    preferred_exercises=[],
                    disliked_exercises=[],
                    pain_or_injuries=[],
                    allergies=[],
                    dietary_preferences=[],
                ),
            )
            return {"username": username, "created": True}
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["inspect", "fingerprint", "account", "serve"]
    )
    parser.add_argument("--area", choices=["frontend", "backend"], default="backend")
    parser.add_argument("--run-id")
    parser.add_argument("--host", choices=["127.0.0.1", "0.0.0.0"], default="127.0.0.1")
    args = parser.parse_args()
    try:
        if args.command == "fingerprint":
            print(fingerprint(args.area))
        elif args.command == "inspect":
            print(json.dumps(asyncio.run(inspect_database())))
        elif args.command == "account":
            print(json.dumps(asyncio.run(ensure_account(json.load(sys.stdin)))))
        else:
            local_settings()
            if not args.run_id:
                raise LocalSetupError("serve requires --run-id")
            import uvicorn
            from nxtrep_backend.main import app

            state = ROOT / ".local" / "api.json"
            state.parent.mkdir(exist_ok=True)
            state.write_text(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "runId": args.run_id,
                        "signature": fingerprint("backend"),
                        "startedAt": datetime.now(UTC).isoformat(),
                        "host": args.host,
                    }
                ),
                encoding="utf-8",
            )
            uvicorn.run(app, host=args.host, port=8000)
    except LocalSetupError as exc:
        print(f"Local setup: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as exc:  # noqa: BLE001 - sanitize failures at this CLI boundary
        # Connection exceptions may contain passwords or signed URLs; do not dump them.
        print(
            f"Local setup failed ({type(exc).__name__}); check backend/.env and PostgreSQL.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
