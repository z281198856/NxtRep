import re
import unicodedata
from dataclasses import replace

from nxtrep_backend.knowledge.schemas import (
    BlockKind,
    ParsedBlock,
    ParsedDocument,
)

_PAGE_NUMBER_PATTERN = re.compile(r"^[—–-]\s*\d+\s*[—–-]$")

_SPACE_PATTERN = re.compile(r"[ \t\f\v]+")

_HEADING_PATTERNS: tuple[
    tuple[int, re.Pattern[str]],
    ...,
] = (
    (
        1,
        re.compile(r"^[一二三四五六七八九十百]+[、.]\s*\S"),
    ),
    (
        2,
        re.compile(r"^[（(][一二三四五六七八九十百]+[）)]\s*\S"),
    ),
    (
        3,
        re.compile(r"^\d+[.、]\s*\S"),
    ),
)

_LIST_PREFIXES = (
    "•",
    "●",
    "▪",
    "——",
)


class KnowledgeNormalizationError(RuntimeError):
    """知识文档清洗后没有可用内容。"""


class KnowledgeTextNormalizer:
    """对PDF和HTML Loader生成的文本执行确定性清洗。"""

    VERSION = "v1"

    def normalize(
        self,
        document: ParsedDocument,
    ) -> ParsedDocument:
        normalized_blocks: list[ParsedBlock] = []
        heading_path: list[str] = []

        for block in document.blocks:
            if block.section_path:
                heading_path = list(block.section_path)

            for fragment in self._split_fragments(block):
                text = self._normalize_text(fragment)

                if not text:
                    continue

                kind = self._infer_kind(
                    block,
                    text,
                )

                if kind == "heading":
                    heading_path = self._update_heading_path(
                        block=block,
                        text=text,
                        current_path=heading_path,
                    )

                section_path = tuple(heading_path) if heading_path else block.section_path

                normalized_block = replace(
                    block,
                    text=text,
                    kind=kind,
                    section_path=section_path,
                )

                if self._is_duplicate(
                    normalized_blocks,
                    normalized_block,
                ):
                    continue

                normalized_blocks.append(normalized_block)

        if not normalized_blocks:
            raise KnowledgeNormalizationError(
                f"Document contains no usable content: {document.source_key}"
            )

        metadata = dict(document.metadata)
        metadata["normalization_version"] = self.VERSION

        return replace(
            document,
            blocks=tuple(normalized_blocks),
            metadata=metadata,
        )

    @staticmethod
    def _split_fragments(
        block: ParsedBlock,
    ) -> tuple[str, ...]:
        source_format = block.metadata.get("source_format")

        if source_format == "html":
            return tuple(block.text.splitlines())

        return (block.text,)

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = unicodedata.normalize("NFC", text)
        text = text.replace("\r\n", "\n")
        text = text.replace("\r", "\n")
        text = text.replace("\u00a0", " ")
        text = text.replace("\u3000", " ")
        text = text.replace("\u200b", "")
        text = text.replace("\ufeff", "")

        lines = [_SPACE_PATTERN.sub(" ", line).strip() for line in text.splitlines()]
        lines = [line for line in lines if line]

        if lines and _PAGE_NUMBER_PATTERN.fullmatch(lines[0]):
            lines.pop(0)

        if lines and _PAGE_NUMBER_PATTERN.fullmatch(lines[-1]):
            lines.pop()

        return KnowledgeTextNormalizer._join_lines(lines)

    @staticmethod
    def _join_lines(lines: list[str]) -> str:
        if not lines:
            return ""

        result = lines[0]

        for line in lines[1:]:
            previous_character = result[-1]
            next_character = line[0]

            if (
                previous_character == "-"
                or (next_character == "-" and previous_character.isalnum())
                or (
                    KnowledgeTextNormalizer._is_cjk(previous_character)
                    and KnowledgeTextNormalizer._is_cjk(next_character)
                )
                or next_character in "，。！？；：、,.!?;:)]}）】》"
            ):
                separator = ""
            else:
                separator = " "

            result = f"{result}{separator}{line}"

        return result.strip()

    def _infer_kind(
        self,
        block: ParsedBlock,
        text: str,
    ) -> BlockKind:
        if block.kind != "paragraph":
            return block.kind

        if text.startswith(_LIST_PREFIXES):
            return "list"

        if self._heading_level(text) is not None:
            return "heading"

        return "paragraph"

    @staticmethod
    def _heading_level(text: str) -> int | None:
        if len(text) > 100:
            return None

        for level, pattern in _HEADING_PATTERNS:
            if pattern.match(text):
                return level

        letters = [character for character in text if character.isalpha()]

        if (
            letters
            and len(text.split()) <= 14
            and all(character.isupper() for character in letters)
        ):
            return 1

        return None

    def _update_heading_path(
        self,
        *,
        block: ParsedBlock,
        text: str,
        current_path: list[str],
    ) -> list[str]:
        source_tag = block.metadata.get("source_tag")

        if (
            block.kind == "heading"
            and isinstance(source_tag, str)
            and source_tag
            in {
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
            }
        ):
            level = int(source_tag[1])
        else:
            level = self._heading_level(text) or 1

        new_path = current_path[: level - 1]
        new_path.append(text)

        return new_path

    @staticmethod
    def _is_duplicate(
        existing: list[ParsedBlock],
        candidate: ParsedBlock,
    ) -> bool:
        if not existing:
            return False

        previous = existing[-1]

        return previous.text == candidate.text and previous.page_number == candidate.page_number

    @staticmethod
    def _is_cjk(character: str) -> bool:
        return "\u3400" <= character <= "\u4dbf" or "\u4e00" <= character <= "\u9fff"
