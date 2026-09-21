import argparse
import asyncio
from uuid import UUID

from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.knowledge import SqlAlchemyKnowledgeRepository
from nxtrep_backend.services.knowledge_document_publication import (
    KnowledgeDocumentPublicationService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish a reviewed knowledge document.",
    )
    parser.add_argument(
        "--document-id",
        type=UUID,
        required=True,
    )
    return parser


async def run_publication(document_id: UUID) -> None:
    async with SessionFactory() as session:
        try:
            result = await KnowledgeDocumentPublicationService(
                repository=SqlAlchemyKnowledgeRepository(session)
            ).publish(document_id)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    document = result.document
    published_at = (
        document.published_at.isoformat() if document.published_at is not None else "none"
    )
    print(
        f"status={result.status} "
        f"document_id={document.id} "
        f"review_status={document.review_status} "
        f"published_at={published_at}"
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        asyncio.run(run_publication(args.document_id))
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(status=1, message=f"Error: {exc}\n")


if __name__ == "__main__":
    main()
