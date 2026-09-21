from uuid import UUID, uuid4

import pytest

from nxtrep_backend.knowledge.schemas import KnowledgeRetrievalHit
from nxtrep_backend.services.knowledge_retrieval import KnowledgeRetrievalMerger


def build_hit(
    chunk_id: UUID,
    *,
    match_type: str,
    source_key: str,
) -> KnowledgeRetrievalHit:
    return KnowledgeRetrievalHit(
        chunk_id=chunk_id,
        document_id=uuid4(),
        source_id=uuid4(),
        source_key=source_key,
        source_title=f"Source {source_key}",
        source_uri=f"https://example.com/{source_key}",
        source_version=1,
        topic="exercise",
        locale="zh-CN",
        content=f"Content for {source_key}",
        section_path="深蹲",
        page_numbers=(1,),
        score=0.5,
        match_type=match_type,
    )


def test_merger_deduplicates_and_prioritizes_hits_from_both_channels() -> None:
    shared_id = uuid4()
    text_only_id = uuid4()
    vector_only_id = uuid4()
    full_text_hits = (
        build_hit(
            text_only_id,
            match_type="full_text",
            source_key="text-only",
        ),
        build_hit(
            shared_id,
            match_type="full_text",
            source_key="shared",
        ),
    )
    vector_hits = (
        build_hit(
            shared_id,
            match_type="vector",
            source_key="shared",
        ),
        build_hit(
            vector_only_id,
            match_type="vector",
            source_key="vector-only",
        ),
    )

    result = KnowledgeRetrievalMerger().merge(
        full_text_hits=full_text_hits,
        vector_hits=vector_hits,
        top_k=3,
    )

    assert [hit.chunk_id for hit in result] == [
        shared_id,
        text_only_id,
        vector_only_id,
    ]
    assert len({hit.chunk_id for hit in result}) == 3
    assert result[0].match_type == "hybrid"
    assert result[1].match_type == "full_text"
    assert result[2].match_type == "vector"
    assert result[0].score > result[1].score
    assert all(0 <= hit.score <= 1 for hit in result)


def test_merger_respects_top_k() -> None:
    full_text_hits = tuple(
        build_hit(
            uuid4(),
            match_type="full_text",
            source_key=f"source-{index}",
        )
        for index in range(5)
    )

    result = KnowledgeRetrievalMerger().merge(
        full_text_hits=full_text_hits,
        vector_hits=(),
        top_k=2,
    )

    assert [hit.chunk_id for hit in result] == [
        hit.chunk_id for hit in full_text_hits[:2]
    ]
    assert all(hit.match_type == "full_text" for hit in result)


def test_merger_returns_empty_tuple_for_no_candidates() -> None:
    result = KnowledgeRetrievalMerger().merge(
        full_text_hits=(),
        vector_hits=(),
        top_k=5,
    )

    assert result == ()


def test_merger_rejects_invalid_top_k() -> None:
    with pytest.raises(ValueError, match="top_k must be positive"):
        KnowledgeRetrievalMerger().merge(
            full_text_hits=(),
            vector_hits=(),
            top_k=0,
        )
