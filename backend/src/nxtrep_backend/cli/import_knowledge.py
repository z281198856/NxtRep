import argparse
import asyncio
from pathlib import Path
from uuid import UUID

from nxtrep_backend.core.config import get_settings
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.knowledge.schemas import KnowledgeLoadRequest, KnowledgeTopic
from nxtrep_backend.services.knowledge_ingestion import (
    build_knowledge_document_preparer,
    build_knowledge_ingestion_service,
)

KNOWLEDGE_TOPICS: tuple[KnowledgeTopic, ...] = (
    "exercise",
    "training",
    "nutrition",
    "product_help",
    "safety",
)
KNOWLEDGE_CONTENT_TYPES = (
    "application/pdf",
    "text/html",
    "application/xhtml+xml",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare or import a reviewed PDF/HTML into NxtRep knowledge.",
    )
    parser.add_argument("--source-id", type=UUID)
    parser.add_argument(
        "--file",
        "--path",
        dest="path",
        type=Path,
        required=True,
    )
    parser.add_argument("--source-key", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument(
        "--topic",
        choices=KNOWLEDGE_TOPICS,
        required=True,
    )
    parser.add_argument("--locale", default="zh-CN")
    parser.add_argument(
        "--content-type",
        choices=KNOWLEDGE_CONTENT_TYPES,
        required=True,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Prepare and report chunks without calling GLM or the database.",
    )
    return parser


async def run_import(
    *,
    source_id: UUID | None,
    path: Path,
    source_key: str,
    title: str,
    topic: KnowledgeTopic,
    locale: str,
    content_type: str,
    dry_run: bool,
) -> None:
    request = KnowledgeLoadRequest(
        path=path,
        source_key=source_key,
        title=title,
        topic=topic,
        locale=locale,
        content_type=content_type,
    )

    if dry_run:
        prepared = build_knowledge_document_preparer().prepare(request)
        print(
            "status=prepared "
            f"blocks={len(prepared.document.blocks)} "
            f"chunks={len(prepared.chunks)} "
            f"tokens={sum(chunk.token_count for chunk in prepared.chunks)} "
            f"content_hash={prepared.content_hash} "
            "dry_run=true"
        )
        return

    if source_id is None:
        raise ValueError("source_id is required unless dry_run is enabled")

    async with SessionFactory() as session:
        try:
            service = build_knowledge_ingestion_service(
                session=session,
                settings=get_settings(),
            )
            result = await service.ingest(
                source_id=source_id,
                request=request,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    print(
        f"status={result.status} "
        f"source_id={result.source_id} "
        f"document_id={result.document_id} "
        f"source_version={result.source_version} "
        f"chunks_created={result.created_chunks} "
        f"embeddings_created={result.created_embeddings} "
        "dry_run=false"
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.dry_run and args.source_id is None:
        parser.error("--source-id is required unless --dry-run is used")

    try:
        asyncio.run(
            run_import(
                source_id=args.source_id,
                path=args.path,
                source_key=args.source_key,
                title=args.title,
                topic=args.topic,
                locale=args.locale,
                content_type=args.content_type,
                dry_run=args.dry_run,
            )
        )
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(status=1, message=f"Error: {exc}\n")


if __name__ == "__main__":
    main()
