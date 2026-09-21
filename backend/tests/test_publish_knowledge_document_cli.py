from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

import nxtrep_backend.cli.publish_knowledge_document as cli_module
from nxtrep_backend.db.models import KnowledgeDocument
from nxtrep_backend.services.knowledge_document_publication import (
    KnowledgePublicationResult,
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


def test_parser_converts_document_id_to_uuid() -> None:
    document_id = uuid4()

    args = cli_module.build_parser().parse_args(
        ["--document-id", str(document_id)]
    )

    assert isinstance(args.document_id, UUID)
    assert args.document_id == document_id


@pytest.mark.asyncio
async def test_publication_commits_and_prints_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = FakeSession()
    published_at = datetime.now(UTC)
    document = KnowledgeDocument(
        id=uuid4(),
        source_id=uuid4(),
        source_version=2,
        title="全民健身指南 v2",
        normalized_content="每天保持适量运动。",
        content_hash="b" * 64,
        topic="training",
        locale="zh-CN",
        review_status="published",
        published_at=published_at,
        metadata_json={},
    )
    service = SimpleNamespace(publish=Mock())

    async def publish(_: UUID) -> KnowledgePublicationResult:
        return KnowledgePublicationResult(
            status="published",
            document=document,
        )

    service.publish = publish
    monkeypatch.setattr(cli_module, "SessionFactory", lambda: session)
    monkeypatch.setattr(
        cli_module,
        "SqlAlchemyKnowledgeRepository",
        lambda _: object(),
    )
    monkeypatch.setattr(
        cli_module,
        "KnowledgeDocumentPublicationService",
        lambda repository: service,
    )

    await cli_module.run_publication(document.id)

    assert session.commit_calls == 1
    assert session.rollback_calls == 0
    output = capsys.readouterr().out
    assert "status=published" in output
    assert f"document_id={document.id}" in output
    assert "review_status=published" in output
    assert f"published_at={published_at.isoformat()}" in output


@pytest.mark.asyncio
async def test_publication_rolls_back_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()

    async def publish(_: UUID) -> None:
        raise RuntimeError("database failed")

    service = SimpleNamespace(publish=publish)
    monkeypatch.setattr(cli_module, "SessionFactory", lambda: session)
    monkeypatch.setattr(
        cli_module,
        "SqlAlchemyKnowledgeRepository",
        lambda _: object(),
    )
    monkeypatch.setattr(
        cli_module,
        "KnowledgeDocumentPublicationService",
        lambda repository: service,
    )

    with pytest.raises(RuntimeError, match="database failed"):
        await cli_module.run_publication(uuid4())

    assert session.commit_calls == 0
    assert session.rollback_calls == 1
