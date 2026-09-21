from uuid import uuid4

import pytest

from nxtrep_backend.db.models import KnowledgeSource
from nxtrep_backend.services.knowledge_source import (
    KnowledgeSourceConflictError,
    KnowledgeSourceRegistrationResult,
    KnowledgeSourceService,
)


class FakeKnowledgeSourceRepository:
    def __init__(self) -> None:
        self.sources: dict[str, KnowledgeSource] = {}
        self.lock_values: list[bool] = []

    async def get_source_by_key(
        self,
        source_key: str,
        *,
        lock: bool = False,
    ) -> KnowledgeSource | None:
        self.lock_values.append(lock)
        return self.sources.get(source_key)

    async def add_source(self, source: KnowledgeSource) -> KnowledgeSource:
        source.id = uuid4()
        self.sources[source.source_key] = source
        return source


def registration_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "source_key": "national-fitness-guide",
        "title": "全民健身指南",
        "source_type": "url",
        "source_uri": "https://www.sport.gov.cn/guide",
        "publisher": "国家体育总局",
        "license_name": "All rights reserved",
        "topic": "training",
        "locale": "zh-CN",
        "metadata": {"review_status": "pending"},
    }
    values.update(overrides)
    return values


@pytest.mark.asyncio
async def test_register_creates_normalized_inactive_pending_source() -> None:
    repository = FakeKnowledgeSourceRepository()
    service = KnowledgeSourceService(repository)

    result = await service.register(
        **registration_values(
            source_key=" National-Fitness-Guide ",
            title=" 全民健身指南 ",
        )
    )

    assert isinstance(result, KnowledgeSourceRegistrationResult)
    assert result.status == "created"
    assert result.source.source_key == "national-fitness-guide"
    assert result.source.title == "全民健身指南"
    assert result.source.ingest_status == "pending"
    assert result.source.is_active is False
    assert result.source.latest_version == 0
    assert repository.lock_values == [True]


@pytest.mark.asyncio
async def test_register_is_idempotent_for_identical_metadata() -> None:
    service = KnowledgeSourceService(FakeKnowledgeSourceRepository())

    created = await service.register(**registration_values())
    unchanged = await service.register(**registration_values())

    assert created.status == "created"
    assert unchanged.status == "unchanged"
    assert unchanged.source is created.source


@pytest.mark.asyncio
async def test_register_rejects_same_key_with_different_metadata() -> None:
    service = KnowledgeSourceService(FakeKnowledgeSourceRepository())
    await service.register(**registration_values())

    with pytest.raises(KnowledgeSourceConflictError, match="different metadata"):
        await service.register(
            **registration_values(title="另一份指南")
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"source_key": "invalid key"}, "source_key"),
        ({"title": " "}, "title"),
        ({"source_type": "url", "source_uri": None}, "source_uri"),
        ({"locale": " "}, "locale"),
    ],
)
async def test_register_rejects_invalid_source_metadata(
    overrides: dict[str, object],
    message: str,
) -> None:
    service = KnowledgeSourceService(FakeKnowledgeSourceRepository())

    with pytest.raises(ValueError, match=message):
        await service.register(**registration_values(**overrides))
