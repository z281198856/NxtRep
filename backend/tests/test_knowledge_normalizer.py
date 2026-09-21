from pathlib import Path

import pytest

from nxtrep_backend.knowledge.loaders.html import HtmlDocumentLoader
from nxtrep_backend.knowledge.normalizer import (
    KnowledgeNormalizationError,
    KnowledgeTextNormalizer,
)
from nxtrep_backend.knowledge.schemas import (
    KnowledgeLoadRequest,
    ParsedBlock,
    ParsedDocument,
)


def make_document(*blocks: ParsedBlock) -> ParsedDocument:
    return ParsedDocument(
        source_key="test-source",
        title="Test source",
        topic="training",
        locale="en",
        blocks=blocks,
    )


def test_normalizer_removes_pdf_page_marker_and_joins_cjk_lines() -> None:
    document = make_document(
        ParsedBlock(
            text="—6—\n低血糖生成指数的\n水果和蔬菜；",
            page_number=6,
            metadata={"source_format": "pdf"},
        )
    )

    normalized = KnowledgeTextNormalizer().normalize(document)

    assert len(normalized.blocks) == 1
    assert normalized.blocks[0].text == "低血糖生成指数的水果和蔬菜；"
    assert normalized.blocks[0].page_number == 6


def test_normalizer_joins_english_lines_and_repairs_split_hyphen() -> None:
    document = make_document(
        ParsedBlock(
            text=(
                "Adults should undertake regular\n"
                "physical activity at moderate\n"
                "-intensity throughout the week."
            ),
            page_number=10,
            metadata={"source_format": "pdf"},
        )
    )

    normalized = KnowledgeTextNormalizer().normalize(document)

    assert normalized.blocks[0].text == (
        "Adults should undertake regular physical activity at "
        "moderate-intensity throughout the week."
    )


def test_html_loader_and_normalizer_preserve_breaks_and_build_sections(
    tmp_path: Path,
) -> None:
    html_path = tmp_path / "guide.html"
    html_path.write_text(
        """
        <html><body><div id="zoom">
          <p><strong>一、背景<br></strong>
          进入21世纪以来，居民身体活动方式发生改变。<br>
          （一）安全原则<br>
          运动应当循序渐进。</p>
        </div></body></html>
        """,
        encoding="utf-8",
    )
    loaded = HtmlDocumentLoader().load(
        KnowledgeLoadRequest(
            path=html_path,
            source_key="national-fitness-guide",
            title="全民健身指南",
            topic="training",
            locale="zh-CN",
            content_type="text/html",
        )
    )

    normalized = KnowledgeTextNormalizer().normalize(loaded)

    assert [block.text for block in normalized.blocks] == [
        "一、背景",
        "进入21世纪以来，居民身体活动方式发生改变。",
        "（一）安全原则",
        "运动应当循序渐进。",
    ]
    assert [block.kind for block in normalized.blocks] == [
        "heading",
        "paragraph",
        "heading",
        "paragraph",
    ]
    assert normalized.blocks[1].section_path == ("一、背景",)
    assert normalized.blocks[3].section_path == (
        "一、背景",
        "（一）安全原则",
    )
    assert normalized.metadata["normalization_version"] == "v1"


def test_normalizer_removes_unicode_spacing_and_consecutive_duplicates() -> None:
    document = make_document(
        ParsedBlock(
            text="\ufeffStrength\u00a0training\u200b guidance",
            page_number=3,
        ),
        ParsedBlock(
            text="Strength training guidance",
            page_number=3,
        ),
    )

    normalized = KnowledgeTextNormalizer().normalize(document)

    assert [block.text for block in normalized.blocks] == ["Strength training guidance"]


def test_normalizer_preserves_semantic_html_heading_level() -> None:
    document = make_document(
        ParsedBlock(
            text="Training",
            kind="heading",
            section_path=("Training",),
            metadata={"source_format": "html", "source_tag": "h1"},
        ),
        ParsedBlock(
            text="Adults",
            kind="heading",
            section_path=("Training", "Adults"),
            metadata={"source_format": "html", "source_tag": "h2"},
        ),
        ParsedBlock(
            text="Move regularly.",
            section_path=("Training", "Adults"),
            metadata={"source_format": "html", "source_tag": "p"},
        ),
    )

    normalized = KnowledgeTextNormalizer().normalize(document)

    assert normalized.blocks[-1].section_path == ("Training", "Adults")


def test_normalizer_rejects_document_without_usable_content() -> None:
    document = make_document(
        ParsedBlock(
            text="—12—",
            page_number=12,
            metadata={"source_format": "pdf"},
        )
    )

    with pytest.raises(KnowledgeNormalizationError, match="no usable content"):
        KnowledgeTextNormalizer().normalize(document)
