from pypdf import PdfReader
from pypdf.errors import PdfReadError

from nxtrep_backend.knowledge.loaders.base import (
    KnowledgeDocumentLoadError,
)
from nxtrep_backend.knowledge.schemas import (
    KnowledgeLoadRequest,
    ParsedBlock,
    ParsedDocument,
)


class PdfDocumentLoader:
    """使用pypdf逐页读取带文本层的PDF文件。"""

    @property
    def supported_content_types(self) -> frozenset[str]:
        return frozenset({"application/pdf"})

    def load(
        self,
        request: KnowledgeLoadRequest,
    ) -> ParsedDocument:
        self._validate_request(request)

        try:
            reader = PdfReader(str(request.path))

            if reader.is_encrypted and reader.decrypt("") == 0:
                raise KnowledgeDocumentLoadError(f"PDF requires a password: {request.path.name}")

            blocks = self._extract_blocks(reader)
        except (OSError, PdfReadError) as exc:
            raise KnowledgeDocumentLoadError(f"Unable to read PDF: {request.path.name}") from exc

        if not blocks:
            raise KnowledgeDocumentLoadError(
                f"PDF contains no extractable text: {request.path.name}"
            )

        return ParsedDocument(
            source_key=request.source_key,
            title=request.title,
            topic=request.topic,
            locale=request.locale,
            blocks=blocks,
            metadata={
                "loader": "pypdf",
                "file_name": request.path.name,
                "page_count": len(reader.pages),
            },
        )

    def _validate_request(
        self,
        request: KnowledgeLoadRequest,
    ) -> None:
        if request.content_type not in self.supported_content_types:
            raise KnowledgeDocumentLoadError(
                f"Unsupported PDF content type: {request.content_type}"
            )

        if request.path.suffix.casefold() != ".pdf":
            raise KnowledgeDocumentLoadError(f"Expected a PDF file: {request.path.name}")

        if not request.path.is_file():
            raise KnowledgeDocumentLoadError(f"PDF file does not exist: {request.path}")

    @staticmethod
    def _extract_blocks(
        reader: PdfReader,
    ) -> tuple[ParsedBlock, ...]:
        blocks: list[ParsedBlock] = []

        for page_number, page in enumerate(
            reader.pages,
            start=1,
        ):
            text = page.extract_text() or ""
            text = text.strip()

            if not text:
                continue

            blocks.append(
                ParsedBlock(
                    text=text,
                    kind="paragraph",
                    page_number=page_number,
                    metadata={
                        "source_format": "pdf",
                    },
                )
            )

        return tuple(blocks)
