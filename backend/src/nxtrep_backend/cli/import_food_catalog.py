import argparse
import asyncio
from pathlib import Path

from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.services.food_catalog_import import (
    FoodCatalogImporter,
    load_food_catalog_csv,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a reviewed CSV into the versioned NxtRep food catalog.",
    )
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument(
        "--source",
        required=True,
        help="Short source key, for example usda or china_cdc.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


async def run_import(*, path: Path, source: str, dry_run: bool) -> None:
    rows = load_food_catalog_csv(path)
    async with SessionFactory() as session:
        try:
            result = await FoodCatalogImporter(session).import_rows(
                source=source,
                rows=rows,
            )
            if dry_run:
                await session.rollback()
            else:
                await session.commit()
        except Exception:
            await session.rollback()
            raise
    print(
        f"foods_created={result.created_foods} "
        f"versions_created={result.created_versions} "
        f"foods_unchanged={result.unchanged_foods} "
        f"aliases_created={result.created_aliases} "
        f"dry_run={str(dry_run).lower()}"
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        asyncio.run(
            run_import(
                path=args.file,
                source=args.source,
                dry_run=args.dry_run,
            )
        )
    except (OSError, ValueError) as exc:
        parser.exit(status=1, message=f"Error: {exc}\n")


if __name__ == "__main__":
    main()
