import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.db.models import Food, FoodAlias, FoodVersion


class FoodCatalogImportRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=24)
    name: str = Field(min_length=1, max_length=160)
    brand: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=40)
    state: str | None = Field(default=None, max_length=30)
    basis_amount_g: Decimal = Field(gt=0)
    kcal: Decimal = Field(ge=0)
    protein_g: Decimal = Field(ge=0)
    carbs_g: Decimal = Field(ge=0)
    fat_g: Decimal = Field(ge=0)
    confidence: str = Field(default="high", min_length=1, max_length=20)
    aliases: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if any(len(item) > 160 for item in normalized):
            raise ValueError("food alias must not exceed 160 characters")
        return list(dict.fromkeys(normalized))


@dataclass(frozen=True, slots=True)
class FoodCatalogImportResult:
    created_foods: int = 0
    created_versions: int = 0
    unchanged_foods: int = 0
    created_aliases: int = 0


def load_food_catalog_csv(path: Path) -> list[FoodCatalogImportRow]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        rows = []
        for line_number, raw in enumerate(csv.DictReader(source), start=2):
            try:
                rows.append(
                    FoodCatalogImportRow.model_validate(
                        {
                            **raw,
                            "aliases": (raw.get("aliases") or "").split("|"),
                        }
                    )
                )
            except Exception as exc:
                raise ValueError(f"Invalid food catalog row {line_number}: {exc}") from exc
    if not rows:
        raise ValueError("Food catalog CSV contains no data rows")
    external_ids = [item.external_id for item in rows]
    if len(external_ids) != len(set(external_ids)):
        raise ValueError("Food catalog external_id values must be unique")
    return rows


class FoodCatalogImporter:
    """Import attributed nutrition facts into the versioned relational catalog."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def import_rows(
        self,
        *,
        source: str,
        rows: list[FoodCatalogImportRow],
    ) -> FoodCatalogImportResult:
        normalized_source = source.strip().lower()
        if not normalized_source or len(normalized_source) > 14:
            raise ValueError("source must contain 1 to 14 characters")
        created_foods = 0
        created_versions = 0
        unchanged_foods = 0
        created_aliases = 0
        for row in rows:
            source_key = f"catalog:{normalized_source}:{row.external_id}"
            if len(source_key) > 40:
                raise ValueError(
                    "source and external_id exceed the 40-character catalog source limit"
                )
            record = (
                await self._session.execute(
                    select(Food, FoodVersion)
                    .join(FoodVersion, FoodVersion.food_id == Food.id)
                    .where(FoodVersion.source == source_key)
                    .order_by(FoodVersion.version.desc())
                    .limit(1)
                )
            ).first()
            if record is None:
                food = Food(
                    name=row.name.strip(),
                    brand=self._optional(row.brand),
                    region=self._optional(row.region),
                    state=self._optional(row.state),
                )
                self._session.add(food)
                await self._session.flush()
                version = self._version(food, row, source_key, version=1)
                self._session.add(version)
                created_foods += 1
                created_versions += 1
            else:
                food, current = record
                food.name = row.name.strip()
                food.brand = self._optional(row.brand)
                food.region = self._optional(row.region)
                food.state = self._optional(row.state)
                if self._nutrition_changed(current, row):
                    self._session.add(
                        self._version(food, row, source_key, version=current.version + 1)
                    )
                    created_versions += 1
                else:
                    unchanged_foods += 1
            for alias in row.aliases:
                exists = await self._session.scalar(
                    select(FoodAlias.id).where(
                        FoodAlias.food_id == food.id,
                        func.lower(FoodAlias.alias) == alias.casefold(),
                    )
                )
                if exists is None:
                    self._session.add(FoodAlias(food_id=food.id, alias=alias))
                    created_aliases += 1
        await self._session.flush()
        return FoodCatalogImportResult(
            created_foods=created_foods,
            created_versions=created_versions,
            unchanged_foods=unchanged_foods,
            created_aliases=created_aliases,
        )

    @staticmethod
    def _optional(value: str | None) -> str | None:
        normalized = value.strip() if value else ""
        return normalized or None

    @staticmethod
    def _version(
        food: Food,
        row: FoodCatalogImportRow,
        source: str,
        *,
        version: int,
    ) -> FoodVersion:
        return FoodVersion(
            food_id=food.id,
            version=version,
            basis_amount_g=row.basis_amount_g,
            kcal=row.kcal,
            protein_g=row.protein_g,
            carbs_g=row.carbs_g,
            fat_g=row.fat_g,
            source=source,
            confidence=row.confidence,
        )

    @staticmethod
    def _nutrition_changed(current: FoodVersion, row: FoodCatalogImportRow) -> bool:
        return any(
            getattr(current, field) != getattr(row, field)
            for field in (
                "basis_amount_g",
                "kcal",
                "protein_g",
                "carbs_g",
                "fat_g",
                "confidence",
            )
        )
