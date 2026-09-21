from hashlib import sha256
from pathlib import Path

import pytest

from nxtrep_backend.knowledge.loaders.base import KnowledgeDocumentLoader
from nxtrep_backend.knowledge.schemas import (
    ChunkDraft,
    KnowledgeLoadRequest,
    ParsedBlock,
    ParsedDocument,
)


class StubDocumentLoader:
    @property
    def supported_content_types(self) -> frozenset[str]:
        return frozenset({"text/plain"})

    def load(self, request: KnowledgeLoadRequest) -> ParsedDocument:
        return ParsedDocument(
            source_key=request.source_key,
            title=request.title,
            topic=request.topic,
            locale=request.locale,
            blocks=(ParsedBlock(text="Loaded content"),),
        )


def _load_with_contract(
    loader: KnowledgeDocumentLoader,
    request: KnowledgeLoadRequest,
) -> ParsedDocument:
    return loader.load(request)


def test_knowledge_load_request_and_loader_contract() -> None:
    request = KnowledgeLoadRequest(
        path=Path("guideline.txt"),
        source_key="test-guideline",
        title="Test Guideline",
        topic="training",
        locale="en",
        content_type="text/plain",
    )

    loader = StubDocumentLoader()
    document = _load_with_contract(loader, request)

    assert loader.supported_content_types == frozenset({"text/plain"})
    assert document.source_key == request.source_key
    assert document.blocks[0].text == "Loaded content"


@pytest.mark.parametrize("field", ["source_key", "title", "locale", "content_type"])
def test_knowledge_load_request_rejects_blank_required_fields(field: str) -> None:
    values = {
        "path": Path("guideline.pdf"),
        "source_key": "who-guidelines",
        "title": "WHO Guidelines",
        "topic": "training",
        "locale": "en",
        "content_type": "application/pdf",
    }
    values[field] = "   "

    with pytest.raises(ValueError, match=field):
        KnowledgeLoadRequest(**values)


def test_parsed_document_preserves_source_structure() -> None:
    heading = ParsedBlock(
        text="Recommendations for adults",
        kind="heading",
        section_path=("Recommendations",),
        page_number=24,
    )
    paragraph = ParsedBlock(
        text="Adults should undertake regular physical activity.",
        section_path=("Recommendations", "Adults"),
        page_number=24,
    )

    document = ParsedDocument(
        source_key="who-2020-physical-activity-guidelines",
        title="WHO Guidelines on Physical Activity",
        topic="training",
        locale="en",
        blocks=(heading, paragraph),
    )

    assert document.blocks == (heading, paragraph)
    assert document.blocks[1].section_path == ("Recommendations", "Adults")
    assert document.blocks[1].page_number == 24


def test_parsed_block_rejects_blank_text_and_invalid_page_number() -> None:
    with pytest.raises(ValueError, match="text must not be blank"):
        ParsedBlock(text="   ")

    with pytest.raises(ValueError, match="page_number must be positive"):
        ParsedBlock(text="Valid text", page_number=0)


@pytest.mark.parametrize("field", ["source_key", "title", "locale"])
def test_parsed_document_rejects_blank_required_fields(field: str) -> None:
    values = {
        "source_key": "who-guidelines",
        "title": "WHO Guidelines",
        "topic": "training",
        "locale": "en",
        "blocks": (ParsedBlock(text="Valid text"),),
    }
    values[field] = "   "

    with pytest.raises(ValueError, match=field):
        ParsedDocument(**values)


def test_parsed_document_rejects_empty_blocks() -> None:
    with pytest.raises(ValueError, match="blocks must not be empty"):
        ParsedDocument(
            source_key="who-guidelines",
            title="WHO Guidelines",
            topic="training",
            locale="en",
            blocks=(),
        )


def test_chunk_draft_matches_knowledge_chunk_write_shape() -> None:
    content = "Adults should undertake regular physical activity."
    content_hash = sha256(content.encode("utf-8")).hexdigest()

    chunk = ChunkDraft(
        ordinal=0,
        content=content,
        content_hash=content_hash,
        token_count=8,
        search_text=f"Recommendations Adults {content}",
        section_path="Recommendations > Adults",
        page_numbers=(24, 25),
    )

    assert chunk.content_hash == content_hash
    assert chunk.page_numbers == (24, 25)
    assert chunk.section_path == "Recommendations > Adults"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"ordinal": -1}, "ordinal must not be negative"),
        ({"content": "  "}, "content must not be blank"),
        ({"content_hash": "a" * 63}, "SHA-256 hex digest"),
        ({"content_hash": "z" * 64}, "SHA-256 hex digest"),
        ({"token_count": 0}, "token_count must be positive"),
        ({"search_text": "  "}, "search_text must not be blank"),
        ({"page_numbers": (0,)}, "page_numbers must contain positive values"),
    ],
)
def test_chunk_draft_rejects_invalid_values(
    overrides: dict[str, object],
    message: str,
) -> None:
    content = "Valid knowledge content."
    values: dict[str, object] = {
        "ordinal": 0,
        "content": content,
        "content_hash": sha256(content.encode("utf-8")).hexdigest(),
        "token_count": 4,
        "search_text": content,
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        ChunkDraft(**values)
