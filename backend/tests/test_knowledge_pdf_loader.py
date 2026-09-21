from pathlib import Path

import pytest
from pypdf.errors import PdfReadError

import nxtrep_backend.knowledge.loaders.pdf as pdf_loader_module
from nxtrep_backend.knowledge.loaders.base import KnowledgeDocumentLoadError
from nxtrep_backend.knowledge.loaders.pdf import PdfDocumentLoader
from nxtrep_backend.knowledge.schemas import KnowledgeLoadRequest


class FakePage:
    def __init__(self, text: str | None) -> None:
        self.text = text

    def extract_text(self) -> str | None:
        return self.text


class FakePdfReader:
    def __init__(
        self,
        pages: list[FakePage],
        *,
        encrypted: bool = False,
        decrypt_result: int = 1,
    ) -> None:
        self.pages = pages
        self.is_encrypted = encrypted
        self.decrypt_result = decrypt_result

    def decrypt(self, password: str) -> int:
        assert password == ""
        return self.decrypt_result


def make_request(path: Path, **overrides: object) -> KnowledgeLoadRequest:
    values: dict[str, object] = {
        "path": path,
        "source_key": "who-guidelines",
        "title": "WHO Guidelines",
        "topic": "training",
        "locale": "en",
        "content_type": "application/pdf",
    }
    values.update(overrides)
    return KnowledgeLoadRequest(**values)


def test_pdf_loader_preserves_page_numbers_and_skips_blank_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "guideline.pdf"
    pdf_path.write_bytes(b"test placeholder")
    reader = FakePdfReader(
        [
            FakePage("  First page content.  "),
            FakePage(None),
            FakePage("Third page content."),
        ]
    )
    monkeypatch.setattr(pdf_loader_module, "PdfReader", lambda _: reader)

    document = PdfDocumentLoader().load(make_request(pdf_path))

    assert [block.text for block in document.blocks] == [
        "First page content.",
        "Third page content.",
    ]
    assert [block.page_number for block in document.blocks] == [1, 3]
    assert document.metadata == {
        "loader": "pypdf",
        "file_name": "guideline.pdf",
        "page_count": 3,
    }


def test_pdf_loader_exposes_supported_content_type() -> None:
    assert PdfDocumentLoader().supported_content_types == frozenset(
        {"application/pdf"}
    )


@pytest.mark.parametrize(
    ("path_name", "content_type", "message"),
    [
        ("guideline.pdf", "text/html", "Unsupported PDF content type"),
        ("guideline.txt", "application/pdf", "Expected a PDF file"),
    ],
)
def test_pdf_loader_rejects_wrong_request_type(
    tmp_path: Path,
    path_name: str,
    content_type: str,
    message: str,
) -> None:
    path = tmp_path / path_name
    path.write_bytes(b"test placeholder")

    with pytest.raises(KnowledgeDocumentLoadError, match=message):
        PdfDocumentLoader().load(
            make_request(path, content_type=content_type)
        )


def test_pdf_loader_rejects_missing_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.pdf"

    with pytest.raises(KnowledgeDocumentLoadError, match="does not exist"):
        PdfDocumentLoader().load(make_request(missing_path))


def test_pdf_loader_rejects_password_protected_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "protected.pdf"
    pdf_path.write_bytes(b"test placeholder")
    reader = FakePdfReader(
        [FakePage("Protected content")],
        encrypted=True,
        decrypt_result=0,
    )
    monkeypatch.setattr(pdf_loader_module, "PdfReader", lambda _: reader)

    with pytest.raises(KnowledgeDocumentLoadError, match="requires a password"):
        PdfDocumentLoader().load(make_request(pdf_path))


def test_pdf_loader_rejects_pdf_without_extractable_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "scanned.pdf"
    pdf_path.write_bytes(b"test placeholder")
    reader = FakePdfReader([FakePage(None), FakePage("   ")])
    monkeypatch.setattr(pdf_loader_module, "PdfReader", lambda _: reader)

    with pytest.raises(KnowledgeDocumentLoadError, match="no extractable text"):
        PdfDocumentLoader().load(make_request(pdf_path))


def test_pdf_loader_wraps_invalid_pdf_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "broken.pdf"
    pdf_path.write_bytes(b"not a pdf")

    def raise_pdf_error(_: str) -> None:
        raise PdfReadError("broken xref")

    monkeypatch.setattr(pdf_loader_module, "PdfReader", raise_pdf_error)

    with pytest.raises(KnowledgeDocumentLoadError, match="Unable to read PDF"):
        PdfDocumentLoader().load(make_request(pdf_path))
