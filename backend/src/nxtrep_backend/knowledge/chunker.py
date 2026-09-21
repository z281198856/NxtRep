import re
from dataclasses import dataclass, replace
from hashlib import sha256

from nxtrep_backend.knowledge.schemas import ChunkDraft, ParsedBlock, ParsedDocument
from nxtrep_backend.knowledge.token_counter import (
    TiktokenTokenCounter,
    TokenCounter,
)

_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;])|(?<=\.)\s+|\n+")


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    """知识切片大小配置。"""

    target_tokens: int = 700
    max_tokens: int = 1000
    overlap_tokens: int = 100

    def __post_init__(self) -> None:
        if self.target_tokens < 1:
            raise ValueError("target_tokens must be positive")

        if self.max_tokens < self.target_tokens:
            raise ValueError("max_tokens must be greater than or equal to target_tokens")

        if self.overlap_tokens < 0:
            raise ValueError("overlap_tokens must not be negative")

        if self.overlap_tokens >= self.target_tokens:
            raise ValueError("overlap_tokens must be smaller than target_tokens")


class KnowledgeChunkingError(RuntimeError):
    """文档无法生成有效知识切片。"""


class KnowledgeChunker:
    """按章节、Token长度和句子边界生成知识切片。"""

    VERSION = "v1"

    def __init__(
        self,
        token_counter: TokenCounter | None = None,
        config: ChunkingConfig | None = None,
    ) -> None:
        self._token_counter = token_counter or TiktokenTokenCounter()
        self._config = config or ChunkingConfig()

    def chunk(
        self,
        document: ParsedDocument,
    ) -> tuple[ChunkDraft, ...]:
        blocks = self._expand_oversized_blocks(document.blocks)

        drafts: list[ChunkDraft] = []
        current_blocks: list[ParsedBlock] = []

        for block in blocks:
            if self._starts_new_section(
                current_blocks,
                block,
            ):
                self._append_draft(
                    drafts,
                    current_blocks,
                )
                current_blocks = []

            if not current_blocks:
                current_blocks = [block]
                continue

            candidate = [
                *current_blocks,
                block,
            ]

            if self._count_blocks(candidate) <= self._config.target_tokens:
                current_blocks = candidate
                continue

            self._append_draft(
                drafts,
                current_blocks,
            )

            overlap = self._build_overlap(current_blocks)
            candidate = [
                *overlap,
                block,
            ]

            if self._count_blocks(candidate) <= self._config.max_tokens:
                current_blocks = candidate
            else:
                current_blocks = [block]

        self._append_draft(
            drafts,
            current_blocks,
        )

        if not drafts:
            raise KnowledgeChunkingError(f"Document produced no chunks: {document.source_key}")

        return tuple(drafts)

    def _expand_oversized_blocks(
        self,
        blocks: tuple[ParsedBlock, ...],
    ) -> tuple[ParsedBlock, ...]:
        expanded: list[ParsedBlock] = []

        for block in blocks:
            expanded.extend(self._split_oversized_block(block))

        return tuple(expanded)

    def _split_oversized_block(
        self,
        block: ParsedBlock,
    ) -> tuple[ParsedBlock, ...]:
        if self._token_counter.count(block.text) <= self._config.max_tokens:
            return (block,)

        sentence_parts = [
            part.strip() for part in _SENTENCE_BOUNDARY.split(block.text) if part.strip()
        ]

        pieces: list[str] = []
        current_parts: list[str] = []

        for part in sentence_parts:
            if self._token_counter.count(part) > self._config.max_tokens:
                if current_parts:
                    pieces.append("\n".join(current_parts))
                    current_parts = []

                pieces.extend(self._split_by_character(part))
                continue

            candidate = "\n".join(
                [
                    *current_parts,
                    part,
                ]
            )

            if current_parts and self._token_counter.count(candidate) > self._config.max_tokens:
                pieces.append("\n".join(current_parts))
                current_parts = [part]
            else:
                current_parts.append(part)

        if current_parts:
            pieces.append("\n".join(current_parts))

        return tuple(
            replace(
                block,
                text=piece,
            )
            for piece in pieces
            if piece
        )

    def _split_by_character(
        self,
        text: str,
    ) -> list[str]:
        pieces: list[str] = []
        remaining = text

        while remaining:
            low = 1
            high = len(remaining)
            best_length = 1

            while low <= high:
                middle = (low + high) // 2
                candidate = remaining[:middle]

                if self._token_counter.count(candidate) <= self._config.max_tokens:
                    best_length = middle
                    low = middle + 1
                else:
                    high = middle - 1

            piece = remaining[:best_length].strip()

            if piece:
                pieces.append(piece)

            remaining = remaining[best_length:]

        return pieces

    @staticmethod
    def _starts_new_section(
        current_blocks: list[ParsedBlock],
        block: ParsedBlock,
    ) -> bool:
        if not current_blocks:
            return False

        current_section = current_blocks[-1].section_path

        return block.kind == "heading" or (
            bool(block.section_path) and block.section_path != current_section
        )

    def _build_overlap(
        self,
        blocks: list[ParsedBlock],
    ) -> list[ParsedBlock]:
        if self._config.overlap_tokens == 0:
            return []

        overlap: list[ParsedBlock] = []

        for block in reversed(blocks):
            candidate = [
                block,
                *overlap,
            ]

            if self._count_blocks(candidate) > self._config.overlap_tokens:
                break

            overlap = candidate

        return overlap

    def _append_draft(
        self,
        drafts: list[ChunkDraft],
        blocks: list[ParsedBlock],
    ) -> None:
        if not blocks:
            return

        content = self._join_blocks(blocks)
        token_count = self._token_counter.count(content)

        if token_count > self._config.max_tokens:
            raise KnowledgeChunkingError(f"Chunk exceeds max_tokens: {token_count}")

        section_tuple = blocks[-1].section_path
        section_path = " > ".join(section_tuple) if section_tuple else None

        page_numbers = tuple(
            sorted({block.page_number for block in blocks if block.page_number is not None})
        )

        search_text = f"{section_path}\n{content}" if section_path else content

        content_hash = sha256(content.encode("utf-8")).hexdigest()

        drafts.append(
            ChunkDraft(
                ordinal=len(drafts),
                content=content,
                content_hash=content_hash,
                token_count=token_count,
                search_text=search_text,
                section_path=section_path,
                page_numbers=page_numbers,
                metadata={
                    "chunking_version": self.VERSION,
                    "token_counter": (self._token_counter.name),
                    "source_block_count": len(blocks),
                },
            )
        )

    def _count_blocks(
        self,
        blocks: list[ParsedBlock],
    ) -> int:
        return self._token_counter.count(self._join_blocks(blocks))

    @staticmethod
    def _join_blocks(
        blocks: list[ParsedBlock],
    ) -> str:
        return "\n\n".join(block.text for block in blocks).strip()
