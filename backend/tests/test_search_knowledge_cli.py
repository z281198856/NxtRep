import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

import nxtrep_backend.cli.search_knowledge as cli_module
from nxtrep_backend.knowledge.schemas import (
    KnowledgeRetrievalHit,
    KnowledgeRetrievalRequest,
)


class FakeSession:
    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        return None


def build_hit() -> KnowledgeRetrievalHit:
    return KnowledgeRetrievalHit(
        chunk_id=uuid4(),
        document_id=uuid4(),
        source_id=uuid4(),
        source_key="official-guide",
        source_title="全民健身指南",
        source_uri="https://www.sport.gov.cn/guide",
        source_version=2,
        topic="exercise",
        locale="zh-CN",
        content="下蹲时保持膝盖与脚尖方向一致。",
        section_path="力量训练 > 深蹲",
        page_numbers=(12, 13),
        score=0.91,
        match_type="hybrid",
        metadata={"audience": "adult"},
    )


def test_parser_accepts_filters_limits_and_repeated_source_keys() -> None:
    args = cli_module.build_parser().parse_args(
        [
            "--query",
            "如何安全深蹲？",
            "--topic",
            "exercise",
            "--locale",
            "zh-CN",
            "--candidate-k",
            "30",
            "--top-k",
            "6",
            "--source-key",
            "guide-a",
            "--source-key",
            "guide-b",
        ]
    )

    assert args.query == "如何安全深蹲？"
    assert args.topic == "exercise"
    assert args.locale == "zh-CN"
    assert args.candidate_k == 30
    assert args.top_k == 6
    assert args.source_keys == ["guide-a", "guide-b"]


@pytest.mark.asyncio
async def test_search_builds_request_and_prints_traceable_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = FakeSession()
    settings = object()
    received_requests: list[KnowledgeRetrievalRequest] = []
    hit = build_hit()

    async def retrieve(
        request: KnowledgeRetrievalRequest,
    ) -> tuple[KnowledgeRetrievalHit, ...]:
        received_requests.append(request)
        return (hit,)

    service = SimpleNamespace(retrieve=retrieve)
    monkeypatch.setattr(cli_module, "SessionFactory", lambda: session)
    monkeypatch.setattr(cli_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        cli_module,
        "build_knowledge_retrieval_service",
        lambda *, session, settings: service,
    )

    await cli_module.run_search(
        query="如何安全深蹲？",
        topic="exercise",
        locale="zh-CN",
        candidate_k=30,
        top_k=6,
        source_keys=["official-guide"],
    )

    assert received_requests == [
        KnowledgeRetrievalRequest(
            query="如何安全深蹲？",
            topic="exercise",
            locale="zh-CN",
            candidate_k=30,
            top_k=6,
            source_keys=("official-guide",),
        )
    ]
    payload = json.loads(capsys.readouterr().out)
    assert payload["query"] == "如何安全深蹲？"
    assert payload["count"] == 1
    assert payload["hits"] == [
        {
            "chunk_id": str(hit.chunk_id),
            "content": hit.content,
            "score": hit.score,
            "match_type": "hybrid",
            "source_key": "official-guide",
            "source_title": "全民健身指南",
            "source_uri": "https://www.sport.gov.cn/guide",
            "source_version": 2,
            "section_path": "力量训练 > 深蹲",
            "page_numbers": [12, 13],
        }
    ]
