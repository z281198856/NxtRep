from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from nxtrep_backend.agents.tools import AgentToolContext
from nxtrep_backend.agents.tools.knowledge import build_knowledge_tools
from nxtrep_backend.knowledge.schemas import (
    KnowledgeRetrievalHit,
    KnowledgeRetrievalRequest,
)
from nxtrep_backend.services.knowledge_retrieval import KnowledgeRetrievalService


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
    )


def make_context(service: MagicMock | None) -> MagicMock:
    context = MagicMock(spec=AgentToolContext)
    context.knowledge_retrieval_service = service
    context.rag_candidate_k = 20
    context.rag_top_k = 5
    return context


def test_knowledge_tools_are_hidden_without_enabled_service() -> None:
    assert build_knowledge_tools(make_context(None)) == []


@pytest.mark.asyncio
async def test_retrieve_knowledge_returns_traceable_untrusted_evidence() -> None:
    service = MagicMock(spec=KnowledgeRetrievalService)
    hit = build_hit()
    service.retrieve = AsyncMock(return_value=(hit,))
    current_tool = build_knowledge_tools(make_context(service))[0]

    result = await current_tool.ainvoke(
        {
            "query": "如何安全深蹲？",
            "topic": "exercise",
            "locale": "zh-CN",
            "source_keys": ["official-guide"],
        }
    )

    assert current_tool.name == "retrieve_knowledge"
    assert "user_id" not in current_tool.args
    service.retrieve.assert_awaited_once_with(
        KnowledgeRetrievalRequest(
            query="如何安全深蹲？",
            topic="exercise",
            locale="zh-CN",
            candidate_k=20,
            top_k=5,
            source_keys=("official-guide",),
        )
    )
    assert result["status"] == "available"
    assert "untrusted" in result["trust_boundary"].lower()
    assert result["evidence"] == [
        {
            "content": hit.content,
            "score": hit.score,
            "match_type": hit.match_type,
            "citation": {
                "source_key": hit.source_key,
                "source_title": hit.source_title,
                "source_uri": hit.source_uri,
                "source_version": hit.source_version,
                "section_path": hit.section_path,
                "page_numbers": [12, 13],
            },
        }
    ]


@pytest.mark.asyncio
async def test_retrieve_knowledge_reports_no_evidence() -> None:
    service = MagicMock(spec=KnowledgeRetrievalService)
    service.retrieve = AsyncMock(return_value=())
    current_tool = build_knowledge_tools(make_context(service))[0]

    result = await current_tool.ainvoke(
        {
            "query": "没有资料的问题",
            "topic": "safety",
        }
    )

    assert result["status"] == "no_evidence"
    assert result["evidence"] == []
