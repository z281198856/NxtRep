import os
from pathlib import Path
from uuid import uuid4

import pytest

from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.services.food_catalog_import import (
    FoodCatalogImporter,
    FoodCatalogImportRow,
    load_food_catalog_csv,
)


def test_load_food_catalog_csv_parses_aliases_and_nutrients(tmp_path: Path) -> None:
    source = tmp_path / "foods.csv"
    source.write_text(
        "external_id,name,brand,region,state,basis_amount_g,kcal,protein_g,"
        "carbs_g,fat_g,confidence,aliases\n"
        "123,熟燕麦,,CN,cooked,100,68,2.4,12,1.4,high,燕麦|燕麦粥\n",
        encoding="utf-8",
    )

    rows = load_food_catalog_csv(source)

    assert len(rows) == 1
    assert rows[0].external_id == "123"
    assert rows[0].aliases == ["燕麦", "燕麦粥"]
    assert str(rows[0].kcal) == "68"


def test_load_food_catalog_csv_rejects_duplicate_external_ids(tmp_path: Path) -> None:
    source = tmp_path / "foods.csv"
    header = (
        "external_id,name,brand,region,state,basis_amount_g,kcal,protein_g,"
        "carbs_g,fat_g,confidence,aliases\n"
    )
    row = "123,食物,,CN,cooked,100,10,1,1,1,high,别名\n"
    source.write_text(header + row + row, encoding="utf-8")

    with pytest.raises(ValueError, match="external_id"):
        load_food_catalog_csv(source)


@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="Set RUN_DATABASE_TESTS=1 to run PostgreSQL integration tests",
)
@pytest.mark.asyncio
async def test_importer_versions_food_and_alias_is_searchable() -> None:
    async with SessionFactory() as session:
        transaction = await session.begin()
        try:
            result = await FoodCatalogImporter(session).import_rows(
                source="test",
                rows=[
                    FoodCatalogImportRow(
                        external_id=uuid4().hex[:12],
                        name="测试熟燕麦",
                        region="CN",
                        state="cooked",
                        basis_amount_g="100",
                        kcal="68",
                        protein_g="2.4",
                        carbs_g="12",
                        fat_g="1.4",
                        aliases=["测试燕麦粥"],
                    )
                ],
            )
            matches = await SqlAlchemyNutritionRepository(
                session
            ).find_foods_by_exact_alias(
                user_id=uuid4(),
                alias="测试燕麦粥",
            )

            assert result.created_foods == 1
            assert result.created_versions == 1
            assert result.created_aliases == 1
            assert len(matches) == 1
            assert matches[0][0].name == "测试熟燕麦"
        finally:
            await transaction.rollback()
