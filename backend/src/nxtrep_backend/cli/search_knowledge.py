import argparse
import asyncio
import json
import sys
from collections.abc import Sequence

from nxtrep_backend.core.config import get_settings
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.knowledge.schemas import (
    KnowledgeRetrievalRequest,
    KnowledgeTopic,
)
from nxtrep_backend.services.knowledge_retrieval import (
    build_knowledge_retrieval_service,
)

KNOWLEDGE_TOPICS = (
    "exercise",
    "training",
    "nutrition",
    "product_help",
    "safety",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search published NxtRep knowledge.",
    )
    parser.add_argument("--query", required=True)
    parser.add_argument(
        "--topic",
        choices=KNOWLEDGE_TOPICS,
        required=True,
    )
    parser.add_argument("--locale", default="zh-CN")
    parser.add_argument(
        "--candidate-k",
        type=int,
        default=20,
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--source-key",
        action="append",
        dest="source_keys",
        default=[],
    )
    return parser


async def run_search(
    *,
    query: str,
    topic: KnowledgeTopic,
    locale: str,
    candidate_k: int,
    top_k: int,
    source_keys: Sequence[str],
) -> None:
    request = KnowledgeRetrievalRequest(
        query=query,
        topic=topic,
        locale=locale,
        candidate_k=candidate_k,
        top_k=top_k,
        source_keys=tuple(source_keys),
    )
    settings = get_settings()

    async with SessionFactory() as session:
        service = build_knowledge_retrieval_service(
            session=session,
            settings=settings,
        )
        hits = await service.retrieve(request)

    payload = {
        "query": request.query,
        "count": len(hits),
        "hits": [
            {
                "chunk_id": str(hit.chunk_id),
                "content": hit.content,
                "score": hit.score,
                "match_type": hit.match_type,
                "source_key": hit.source_key,
                "source_title": hit.source_title,
                "source_uri": hit.source_uri,
                "source_version": hit.source_version,
                "section_path": hit.section_path,
                "page_numbers": list(hit.page_numbers),
            }
            for hit in hits
        ],
    }

    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args()

    try:
        asyncio.run(
            run_search(
                query=args.query,
                topic=args.topic,
                locale=args.locale,
                candidate_k=args.candidate_k,
                top_k=args.top_k,
                source_keys=args.source_keys,
            )
        )
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(status=1, message=f"Error: {exc}\n")


if __name__ == "__main__":
    main()
