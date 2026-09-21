import argparse
import asyncio
from uuid import UUID

from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.knowledge import SqlAlchemyKnowledgeRepository
from nxtrep_backend.services.knowledge_document_review import (
    KnowledgeDocumentReviewService,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mark a draft knowledge document as reviewed.",
    )
    parser.add_argument(
        "--document-id",
        type=UUID,
        required=True,
    )
    return parser


async def run_review(document_id: UUID) -> None:
    async with SessionFactory() as session:
        try:
            result = await KnowledgeDocumentReviewService(
                repository=SqlAlchemyKnowledgeRepository(session)
            ).review(document_id)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    document = result.document
    print(
        f"status={result.status} document_id={document.id} review_status={document.review_status}"
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        asyncio.run(run_review(args.document_id))
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(status=1, message=f"Error: {exc}\n")


if __name__ == "__main__":
    main()
