from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import Literal
from uuid import UUID

BlockKind = Literal[
    "heading",
    "paragraph",
    "list",
    "table",
]

KnowledgeTopic = Literal[
    "exercise",
    "training",
    "nutrition",
    "product_help",
    "safety",
]


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    """Loader从PDF或HTML中提取的一个原始内容块。"""

    text: str
    kind: BlockKind = "paragraph"
    section_path: tuple[str, ...] = ()
    page_number: int | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("ParsedBlock.text must not be blank")

        if self.page_number is not None and self.page_number < 1:
            raise ValueError("ParsedBlock.page_number must be positive")


@dataclass(frozen=True, slots=True)
class KnowledgeLoadRequest:
    """描述一次知识文件加载任务。"""

    path: Path
    source_key: str
    title: str
    topic: KnowledgeTopic
    locale: str
    content_type: str

    def __post_init__(self) -> None:
        if not self.source_key.strip():
            raise ValueError("KnowledgeLoadRequest.source_key must not be blank")

        if not self.title.strip():
            raise ValueError("KnowledgeLoadRequest.title must not be blank")

        if not self.locale.strip():
            raise ValueError("KnowledgeLoadRequest.locale must not be blank")

        if not self.content_type.strip():
            raise ValueError("KnowledgeLoadRequest.content_type must not be blank")


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """一个原始文件解析完成后的中间结果。"""

    source_key: str
    title: str
    topic: KnowledgeTopic
    locale: str
    blocks: tuple[ParsedBlock, ...]
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_key.strip():
            raise ValueError("ParsedDocument.source_key must not be blank")

        if not self.title.strip():
            raise ValueError("ParsedDocument.title must not be blank")

        if not self.locale.strip():
            raise ValueError("ParsedDocument.locale must not be blank")

        if not self.blocks:
            raise ValueError("ParsedDocument.blocks must not be empty")


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    """切片完成、准备写入knowledge_chunks表的文本块。"""

    ordinal: int
    content: str
    content_hash: str
    token_count: int
    search_text: str
    section_path: str | None = None
    page_numbers: tuple[int, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("ChunkDraft.ordinal must not be negative")

        if not self.content.strip():
            raise ValueError("ChunkDraft.content must not be blank")

        if len(self.content_hash) != 64:
            raise ValueError("ChunkDraft.content_hash must be a SHA-256 hex digest")

        try:
            int(self.content_hash, 16)
        except ValueError as exc:
            raise ValueError("ChunkDraft.content_hash must be a SHA-256 hex digest") from exc

        if self.token_count < 1:
            raise ValueError("ChunkDraft.token_count must be positive")

        if not self.search_text.strip():
            raise ValueError("ChunkDraft.search_text must not be blank")

        if any(page_number < 1 for page_number in self.page_numbers):
            raise ValueError("ChunkDraft.page_numbers must contain positive values")


@dataclass(frozen=True, slots=True)
class PreparedKnowledgeDocument:
    """完成加载、清洗和切块，等待向量化与持久化的文档。"""

    document: ParsedDocument
    normalized_content: str
    content_hash: str
    chunks: tuple[ChunkDraft, ...]

    def __post_init__(self) -> None:
        if not self.normalized_content.strip():
            raise ValueError("PreparedKnowledgeDocument.normalized_content must not be blank")

        if len(self.content_hash) != 64:
            raise ValueError("PreparedKnowledgeDocument.content_hash must be a SHA-256 hex digest")

        try:
            int(self.content_hash, 16)
        except ValueError as exc:
            raise ValueError(
                "PreparedKnowledgeDocument.content_hash must be a SHA-256 hex digest"
            ) from exc

        if not self.chunks:
            raise ValueError("PreparedKnowledgeDocument.chunks must not be empty")


@dataclass(frozen=True, slots=True)
class EmbeddedKnowledgeDocument:
    """切片向量化完成、等待一次性写入数据库的文档。"""

    prepared: PreparedKnowledgeDocument
    model_name: str
    model_version: str
    dimensions: int
    vectors: tuple[tuple[float, ...], ...]

    def __post_init__(self) -> None:
        if not self.model_name.strip():
            raise ValueError("EmbeddedKnowledgeDocument.model_name must not be blank")

        if not self.model_version.strip():
            raise ValueError("EmbeddedKnowledgeDocument.model_version must not be blank")

        if self.dimensions < 1:
            raise ValueError("EmbeddedKnowledgeDocument.dimensions must be positive")

        if len(self.vectors) != len(self.prepared.chunks):
            raise ValueError("EmbeddedKnowledgeDocument must contain one vector per chunk")

        if any(len(vector) != self.dimensions for vector in self.vectors):
            raise ValueError("EmbeddedKnowledgeDocument vector dimensions do not match")

        if any(not isfinite(value) for vector in self.vectors for value in vector):
            raise ValueError("EmbeddedKnowledgeDocument vectors must contain finite values")


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalRequest:
    """一次知识检索的查询、过滤条件和数量限制。"""

    query: str
    topic: KnowledgeTopic
    locale: str
    candidate_k: int = 20
    top_k: int = 5
    source_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("KnowledgeRetrievalRequest.query must not be blank")

        if not self.locale.strip():
            raise ValueError("KnowledgeRetrievalRequest.locale must not be blank")

        if not 1 <= self.candidate_k <= 100:
            raise ValueError("KnowledgeRetrievalRequest.candidate_k must be between 1 and 100")

        if not 1 <= self.top_k <= 10:
            raise ValueError("KnowledgeRetrievalRequest.top_k must be between 1 and 10")

        if self.top_k > self.candidate_k:
            raise ValueError("KnowledgeRetrievalRequest.top_k must not exceed candidate_k")

        if any(not source_key.strip() for source_key in self.source_keys):
            raise ValueError("KnowledgeRetrievalRequest.source_keys must not contain blanks")

        if len(set(self.source_keys)) != len(self.source_keys):
            raise ValueError("KnowledgeRetrievalRequest.source_keys must be unique")


KnowledgeMatchType = Literal["full_text", "vector", "hybrid"]


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalHit:
    """一个带完整来源信息、可以安全引用的知识片段。"""

    chunk_id: UUID
    document_id: UUID
    source_id: UUID
    source_key: str
    source_title: str
    source_uri: str | None
    source_version: int
    topic: KnowledgeTopic
    locale: str
    content: str
    section_path: str | None
    page_numbers: tuple[int, ...]
    score: float
    match_type: KnowledgeMatchType
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_key.strip():
            raise ValueError("KnowledgeRetrievalHit.source_key must not be blank")

        if not self.source_title.strip():
            raise ValueError("KnowledgeRetrievalHit.source_title must not be blank")

        if self.source_version < 1:
            raise ValueError("KnowledgeRetrievalHit.source_version must be positive")

        if not self.locale.strip():
            raise ValueError("KnowledgeRetrievalHit.locale must not be blank")

        if not self.content.strip():
            raise ValueError("KnowledgeRetrievalHit.content must not be blank")

        if any(page_number < 1 for page_number in self.page_numbers):
            raise ValueError("KnowledgeRetrievalHit.page_numbers must contain positive values")

        if not isfinite(self.score):
            raise ValueError("KnowledgeRetrievalHit.score must be finite")

        if not 0 <= self.score <= 1:
            raise ValueError("KnowledgeRetrievalHit.score must be between 0 and 1")

        if self.match_type not in {"full_text", "vector", "hybrid"}:
            raise ValueError("KnowledgeRetrievalHit.match_type is invalid")
