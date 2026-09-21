from pathlib import Path

import pytest

from nxtrep_backend.knowledge.loaders.base import KnowledgeDocumentLoadError
from nxtrep_backend.knowledge.loaders.html import HtmlDocumentLoader
from nxtrep_backend.knowledge.schemas import KnowledgeLoadRequest


def make_request(path: Path, **overrides: object) -> KnowledgeLoadRequest:
    values: dict[str, object] = {
        "path": path,
        "source_key": "national-fitness-guide",
        "title": "National Fitness Guide",
        "topic": "training",
        "locale": "en",
        "content_type": "text/html",
    }
    values.update(overrides)
    return KnowledgeLoadRequest(**values)


def test_html_loader_extracts_structure_and_removes_noise(tmp_path: Path) -> None:
    html_path = tmp_path / "guide.html"
    html_path.write_text(
        """
        <html>
          <head>
            <style>.hidden { display: none; }</style>
            <script>window.noise = true;</script>
          </head>
          <body>
            <header><p>Header noise</p></header>
            <article>
              <h1>Training recommendations</h1>
              <h2>Adults</h2>
              <p>Move regularly throughout the week.</p>
              <ul>
                <li><p>Include strength training.</p></li>
              </ul>
              <table>
                <tr><th>Activity</th><th>Frequency</th></tr>
                <tr><td>Strength</td><td>Twice weekly</td></tr>
              </table>
            </article>
            <footer><p>Footer noise</p></footer>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    document = HtmlDocumentLoader().load(make_request(html_path))

    assert [block.kind for block in document.blocks] == [
        "heading",
        "heading",
        "paragraph",
        "list",
        "table",
    ]
    assert [block.text for block in document.blocks] == [
        "Training recommendations",
        "Adults",
        "Move regularly throughout the week.",
        "Include strength training.",
        "Activity Frequency Strength Twice weekly",
    ]
    assert document.blocks[2].section_path == (
        "Training recommendations",
        "Adults",
    )
    assert document.blocks[3].text == "Include strength training."
    assert document.metadata["loader"] == "beautifulsoup4"


def test_html_loader_uses_main_before_body(tmp_path: Path) -> None:
    html_path = tmp_path / "main.html"
    html_path.write_text(
        """
        <html><body>
          <aside><p>Related article noise</p></aside>
          <main><h1>Main title</h1><p>Main content</p></main>
        </body></html>
        """,
        encoding="utf-8",
    )

    document = HtmlDocumentLoader().load(make_request(html_path))

    assert [block.text for block in document.blocks] == [
        "Main title",
        "Main content",
    ]


def test_html_loader_preserves_article_wrapped_in_form(tmp_path: Path) -> None:
    html_path = tmp_path / "server-form.html"
    html_path.write_text(
        """
        <html><body>
          <form method="post">
            <header><p>Header noise</p></header>
            <main><article>
              <aside><p>Newsletter noise</p></aside>
              <h1>Fact sheet</h1>
              <p>Reviewed content.</p>
            </article></main>
            <footer><p>Footer noise</p></footer>
          </form>
        </body></html>
        """,
        encoding="utf-8",
    )

    document = HtmlDocumentLoader().load(make_request(html_path))

    assert [block.text for block in document.blocks] == [
        "Fact sheet",
        "Reviewed content.",
    ]


def test_html_loader_uses_known_article_container_before_body(
    tmp_path: Path,
) -> None:
    html_path = tmp_path / "government-guide.html"
    html_path.write_text(
        """
        <html><body>
          <ul><li>Home navigation</li><li>Services</li></ul>
          <div class="content" id="zoom">
            <p>Authoritative article content.</p>
          </div>
        </body></html>
        """,
        encoding="utf-8",
    )

    document = HtmlDocumentLoader().load(make_request(html_path))

    assert [block.text for block in document.blocks] == ["Authoritative article content."]


def test_html_loader_exposes_supported_content_types() -> None:
    assert HtmlDocumentLoader().supported_content_types == frozenset(
        {"text/html", "application/xhtml+xml"}
    )


@pytest.mark.parametrize(
    ("path_name", "content_type", "message"),
    [
        ("guide.html", "application/pdf", "Unsupported HTML content type"),
        ("guide.txt", "text/html", "Expected an HTML file"),
    ],
)
def test_html_loader_rejects_wrong_request_type(
    tmp_path: Path,
    path_name: str,
    content_type: str,
    message: str,
) -> None:
    path = tmp_path / path_name
    path.write_text("<p>Content</p>", encoding="utf-8")

    with pytest.raises(KnowledgeDocumentLoadError, match=message):
        HtmlDocumentLoader().load(make_request(path, content_type=content_type))


def test_html_loader_rejects_missing_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.html"

    with pytest.raises(KnowledgeDocumentLoadError, match="does not exist"):
        HtmlDocumentLoader().load(make_request(missing_path))


def test_html_loader_rejects_page_without_content(tmp_path: Path) -> None:
    html_path = tmp_path / "empty.html"
    html_path.write_text(
        "<html><body><script>only noise</script></body></html>",
        encoding="utf-8",
    )

    with pytest.raises(KnowledgeDocumentLoadError, match="no extractable text"):
        HtmlDocumentLoader().load(make_request(html_path))
