from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

import nxtrep_backend.cli.register_knowledge_source as cli_module
from nxtrep_backend.db.models import KnowledgeSource
from nxtrep_backend.services.knowledge_source import (
    KnowledgeSourceRegistrationResult,
)


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1


def registration_arguments() -> dict[str, object]:
    return {
        "source_key": "national-fitness-guide",
        "title": "全民健身指南",
        "source_type": "url",
        "source_uri": "https://www.sport.gov.cn/guide",
        "publisher": "国家体育总局",
        "license_name": "All rights reserved",
        "topic": "training",
        "locale": "zh-CN",
    }


def test_parser_does_not_offer_direct_activation() -> None:
    parser = cli_module.build_parser()
    destinations = {action.dest for action in parser._actions}

    assert "source_key" in destinations
    assert "source_type" in destinations
    assert "active" not in destinations
    assert "is_active" not in destinations


@pytest.mark.asyncio
async def test_registration_commits_and_prints_safe_initial_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = FakeSession()
    source = KnowledgeSource(
        id=uuid4(),
        source_key="national-fitness-guide",
        title="全民健身指南",
        source_type="url",
        source_uri="https://www.sport.gov.cn/guide",
        topic="training",
        locale="zh-CN",
        ingest_status="pending",
        is_active=False,
    )
    service = SimpleNamespace(
        register=Mock()
    )

    async def register(**_: object) -> KnowledgeSourceRegistrationResult:
        return KnowledgeSourceRegistrationResult(
            status="created",
            source=source,
        )

    service.register = register
    monkeypatch.setattr(cli_module, "SessionFactory", lambda: session)
    monkeypatch.setattr(
        cli_module,
        "SqlAlchemyKnowledgeRepository",
        lambda _: object(),
    )
    monkeypatch.setattr(
        cli_module,
        "KnowledgeSourceService",
        lambda repository: service,
    )

    await cli_module.run_registration(**registration_arguments())

    assert session.commit_calls == 1
    assert session.rollback_calls == 0
    output = capsys.readouterr().out
    assert "status=created" in output
    assert "ingest_status=pending" in output
    assert "active=false" in output


@pytest.mark.asyncio
async def test_registration_rolls_back_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()

    async def register(**_: object) -> None:
        raise RuntimeError("database failed")

    service = SimpleNamespace(register=register)
    monkeypatch.setattr(cli_module, "SessionFactory", lambda: session)
    monkeypatch.setattr(
        cli_module,
        "SqlAlchemyKnowledgeRepository",
        lambda _: object(),
    )
    monkeypatch.setattr(
        cli_module,
        "KnowledgeSourceService",
        lambda repository: service,
    )

    with pytest.raises(RuntimeError, match="database failed"):
        await cli_module.run_registration(**registration_arguments())

    assert session.commit_calls == 0
    assert session.rollback_calls == 1
