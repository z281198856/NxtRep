"""Offline guardrails for the Windows local launcher; no real DB or credentials."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

HELPER = Path(__file__).resolve().parents[2] / "scripts" / "local_runtime.py"
SPEC = importlib.util.spec_from_file_location("local_runtime_tests", HELPER)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


def test_frontend_fingerprint_ignores_test_builds_but_tracks_app(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    source = tmp_path / "frontend/lib/main.dart"
    source.parent.mkdir(parents=True)
    source.write_text("app v1")
    original = runtime.fingerprint("frontend")
    generated = tmp_path / "frontend/android/.gradle/cache"
    generated.parent.mkdir(parents=True)
    generated.write_text("integration build cache")
    assert runtime.fingerprint("frontend") == original
    source.write_text("app v2")
    assert runtime.fingerprint("frontend") != original


@pytest.fixture
def local_config(tmp_path, monkeypatch):
    from nxtrep_backend.core import config

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runtime, "BACKEND", tmp_path)
    monkeypatch.delenv("NXTREP_DATABASE_URL", raising=False)
    url = "postgresql+asyncpg://test:synthetic@localhost:5432/test"
    (tmp_path / ".env").write_text(f"NXTREP_DATABASE_URL={url}\n")
    settings = SimpleNamespace(environment="local", database_url=url)
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    return settings


def test_local_database_accepted(local_config):
    settings, url = runtime.local_settings()
    assert settings is local_config
    assert url.host == "localhost"


def test_different_environment_override_rejected(local_config, monkeypatch):
    monkeypatch.setenv("NXTREP_DATABASE_URL", "postgresql://different")
    with pytest.raises(runtime.LocalSetupError, match="overrides"):
        runtime.local_settings()


@pytest.mark.parametrize(
    ("environment", "url"),
    [
        ("production", "postgresql://localhost/test"),
        ("local", "postgresql://remote.invalid/test"),
        ("local", "postgresql://localhost:5433/test"),
    ],
)
def test_unsupported_database_rejected(local_config, environment, url):
    local_config.environment = environment
    local_config.database_url = url
    with pytest.raises(runtime.LocalSetupError):
        runtime.local_settings()


def test_missing_explicit_config_rejected(local_config, tmp_path):
    (tmp_path / ".env").write_text("")
    with pytest.raises(runtime.LocalSetupError, match="explicitly"):
        runtime.local_settings()


def test_unexpected_value_error_never_prints_secret(monkeypatch, capsys):
    monkeypatch.setattr(runtime.sys, "argv", ["local_runtime.py", "fingerprint"])

    def fail(_):
        raise ValueError("synthetic-secret-must-not-appear")

    monkeypatch.setattr(runtime, "fingerprint", fail)
    with pytest.raises(SystemExit):
        runtime.main()
    error = capsys.readouterr().err
    assert "ValueError" in error
    assert "synthetic-secret" not in error
