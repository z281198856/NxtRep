from pathlib import Path
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

import nxtrep_backend.cli.import_knowledge as cli_module
from nxtrep_backend.repositories.knowledge import KnowledgePersistenceResult


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


class FakeIngestionService:
    def __init__(
        self,
        *,
        result: KnowledgePersistenceResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.received_source_id: UUID | None = None
        self.received_request = None

    async def ingest(self, *, source_id: UUID, request):
        self.received_source_id = source_id
        self.received_request = request
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def run_arguments(
    *,
    path: Path,
    source_id: UUID | None = None,
    dry_run: bool,
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "path": path,
        "source_key": "national-fitness-guide",
        "title": "全民健身指南",
        "topic": "training",
        "locale": "zh-CN",
        "content_type": "text/html",
        "dry_run": dry_run,
    }


def test_parser_accepts_path_alias_and_validates_choices() -> None:
    parser = cli_module.build_parser()

    args = parser.parse_args(
        [
            "--path",
            "guide.html",
            "--source-key",
            "guide",
            "--title",
            "Guide",
            "--topic",
            "training",
            "--content-type",
            "text/html",
            "--dry-run",
        ]
    )

    assert args.path == Path("guide.html")
    assert args.source_id is None
    assert args.locale == "zh-CN"
    assert args.dry_run is True


@pytest.mark.asyncio
async def test_dry_run_prepares_without_session_or_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "guide.html"
    source.write_text(
        "<html><body><article><p>动作稳定</p></article></body></html>",
        encoding="utf-8",
    )
    session_factory = Mock(side_effect=AssertionError("database must not be used"))
    service_builder = Mock(side_effect=AssertionError("GLM must not be used"))
    monkeypatch.setattr(cli_module, "SessionFactory", session_factory)
    monkeypatch.setattr(
        cli_module,
        "build_knowledge_ingestion_service",
        service_builder,
    )

    await cli_module.run_import(**run_arguments(path=source, dry_run=True))

    output = capsys.readouterr().out
    assert "status=prepared" in output
    assert "blocks=1" in output
    assert "chunks=1" in output
    assert "dry_run=true" in output
    session_factory.assert_not_called()
    service_builder.assert_not_called()


@pytest.mark.asyncio
async def test_formal_import_commits_and_prints_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "guide.html"
    source.write_text("<p>动作稳定</p>", encoding="utf-8")
    source_id = uuid4()
    result = KnowledgePersistenceResult(
        status="created",
        source_id=source_id,
        document_id=uuid4(),
        source_version=2,
        created_chunks=3,
        created_embeddings=3,
    )
    session = FakeSession()
    service = FakeIngestionService(result=result)
    monkeypatch.setattr(cli_module, "SessionFactory", lambda: session)
    monkeypatch.setattr(
        cli_module,
        "build_knowledge_ingestion_service",
        lambda **_: service,
    )

    await cli_module.run_import(
        **run_arguments(
            path=source,
            source_id=source_id,
            dry_run=False,
        )
    )

    assert session.commit_calls == 1
    assert session.rollback_calls == 0
    assert service.received_source_id == source_id
    assert service.received_request.path == source
    output = capsys.readouterr().out
    assert "status=created" in output
    assert "source_version=2" in output
    assert "dry_run=false" in output


@pytest.mark.asyncio
async def test_formal_import_rolls_back_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "guide.html"
    source.write_text("<p>动作稳定</p>", encoding="utf-8")
    session = FakeSession()
    service = FakeIngestionService(error=RuntimeError("embedding failed"))
    monkeypatch.setattr(cli_module, "SessionFactory", lambda: session)
    monkeypatch.setattr(
        cli_module,
        "build_knowledge_ingestion_service",
        lambda **_: service,
    )

    with pytest.raises(RuntimeError, match="embedding failed"):
        await cli_module.run_import(
            **run_arguments(
                path=source,
                source_id=uuid4(),
                dry_run=False,
            )
        )

    assert session.commit_calls == 0
    assert session.rollback_calls == 1


@pytest.mark.asyncio
async def test_formal_import_requires_source_id(tmp_path: Path) -> None:
    source = tmp_path / "guide.html"
    source.write_text("<p>动作稳定</p>", encoding="utf-8")

    with pytest.raises(ValueError, match="source_id"):
        await cli_module.run_import(
            **run_arguments(path=source, dry_run=False)
        )
