import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from nxtrep_backend.db.models import KnowledgeSource
from nxtrep_backend.knowledge.schemas import KnowledgeTopic

KnowledgeSourceType = Literal["manual", "file", "url"]
KnowledgeSourceRegistrationStatus = Literal["created", "unchanged"]

_SOURCE_KEY_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,118}[a-z0-9])?")


class KnowledgeSourceConflictError(RuntimeError):
    """同一个稳定键已经指向不同的来源元数据。"""


class KnowledgeSourceRepository(Protocol):
    async def get_source_by_key(
        self,
        source_key: str,
        *,
        lock: bool = False,
    ) -> KnowledgeSource | None: ...

    async def add_source(
        self,
        source: KnowledgeSource,
    ) -> KnowledgeSource: ...


@dataclass(frozen=True, slots=True)
class KnowledgeSourceRegistrationResult:
    status: KnowledgeSourceRegistrationStatus
    source: KnowledgeSource


class KnowledgeSourceService:
    """注册受管理员管理、默认不参与检索的知识来源。"""

    def __init__(self, repository: KnowledgeSourceRepository) -> None:
        self._repository = repository

    async def register(
        self,
        *,
        source_key: str,
        title: str,
        source_type: KnowledgeSourceType,
        source_uri: str | None,
        publisher: str | None,
        license_name: str | None,
        topic: KnowledgeTopic,
        locale: str,
        metadata: Mapping[str, object] | None = None,
    ) -> KnowledgeSourceRegistrationResult:
        values = self._normalize(
            source_key=source_key,
            title=title,
            source_type=source_type,
            source_uri=source_uri,
            publisher=publisher,
            license_name=license_name,
            topic=topic,
            locale=locale,
            metadata=metadata,
        )
        existing = await self._repository.get_source_by_key(
            values["source_key"],
            lock=True,
        )

        if existing is not None:
            if not self._matches(existing, values):
                raise KnowledgeSourceConflictError(
                    "Knowledge source key already uses different metadata"
                )
            return KnowledgeSourceRegistrationResult(
                status="unchanged",
                source=existing,
            )

        source = KnowledgeSource(
            **values,
            ingest_status="pending",
            is_active=False,
            latest_version=0,
        )
        await self._repository.add_source(source)
        return KnowledgeSourceRegistrationResult(
            status="created",
            source=source,
        )

    @staticmethod
    def _normalize(
        *,
        source_key: str,
        title: str,
        source_type: KnowledgeSourceType,
        source_uri: str | None,
        publisher: str | None,
        license_name: str | None,
        topic: KnowledgeTopic,
        locale: str,
        metadata: Mapping[str, object] | None,
    ) -> dict[str, object]:
        normalized_key = source_key.strip().lower()
        normalized_title = title.strip()
        normalized_uri = KnowledgeSourceService._optional(source_uri)
        normalized_publisher = KnowledgeSourceService._optional(publisher)
        normalized_license = KnowledgeSourceService._optional(license_name)
        normalized_locale = locale.strip()

        if _SOURCE_KEY_PATTERN.fullmatch(normalized_key) is None:
            raise ValueError(
                "source_key must use 1-120 lowercase letters, numbers, dots, "
                "underscores or hyphens and must start and end with a letter or number"
            )
        if not normalized_title or len(normalized_title) > 300:
            raise ValueError("title must contain 1-300 characters")
        if source_type not in {"manual", "file", "url"}:
            raise ValueError("source_type must be manual, file or url")
        if source_type != "manual" and normalized_uri is None:
            raise ValueError("source_uri is required for file and url sources")
        if normalized_publisher is not None and len(normalized_publisher) > 200:
            raise ValueError("publisher must not exceed 200 characters")
        if normalized_license is not None and len(normalized_license) > 120:
            raise ValueError("license_name must not exceed 120 characters")
        if not normalized_locale or len(normalized_locale) > 20:
            raise ValueError("locale must contain 1-20 characters")

        return {
            "source_key": normalized_key,
            "title": normalized_title,
            "source_type": source_type,
            "source_uri": normalized_uri,
            "publisher": normalized_publisher,
            "license_name": normalized_license,
            "topic": topic,
            "locale": normalized_locale,
            "metadata_json": dict(metadata or {}),
        }

    @staticmethod
    def _matches(
        source: KnowledgeSource,
        values: Mapping[str, object],
    ) -> bool:
        return all(getattr(source, field) == value for field, value in values.items())

    @staticmethod
    def _optional(value: str | None) -> str | None:
        normalized = value.strip() if value else ""
        return normalized or None
