from hashlib import sha256

import pytest

from nxtrep_backend.knowledge.chunker import ChunkingConfig, KnowledgeChunker
from nxtrep_backend.knowledge.schemas import ParsedBlock, ParsedDocument


class CharacterTokenCounter:
    """让测试中的一个字符稳定地等于一个 Token。"""

    @property
    def name(self) -> str:
        return "characters:v1"

    def count(self, text: str) -> int:
        return len(text)


def make_document(*blocks: ParsedBlock) -> ParsedDocument:
    return ParsedDocument(
        source_key="training-guide",
        title="训练指南",
        topic="training",
        locale="zh-CN",
        blocks=blocks,
    )


def test_chunker_splits_content_at_section_boundaries() -> None:
    document = make_document(
        ParsedBlock(
            text="第一章",
            kind="heading",
            section_path=("第一章",),
            page_number=1,
        ),
        ParsedBlock(
            text="动作稳定",
            section_path=("第一章",),
            page_number=1,
        ),
        ParsedBlock(
            text="第二章",
            kind="heading",
            section_path=("第二章",),
            page_number=2,
        ),
        ParsedBlock(
            text="逐步加量",
            section_path=("第二章",),
            page_number=2,
        ),
    )
    chunker = KnowledgeChunker(
        token_counter=CharacterTokenCounter(),
        config=ChunkingConfig(
            target_tokens=20,
            max_tokens=30,
            overlap_tokens=0,
        ),
    )

    chunks = chunker.chunk(document)

    assert len(chunks) == 2
    assert chunks[0].ordinal == 0
    assert chunks[0].content == "第一章\n\n动作稳定"
    assert chunks[0].section_path == "第一章"
    assert chunks[0].page_numbers == (1,)
    assert chunks[0].content_hash == sha256(
        chunks[0].content.encode("utf-8")
    ).hexdigest()
    assert chunks[0].metadata == {
        "chunking_version": "v1",
        "token_counter": "characters:v1",
        "source_block_count": 2,
    }
    assert chunks[1].ordinal == 1
    assert chunks[1].section_path == "第二章"
    assert chunks[1].page_numbers == (2,)


def test_chunker_reuses_trailing_blocks_as_overlap() -> None:
    document = make_document(
        ParsedBlock(text="aaaa"),
        ParsedBlock(text="bbbb"),
        ParsedBlock(text="cc"),
    )
    chunker = KnowledgeChunker(
        token_counter=CharacterTokenCounter(),
        config=ChunkingConfig(
            target_tokens=10,
            max_tokens=12,
            overlap_tokens=4,
        ),
    )

    chunks = chunker.chunk(document)

    assert [chunk.content for chunk in chunks] == [
        "aaaa\n\nbbbb",
        "bbbb\n\ncc",
    ]


def test_chunker_splits_one_oversized_block_below_maximum() -> None:
    document = make_document(ParsedBlock(text="abcdefghij"))
    chunker = KnowledgeChunker(
        token_counter=CharacterTokenCounter(),
        config=ChunkingConfig(
            target_tokens=4,
            max_tokens=4,
            overlap_tokens=0,
        ),
    )

    chunks = chunker.chunk(document)

    assert [chunk.content for chunk in chunks] == ["abcd", "efgh", "ij"]
    assert all(chunk.token_count <= 4 for chunk in chunks)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"target_tokens": 0}, "target_tokens must be positive"),
        (
            {"target_tokens": 10, "max_tokens": 9},
            "max_tokens must be greater than or equal to target_tokens",
        ),
        ({"overlap_tokens": -1}, "overlap_tokens must not be negative"),
        (
            {"target_tokens": 10, "overlap_tokens": 10},
            "overlap_tokens must be smaller than target_tokens",
        ),
    ],
)
def test_chunking_config_rejects_invalid_values(
    kwargs: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ChunkingConfig(**kwargs)
