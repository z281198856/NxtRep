from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from nxtrep_backend.agents.nutrition_vision import (
    GlmFoodImageRecognizer,
    GlmFoodNutritionFallbackEstimator,
)
from nxtrep_backend.repositories.nutrition import (
    SqlAlchemyNutritionRepository,
)
from nxtrep_backend.schemas.media import ImagePurpose
from nxtrep_backend.schemas.nutrition import (
    FoodCatalogMatchResult,
    FoodImageCandidate,
    FoodNutritionDraftItem,
    FoodNutritionFallbackEstimate,
    FoodResponse,
    NutritionDraftCalculation,
    NutritionEstimateRange,
    NutritionImageAnalysisResult,
    NutritionImageDraftResponse,
    NutritionImageEstimateRequest,
    NutritionTotals,
)
from nxtrep_backend.services.agent_media import (
    AgentImageAssetResolver,
    ResolvedAgentImage,
)


class FoodCatalogMatcher:
    def __init__(
        self,
        repository: SqlAlchemyNutritionRepository,
    ) -> None:
        self._repository = repository

    async def match(
        self,
        *,
        user_id: UUID,
        foods: Sequence[FoodImageCandidate],
    ) -> list[FoodCatalogMatchResult]:
        results: list[FoodCatalogMatchResult] = []

        for detected in foods:
            keyword = detected.name.strip()

            rows, _ = await self._repository.search_foods(
                user_id,
                keyword,
                None,
                None,
                1,
                5,
            )

            exact_rows = [
                row for row in rows if row[0].name.strip().casefold() == keyword.casefold()
            ]

            if not exact_rows:
                exact_rows = await self._repository.find_foods_by_exact_alias(
                    user_id=user_id,
                    alias=keyword,
                )

            if len(exact_rows) == 1:
                result = FoodCatalogMatchResult(
                    detected=detected,
                    status="matched",
                    selected=self._to_response(*exact_rows[0]),
                )
            elif exact_rows or rows:
                result = FoodCatalogMatchResult(
                    detected=detected,
                    status="needs_confirmation",
                    alternatives=[
                        self._to_response(food, version) for food, version in (exact_rows or rows)
                    ],
                )
            else:
                result = FoodCatalogMatchResult(
                    detected=detected,
                    status="not_found",
                )

            results.append(result)

        return results

    @staticmethod
    def _to_response(food, version) -> FoodResponse:
        return FoodResponse(
            id=food.id,
            food_version_id=version.id,
            name=food.name,
            brand=food.brand,
            state=food.state,
            basis_amount_g=version.basis_amount_g,
            kcal=version.kcal,
            protein_g=version.protein_g,
            carbs_g=version.carbs_g,
            fat_g=version.fat_g,
            source=version.source,
            confidence=version.confidence,
        )


class NutritionDraftCalculator:
    _NUTRIENTS = (
        "kcal",
        "protein_g",
        "carbs_g",
        "fat_g",
    )

    def calculate(
        self,
        matches: Sequence[FoodCatalogMatchResult],
        fallback_estimates: Sequence[FoodNutritionFallbackEstimate] = (),
    ) -> NutritionDraftCalculation:
        items: list[FoodNutritionDraftItem] = []
        fallback_by_name = {
            estimate.food_name.strip().casefold(): estimate for estimate in fallback_estimates
        }

        if len(fallback_by_name) != len(fallback_estimates):
            raise ValueError("Fallback food names must be unique")

        totals = {
            bound: {nutrient: Decimal("0") for nutrient in self._NUTRIENTS}
            for bound in (
                "minimum",
                "estimated",
                "maximum",
            )
        }

        for match in matches:
            if match.status == "not_found":
                fallback = fallback_by_name.pop(
                    match.detected.name.strip().casefold(),
                    None,
                )

                if fallback is not None:
                    nutrition = self._calculate_fallback_range(
                        match.detected,
                        fallback,
                    )
                    items.append(
                        FoodNutritionDraftItem(
                            match=match,
                            nutrition=nutrition,
                            source=fallback.source,
                            confidence=fallback.confidence,
                            requires_confirmation=(fallback.requires_confirmation),
                            assumptions=fallback.assumptions,
                            follow_up_questions=(fallback.follow_up_questions),
                        )
                    )
                    self._add_to_totals(totals, nutrition)
                    continue

            if match.status != "matched" or match.selected is None:
                items.append(
                    FoodNutritionDraftItem(
                        match=match,
                        nutrition=None,
                        requires_confirmation=True,
                    )
                )
                continue

            nutrition = self._calculate_range(match)

            items.append(
                FoodNutritionDraftItem(
                    match=match,
                    nutrition=nutrition,
                    source=match.selected.source,
                    confidence=match.selected.confidence,
                )
            )
            self._add_to_totals(totals, nutrition)

        if fallback_by_name:
            raise ValueError("Fallback results contain foods not requested by matches")

        total_range = NutritionEstimateRange(
            minimum=NutritionTotals(**totals["minimum"]),
            estimated=NutritionTotals(**totals["estimated"]),
            maximum=NutritionTotals(**totals["maximum"]),
        )

        is_complete = bool(matches) and all(item.nutrition is not None for item in items)
        requires_confirmation = any(item.requires_confirmation for item in items)

        return NutritionDraftCalculation(
            items=items,
            totals=total_range,
            is_complete=is_complete,
            requires_confirmation=requires_confirmation,
        )

    def _add_to_totals(
        self,
        totals: dict[str, dict[str, Decimal]],
        nutrition: NutritionEstimateRange,
    ) -> None:
        for bound in totals:
            bound_totals = getattr(nutrition, bound)

            for nutrient in self._NUTRIENTS:
                totals[bound][nutrient] += getattr(
                    bound_totals,
                    nutrient,
                )

    def _calculate_range(
        self,
        match: FoodCatalogMatchResult,
    ) -> NutritionEstimateRange:
        food = match.selected
        detected = match.detected

        if food is None:
            raise ValueError("Matched food requires selected catalog food")

        return NutritionEstimateRange(
            minimum=self._calculate_amount(
                food,
                detected.amount_min_g,
            ),
            estimated=self._calculate_amount(
                food,
                detected.estimated_amount_g,
            ),
            maximum=self._calculate_amount(
                food,
                detected.amount_max_g,
            ),
        )

    @staticmethod
    def _calculate_amount(
        food: FoodResponse,
        amount_g: Decimal,
    ) -> NutritionTotals:
        ratio = amount_g / food.basis_amount_g

        return NutritionTotals(
            kcal=food.kcal * ratio,
            protein_g=food.protein_g * ratio,
            carbs_g=food.carbs_g * ratio,
            fat_g=food.fat_g * ratio,
        )

    def _calculate_fallback_range(
        self,
        detected: FoodImageCandidate,
        fallback: FoodNutritionFallbackEstimate,
    ) -> NutritionEstimateRange:
        per_100g = fallback.nutrition_per_100g

        return NutritionEstimateRange(
            minimum=self._scale_totals(
                per_100g.minimum,
                detected.amount_min_g / fallback.basis_amount_g,
            ),
            estimated=self._scale_totals(
                per_100g.estimated,
                detected.estimated_amount_g / fallback.basis_amount_g,
            ),
            maximum=self._scale_totals(
                per_100g.maximum,
                detected.amount_max_g / fallback.basis_amount_g,
            ),
        )

    @staticmethod
    def _scale_totals(
        nutrition: NutritionTotals,
        ratio: Decimal,
    ) -> NutritionTotals:
        return NutritionTotals(
            kcal=nutrition.kcal * ratio,
            protein_g=nutrition.protein_g * ratio,
            carbs_g=nutrition.carbs_g * ratio,
            fat_g=nutrition.fat_g * ratio,
        )


class NutritionImagePurposeError(RuntimeError):
    pass


class NutritionImageAnalysisService:
    def __init__(
        self,
        *,
        recognizer: GlmFoodImageRecognizer,
        fallback_estimator: GlmFoodNutritionFallbackEstimator,
        matcher: FoodCatalogMatcher,
        calculator: NutritionDraftCalculator,
    ) -> None:
        self._recognizer = recognizer
        self._fallback_estimator = fallback_estimator
        self._matcher = matcher
        self._calculator = calculator

    async def analyze(
        self,
        *,
        user_id: UUID,
        images: Sequence[ResolvedAgentImage],
        notes: str | None,
    ) -> NutritionImageAnalysisResult:
        if not images:
            raise ValueError("At least one resolved nutrition image is required")

        allowed_purposes = {
            ImagePurpose.NUTRITION_ENTRY,
            ImagePurpose.CHAT_ATTACHMENT,
        }

        if any(image.purpose not in allowed_purposes for image in images):
            raise NutritionImagePurposeError("Images must be nutrition entries or chat attachments")

        recognition = await self._recognizer.recognize(
            images=images,
            notes=notes,
        )

        matches = await self._matcher.match(
            user_id=user_id,
            foods=recognition.foods,
        )

        unmatched_foods = [match.detected for match in matches if match.status == "not_found"]

        fallback_estimates: Sequence[FoodNutritionFallbackEstimate] = ()

        if unmatched_foods:
            fallback = await self._fallback_estimator.estimate(
                images=images,
                foods=unmatched_foods,
                notes=notes,
            )
            fallback_estimates = fallback.estimates

        calculation = self._calculator.calculate(
            matches,
            fallback_estimates,
        )

        return NutritionImageAnalysisResult(
            recognition=recognition,
            calculation=calculation,
        )


class NutritionImageDraftEstimator:
    def __init__(
        self,
        *,
        resolver: AgentImageAssetResolver,
        analysis_service: NutritionImageAnalysisService,
    ) -> None:
        self._resolver = resolver
        self._analysis_service = analysis_service

    async def estimate(
        self,
        *,
        user_id: UUID,
        body: NutritionImageEstimateRequest,
    ) -> NutritionImageDraftResponse:
        images = await self._resolver.resolve(
            user_id=user_id,
            asset_ids=[body.image_asset_id],
        )

        if len(images) != 1 or images[0].purpose != ImagePurpose.NUTRITION_ENTRY:
            raise NutritionImagePurposeError("Image purpose must be nutrition_entry")

        analysis = await self._analysis_service.analyze(
            user_id=user_id,
            images=images,
            notes=body.notes,
        )

        return NutritionImageDraftResponse(
            **body.model_dump(),
            recognition=analysis.recognition,
            calculation=analysis.calculation,
        )
