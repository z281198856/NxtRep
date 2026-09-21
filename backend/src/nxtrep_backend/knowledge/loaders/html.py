from bs4 import BeautifulSoup, Tag

from nxtrep_backend.knowledge.loaders.base import (
    KnowledgeDocumentLoadError,
)
from nxtrep_backend.knowledge.schemas import (
    KnowledgeLoadRequest,
    ParsedBlock,
    ParsedDocument,
)

_HTML_LINE_BREAK_MARKER = "\ue000"


class HtmlDocumentLoader:
    """从HTML网页快照中提取标题、段落、列表和表格。"""

    @property
    def supported_content_types(self) -> frozenset[str]:
        return frozenset(
            {
                "text/html",
                "application/xhtml+xml",
            }
        )

    def load(
        self,
        request: KnowledgeLoadRequest,
    ) -> ParsedDocument:
        self._validate_request(request)

        try:
            raw_html = request.path.read_bytes()
        except OSError as exc:
            raise KnowledgeDocumentLoadError(f"Unable to read HTML: {request.path.name}") from exc

        soup = BeautifulSoup(raw_html, "html.parser")
        self._remove_noise(soup)

        root = self._find_content_root(soup)
        blocks = self._extract_blocks(root)

        if not blocks:
            raise KnowledgeDocumentLoadError(
                f"HTML contains no extractable text: {request.path.name}"
            )

        return ParsedDocument(
            source_key=request.source_key,
            title=request.title,
            topic=request.topic,
            locale=request.locale,
            blocks=blocks,
            metadata={
                "loader": "beautifulsoup4",
                "file_name": request.path.name,
                "original_encoding": soup.original_encoding,
            },
        )

    def _validate_request(
        self,
        request: KnowledgeLoadRequest,
    ) -> None:
        if request.content_type not in self.supported_content_types:
            raise KnowledgeDocumentLoadError(
                f"Unsupported HTML content type: {request.content_type}"
            )

        if request.path.suffix.casefold() not in {".html", ".htm"}:
            raise KnowledgeDocumentLoadError(f"Expected an HTML file: {request.path.name}")

        if not request.path.is_file():
            raise KnowledgeDocumentLoadError(f"HTML file does not exist: {request.path}")

    @staticmethod
    def _remove_noise(
        soup: BeautifulSoup,
    ) -> None:
        noise_tags = (
            "script",
            "style",
            "noscript",
            "svg",
            "nav",
            "header",
            "footer",
            "aside",
        )

        for element in soup.find_all(noise_tags):
            element.decompose()

        # Some public-sector sites wrap the entire document in a server-side
        # form. Removing the form would also remove the article inside it, so
        # retain its children while discarding only the wrapper.
        for element in soup.find_all("form"):
            element.unwrap()

    @staticmethod
    def _find_content_root(
        soup: BeautifulSoup,
    ) -> Tag | BeautifulSoup:
        content_selectors = (
            "article",
            "main",
            '[role="main"]',
            "#zoom",
            ".TRS_Editor",
            ".article-content",
        )

        for selector in content_selectors:
            root = soup.select_one(selector)
            if isinstance(root, Tag):
                return root

        if isinstance(soup.body, Tag):
            return soup.body

        return soup

    @staticmethod
    def _extract_blocks(
        root: Tag | BeautifulSoup,
    ) -> tuple[ParsedBlock, ...]:
        blocks: list[ParsedBlock] = []
        heading_path: list[str] = []

        elements = root.find_all(
            [
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
                "p",
                "li",
                "table",
            ]
        )

        for element in elements:
            if element.name in {"p", "li", "table"}:
                nested_parent = element.find_parent(["p", "li", "table"])
                if nested_parent is not None:
                    continue

            for line_break in element.find_all("br"):
                line_break.replace_with(_HTML_LINE_BREAK_MARKER)

            text = element.get_text(" ", strip=True)
            text = text.replace(
                _HTML_LINE_BREAK_MARKER,
                "\n",
            )

            if not text:
                continue

            if element.name.startswith("h"):
                level = int(element.name[1])
                heading_path = heading_path[: level - 1]
                heading_path.append(text)
                kind = "heading"
            elif element.name == "li":
                kind = "list"
            elif element.name == "table":
                kind = "table"
            else:
                kind = "paragraph"

            blocks.append(
                ParsedBlock(
                    text=text,
                    kind=kind,
                    section_path=tuple(heading_path),
                    metadata={
                        "source_format": "html",
                        "source_tag": element.name,
                    },
                )
            )

        return tuple(blocks)
