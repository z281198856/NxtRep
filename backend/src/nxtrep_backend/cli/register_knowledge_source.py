import argparse
import asyncio

from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.knowledge.schemas import KnowledgeTopic
from nxtrep_backend.repositories.knowledge import SqlAlchemyKnowledgeRepository
from nxtrep_backend.services.knowledge_source import (
    KnowledgeSourceService,
    KnowledgeSourceType,
)

SOURCE_TYPES = ("manual", "file", "url")
KNOWLEDGE_TOPICS = (
    "exercise",
    "training",
    "nutrition",
    "product_help",
    "safety",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Register an inactive knowledge source before importing it.",
    )
    parser.add_argument("--source-key", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument(
        "--source-type",
        choices=SOURCE_TYPES,
        required=True,
    )
    parser.add_argument("--source-uri")
    parser.add_argument("--publisher")
    parser.add_argument("--license-name")
    parser.add_argument(
        "--topic",
        choices=KNOWLEDGE_TOPICS,
        required=True,
    )
    parser.add_argument("--locale", default="zh-CN")
    return parser


async def run_registration(
    *,
    source_key: str,
    title: str,
    source_type: KnowledgeSourceType,
    source_uri: str | None,
    publisher: str | None,
    license_name: str | None,
    topic: KnowledgeTopic,
    locale: str,
) -> None:
    async with SessionFactory() as session:
        try:
            result = await KnowledgeSourceService(
                repository=SqlAlchemyKnowledgeRepository(session)
            ).register(
                source_key=source_key,
                title=title,
                source_type=source_type,
                source_uri=source_uri,
                publisher=publisher,
                license_name=license_name,
                topic=topic,
                locale=locale,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    source = result.source
    print(
        f"status={result.status} "
        f"source_id={source.id} "
        f"source_key={source.source_key} "
        f"ingest_status={source.ingest_status} "
        f"active={str(source.is_active).lower()}"
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        asyncio.run(
            run_registration(
                source_key=args.source_key,
                title=args.title,
                source_type=args.source_type,
                source_uri=args.source_uri,
                publisher=args.publisher,
                license_name=args.license_name,
                topic=args.topic,
                locale=args.locale,
            )
        )
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(status=1, message=f"Error: {exc}\n")


if __name__ == "__main__":
    main()
