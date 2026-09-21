from uuid import uuid4

import pytest

from nxtrep_backend.knowledge.schemas import (
    KnowledgeRetrievalHit,
    KnowledgeRetrievalRequest,
)


def request_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "query": "如何安全地进行深蹲？",
        "topic": "exercise",
        "locale": "zh-CN",
        "candidate_k": 20,
        "top_k": 5,
        "source_keys": (),
    }
    values.update(overrides)
    return values


def hit_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "chunk_id": uuid4(),
        "document_id": uuid4(),
        "source_id": uuid4(),
        "source_key": "national-fitness-guide",
        "source_title": "全民健身指南",
        "source_uri": "https://www.sport.gov.cn/guide",
        "source_version": 2,
        "topic": "exercise",
        "locale": "zh-CN",
        "content": "下蹲时保持膝盖与脚尖方向一致。",
        "section_path": "力量训练 > 深蹲",
        "page_numbers": (12, 13),
        "score": 0.82,
        "match_type": "hybrid",
        "metadata": {"audience": "adult"},
    }
    values.update(overrides)
    return values


def test_retrieval_request_preserves_explicit_filters_and_limits() -> None:
    request = KnowledgeRetrievalRequest(
        **request_values(source_keys=("national-fitness-guide",))
    )

    assert request.query == "如何安全地进行深蹲？"
    assert request.topic == "exercise"
    assert request.locale == "zh-CN"
    assert request.candidate_k == 20
    assert request.top_k == 5
    assert request.source_keys == ("national-fitness-guide",)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"query": "   "}, "query must not be blank"),
        ({"locale": "   "}, "locale must not be blank"),
        ({"candidate_k": 0}, "candidate_k must be between 1 and 100"),
        ({"candidate_k": 101}, "candidate_k must be between 1 and 100"),
        ({"top_k": 0}, "top_k must be between 1 and 10"),
        ({"top_k": 11}, "top_k must be between 1 and 10"),
        ({"candidate_k": 4, "top_k": 5}, "top_k must not exceed candidate_k"),
        ({"source_keys": ("valid", " ")}, "source_keys must not contain blanks"),
        ({"source_keys": ("same", "same")}, "source_keys must be unique"),
    ],
)
def test_retrieval_request_rejects_invalid_values(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        KnowledgeRetrievalRequest(**request_values(**overrides))


def test_retrieval_hit_contains_traceable_citation_fields() -> None:
    hit = KnowledgeRetrievalHit(**hit_values())

    assert hit.source_key == "national-fitness-guide"
    assert hit.source_version == 2
    assert hit.section_path == "力量训练 > 深蹲"
    assert hit.page_numbers == (12, 13)
    assert hit.match_type == "hybrid"
    assert hit.score == 0.82


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"source_key": " "}, "source_key must not be blank"),
        ({"source_title": " "}, "source_title must not be blank"),
        ({"source_version": 0}, "source_version must be positive"),
        ({"locale": " "}, "locale must not be blank"),
        ({"content": " "}, "content must not be blank"),
        ({"page_numbers": (0,)}, "page_numbers must contain positive values"),
        ({"score": -0.1}, "score must be between 0 and 1"),
        ({"score": 1.1}, "score must be between 0 and 1"),
        ({"score": float("nan")}, "score must be finite"),
        ({"match_type": "unknown"}, "match_type is invalid"),
    ],
)
def test_retrieval_hit_rejects_invalid_values(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        KnowledgeRetrievalHit(**hit_values(**overrides))
