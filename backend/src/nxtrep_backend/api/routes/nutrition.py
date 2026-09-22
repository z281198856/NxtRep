from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from nxtrep_backend.agents.nutrition_vision import (
    FoodImageRecognitionError,
    FoodNutritionFallbackError,
    GlmFoodImageRecognizer,
    GlmFoodNutritionFallbackEstimator,
)
from nxtrep_backend.api.deps import CurrentUser, DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.api.idempotency import (
    IdempotencyKey,
    begin_idempotent,
    complete_idempotent,
    replay_response,
)
from nxtrep_backend.api.routes.training import _confirmation_response
from nxtrep_backend.core.config import (
    StorageConfigurationError,
    get_settings,
)
from nxtrep_backend.providers.models import (
    ModelConfigurationError,
    build_vision_model,
)
from nxtrep_backend.providers.storage import (
    StorageProviderError,
    build_image_storage_provider,
)
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.media import (
    SqlAlchemyImageAssetRepository,
)
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.schemas.confirmation import ConfirmationSubmitResponse
from nxtrep_backend.schemas.nutrition import (
    DailyNutritionSummaryResponse,
    DynamicNutritionTargetDraftRequest,
    ExpectedVersionRequest,
    FlexibleMealCreateRequest,
    FlexibleMealResponse,
    FlexibleMealUpdateRequest,
    FoodCreateRequest,
    FoodResponse,
    FoodSearchResponse,
    FoodUpdateRequest,
    FrequentFoodResponse,
    NutritionAdviceRequest,
    NutritionAdviceResponse,
    NutritionEntryCreateRequest,
    NutritionEntryDeleteRequest,
    NutritionEntryDraftResponse,
    NutritionEntryDraftUpdateRequest,
    NutritionEntryResponse,
    NutritionEntryUpdateRequest,
    NutritionImageDraftResponse,
    NutritionImageEstimateRequest,
    NutritionTargetDraftRequest,
    NutritionTargetDraftResponse,
    NutritionTargetVersionResponse,
    NutritionTextDraftRequest,
    NutritionTotals,
    RecipeCreateRequest,
    RecipeResponse,
    RecipeUpdateRequest,
    WeeklyNutritionSummaryResponse,
)
from nxtrep_backend.services.agent_media import (
    AgentImageAssetNotFoundError,
    AgentImageAssetNotReadyError,
    AgentImageAssetResolver,
)
from nxtrep_backend.services.nutrition import (
    NutritionConflictError,
    NutritionNotFoundError,
    NutritionService,
)
from nxtrep_backend.services.nutrition_image import (
    FoodCatalogMatcher,
    NutritionDraftCalculator,
    NutritionImageAnalysisService,
    NutritionImageDraftEstimator,
    NutritionImagePurposeError,
)

foods_router = APIRouter()
nutrition_router = APIRouter()
recipes_router = APIRouter()
EntryDate = Annotated[date, Query(alias="date")]


def _service(session: DbSession) -> NutritionService:
    return NutritionService(
        SqlAlchemyNutritionRepository(session), SqlAlchemyConfirmationRepository(session)
    )


def _build_nutrition_image_estimator(
    session: AsyncSession,
) -> NutritionImageDraftEstimator:
    settings = get_settings()

    storage = build_image_storage_provider(settings)

    resolver = AgentImageAssetResolver(
        SqlAlchemyImageAssetRepository(session),
        storage,
    )

    vision_model = build_vision_model(settings)

    recognizer = GlmFoodImageRecognizer(vision_model)
    fallback_estimator = GlmFoodNutritionFallbackEstimator(vision_model)

    matcher = FoodCatalogMatcher(SqlAlchemyNutritionRepository(session))
    calculator = NutritionDraftCalculator()

    analysis_service = NutritionImageAnalysisService(
        recognizer=recognizer,
        fallback_estimator=fallback_estimator,
        matcher=matcher,
        calculator=calculator,
    )

    return NutritionImageDraftEstimator(
        resolver=resolver,
        analysis_service=analysis_service,
    )


def _raise_nutrition_error(exc: RuntimeError) -> None:
    if isinstance(exc, NutritionNotFoundError):
        raise ApiError(status_code=404, code="NUTRITION_NOT_FOUND", message=str(exc)) from exc
    if isinstance(exc, NutritionConflictError):
        raise ApiError(
            status_code=409,
            code="NUTRITION_VERSION_CONFLICT",
            message=str(exc),
            details={"current_version": exc.current_version},
        ) from exc
    raise exc


def _food_response(food, version) -> FoodResponse:
    return FoodResponse(
        id=food.id,
        food_version_id=version.id,
        name=food.name,
        brand=food.brand,
        barcode=food.barcode,
        state=food.state,
        basis_amount_g=version.basis_amount_g,
        kcal=version.kcal,
        protein_g=version.protein_g,
        carbs_g=version.carbs_g,
        fat_g=version.fat_g,
        source=version.source,
        confidence=version.confidence,
    )


def _entry_response(item) -> NutritionEntryResponse:
    return NutritionEntryResponse(
        id=item.id,
        meal_type=item.meal_type,
        eaten_at=item.eaten_at,
        items=item.items,
        totals=NutritionTotals.model_validate(item.totals),
        is_flexible_meal=item.is_flexible_meal,
        notes=item.notes,
        version=item.version,
    )


def _entry_draft_response(item) -> NutritionEntryDraftResponse:
    return NutritionEntryDraftResponse.model_validate(item, from_attributes=True)


def _recipe_response(item) -> RecipeResponse:
    return RecipeResponse.model_validate(item, from_attributes=True)


@foods_router.get("/search", response_model=FoodSearchResponse)
async def search_foods(
    user: CurrentUser,
    session: DbSession,
    keyword: str = Query(default="", max_length=160),
    region: str | None = None,
    state: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> FoodSearchResponse:
    rows, total = await SqlAlchemyNutritionRepository(session).search_foods(
        user.id, keyword.strip(), region, state, page, page_size
    )
    return FoodSearchResponse(
        list=[_food_response(food, version) for food, version in rows],
        total=total,
        page=page,
        page_size=page_size,
        has_more=page * page_size < total,
    )


@foods_router.post("", response_model=FoodResponse, status_code=201)
async def create_food(
    body: FoodCreateRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> FoodResponse:
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, "POST /foods", body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, FoodResponse, 201):
        return replayed
    food, version = await _service(session).create_food(user.id, body)
    response = _food_response(food, version)
    await complete_idempotent(idem, decision, response, 201)
    return response


@foods_router.get("/frequent", response_model=list[FrequentFoodResponse])
async def list_frequent_foods(
    user: CurrentUser,
    session: DbSession,
    limit: int = Query(default=10, ge=1, le=50),
) -> list[FrequentFoodResponse]:
    rows = await SqlAlchemyNutritionRepository(session).list_frequent_foods(
        user.id,
        limit=limit,
    )
    return [
        FrequentFoodResponse(**_food_response(food, version).model_dump(), use_count=count)
        for food, version, count in rows
    ]


@foods_router.get("/barcodes/{code}", response_model=FoodResponse)
async def get_food_by_barcode(
    code: str,
    user: CurrentUser,
    session: DbSession,
) -> FoodResponse:
    found = await SqlAlchemyNutritionRepository(session).get_food_by_barcode(user.id, code.strip())
    if found is None:
        raise ApiError(
            status_code=404,
            code="FOOD_BARCODE_NOT_FOUND",
            message="Food barcode not found",
        )
    return _food_response(*found)


@foods_router.get("/{food_id}", response_model=FoodResponse)
async def get_food(
    food_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> FoodResponse:
    try:
        food, version = await _service(session).get_food(user.id, food_id)
    except RuntimeError as exc:
        _raise_nutrition_error(exc)
    return _food_response(food, version)


@foods_router.patch("/{food_id}", response_model=FoodResponse)
async def update_food(
    food_id: UUID,
    body: FoodUpdateRequest,
    user: CurrentUser,
    session: DbSession,
) -> FoodResponse:
    try:
        food, version = await _service(session).update_food(user.id, food_id, body)
    except RuntimeError as exc:
        _raise_nutrition_error(exc)
    return _food_response(food, version)


@foods_router.delete("/{food_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_food(
    food_id: UUID,
    expected_version: int,
    user: CurrentUser,
    session: DbSession,
) -> Response:
    try:
        await _service(session).delete_food(user.id, food_id, expected_version)
    except RuntimeError as exc:
        _raise_nutrition_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@nutrition_router.post("/entries", response_model=NutritionEntryResponse, status_code=201)
async def create_nutrition_entry(
    body: NutritionEntryCreateRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> NutritionEntryResponse:
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, "POST /nutrition/entries", body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, NutritionEntryResponse, 201):
        return replayed
    try:
        response = _entry_response(await _service(session).create_entry(user.id, body))
    except RuntimeError as exc:
        _raise_nutrition_error(exc)
    await complete_idempotent(idem, decision, response, 201)
    return response


@nutrition_router.get("/entries", response_model=list[NutritionEntryResponse])
async def list_nutrition_entries(
    date_value: EntryDate,
    user: CurrentUser,
    session: DbSession,
    meal_type: str | None = None,
) -> list[NutritionEntryResponse]:
    items = await SqlAlchemyNutritionRepository(session).list_entries(
        user.id, date_value, meal_type
    )
    return [_entry_response(item) for item in items]


@nutrition_router.get("/entries/{entry_id}", response_model=NutritionEntryResponse)
async def get_nutrition_entry(
    entry_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> NutritionEntryResponse:
    item = await SqlAlchemyNutritionRepository(session).get_entry(user.id, entry_id)
    if item is None:
        raise ApiError(status_code=404, code="NUTRITION_NOT_FOUND", message="Entry not found")
    return _entry_response(item)


@nutrition_router.patch("/entries/{entry_id}", response_model=NutritionEntryResponse)
async def update_nutrition_entry(
    entry_id: UUID,
    body: NutritionEntryUpdateRequest,
    user: CurrentUser,
    session: DbSession,
) -> NutritionEntryResponse:
    try:
        return _entry_response(await _service(session).update_entry(user.id, entry_id, body))
    except RuntimeError as exc:
        _raise_nutrition_error(exc)


@nutrition_router.delete(
    "/entries/{entry_id}",
    response_model=ConfirmationSubmitResponse,
)
async def delete_nutrition_entry(
    entry_id: UUID,
    body: NutritionEntryDeleteRequest,
    user: CurrentUser,
    session: DbSession,
) -> ConfirmationSubmitResponse:
    try:
        return _confirmation_response(
            await _service(session).create_entry_delete_confirmation(user.id, entry_id, body)
        )
    except RuntimeError as exc:
        _raise_nutrition_error(exc)


@nutrition_router.get("/daily-summary", response_model=DailyNutritionSummaryResponse)
async def get_daily_summary(
    date_value: EntryDate, user: CurrentUser, session: DbSession
) -> DailyNutritionSummaryResponse:
    return DailyNutritionSummaryResponse.model_validate(
        await _service(session).daily_summary(user.id, date_value)
    )


@nutrition_router.get("/weekly-summary", response_model=WeeklyNutritionSummaryResponse)
async def get_weekly_summary(
    start_date: date,
    user: CurrentUser,
    session: DbSession,
) -> WeeklyNutritionSummaryResponse:
    return WeeklyNutritionSummaryResponse.model_validate(
        await _service(session).weekly_summary(user.id, start_date)
    )


@nutrition_router.post("/advice", response_model=NutritionAdviceResponse)
async def get_nutrition_advice(
    body: NutritionAdviceRequest,
    user: CurrentUser,
    session: DbSession,
) -> NutritionAdviceResponse:
    return NutritionAdviceResponse.model_validate(
        await _service(session).nutrition_advice(user.id, body.food_name, body.on_date)
    )


@nutrition_router.get("/targets", response_model=list[NutritionTargetVersionResponse])
async def list_nutrition_targets(
    user: CurrentUser,
    session: DbSession,
) -> list[NutritionTargetVersionResponse]:
    items = await SqlAlchemyNutritionRepository(session).list_target_versions(user.id)
    return [
        NutritionTargetVersionResponse.model_validate(item, from_attributes=True) for item in items
    ]


@nutrition_router.get("/flexible-meals", response_model=list[FlexibleMealResponse])
async def list_flexible_meals(
    user: CurrentUser,
    session: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[FlexibleMealResponse]:
    if start_date and end_date and start_date > end_date:
        raise ApiError(
            status_code=422,
            code="INVALID_DATE_RANGE",
            message="start_date must not exceed end_date",
        )
    items = await SqlAlchemyNutritionRepository(session).list_flexible_meals(
        user.id, start_date, end_date
    )
    return [FlexibleMealResponse.model_validate(item, from_attributes=True) for item in items]


@nutrition_router.post(
    "/flexible-meals",
    response_model=FlexibleMealResponse,
    status_code=201,
)
async def create_flexible_meal(
    body: FlexibleMealCreateRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> FlexibleMealResponse:
    idem, decision = await begin_idempotent(
        session,
        user.id,
        idempotency_key,
        "POST /nutrition/flexible-meals",
        body.model_dump(mode="json"),
    )
    if replayed := replay_response(decision, FlexibleMealResponse, 201):
        return replayed
    try:
        response = FlexibleMealResponse.model_validate(
            await _service(session).create_flexible_meal(user.id, body),
            from_attributes=True,
        )
    except RuntimeError as exc:
        _raise_nutrition_error(exc)
    await complete_idempotent(idem, decision, response, 201)
    return response


@nutrition_router.patch(
    "/flexible-meals/{item_id}",
    response_model=FlexibleMealResponse,
)
async def update_flexible_meal(
    item_id: UUID,
    body: FlexibleMealUpdateRequest,
    user: CurrentUser,
    session: DbSession,
) -> FlexibleMealResponse:
    try:
        return FlexibleMealResponse.model_validate(
            await _service(session).update_flexible_meal(user.id, item_id, body),
            from_attributes=True,
        )
    except RuntimeError as exc:
        _raise_nutrition_error(exc)


@nutrition_router.post(
    "/target-drafts", response_model=NutritionTargetDraftResponse, status_code=201
)
async def create_nutrition_target_draft(
    body: NutritionTargetDraftRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> NutritionTargetDraftResponse:
    idem, decision = await begin_idempotent(
        session,
        user.id,
        idempotency_key,
        "POST /nutrition/target-drafts",
        body.model_dump(mode="json"),
    )
    if replayed := replay_response(decision, NutritionTargetDraftResponse, 201):
        return replayed
    item = await _service(session).create_target_draft(user.id, body)
    response = NutritionTargetDraftResponse(
        id=item.id,
        status=item.status,
        version=item.version,
        **body.model_dump(),
    )
    await complete_idempotent(idem, decision, response, 201)
    return response


@nutrition_router.post(
    "/dynamic-target-drafts",
    response_model=NutritionTargetDraftResponse,
    status_code=201,
)
async def create_dynamic_nutrition_target_draft(
    body: DynamicNutritionTargetDraftRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> NutritionTargetDraftResponse:
    idem, decision = await begin_idempotent(
        session,
        user.id,
        idempotency_key,
        "POST /nutrition/dynamic-target-drafts",
        body.model_dump(mode="json"),
    )
    if replayed := replay_response(decision, NutritionTargetDraftResponse, 201):
        return replayed
    try:
        item = await _service(session).create_dynamic_target_draft(user.id, body)
    except RuntimeError as exc:
        _raise_nutrition_error(exc)
    response = NutritionTargetDraftResponse.model_validate(item, from_attributes=True)
    await complete_idempotent(idem, decision, response, 201)
    return response


@nutrition_router.post(
    "/target-drafts/{target_id}/submit", response_model=ConfirmationSubmitResponse
)
async def submit_nutrition_target_draft(
    target_id: UUID,
    body: ExpectedVersionRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> ConfirmationSubmitResponse:
    operation = f"POST /nutrition/target-drafts/{target_id}/submit"
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, operation, body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, ConfirmationSubmitResponse, 200):
        return replayed
    try:
        response = _confirmation_response(
            await _service(session).submit_target(user.id, target_id, body.expected_version)
        )
    except RuntimeError as exc:
        _raise_nutrition_error(exc)
    await complete_idempotent(idem, decision, response, 200)
    return response


@recipes_router.get("", response_model=list[RecipeResponse])
async def list_recipes(
    user: CurrentUser,
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[RecipeResponse]:
    items, _ = await SqlAlchemyNutritionRepository(session).list_recipes(user.id, page, page_size)
    return [_recipe_response(item) for item in items]


@recipes_router.post("", response_model=RecipeResponse, status_code=201)
async def create_recipe(
    body: RecipeCreateRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> RecipeResponse:
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, "POST /recipes", body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, RecipeResponse, 201):
        return replayed
    try:
        response = _recipe_response(await _service(session).create_recipe(user.id, body))
    except RuntimeError as exc:
        _raise_nutrition_error(exc)
    await complete_idempotent(idem, decision, response, 201)
    return response


@recipes_router.get("/{recipe_id}", response_model=RecipeResponse)
async def get_recipe(recipe_id: UUID, user: CurrentUser, session: DbSession) -> RecipeResponse:
    item = await SqlAlchemyNutritionRepository(session).get_recipe(user.id, recipe_id)
    if item is None:
        raise ApiError(status_code=404, code="RECIPE_NOT_FOUND", message="Recipe not found")
    return _recipe_response(item)


@recipes_router.patch("/{recipe_id}", response_model=RecipeResponse)
async def update_recipe(
    recipe_id: UUID,
    body: RecipeUpdateRequest,
    user: CurrentUser,
    session: DbSession,
) -> RecipeResponse:
    try:
        return _recipe_response(await _service(session).update_recipe(user.id, recipe_id, body))
    except RuntimeError as exc:
        _raise_nutrition_error(exc)


@recipes_router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipe(
    recipe_id: UUID,
    expected_version: int,
    user: CurrentUser,
    session: DbSession,
) -> Response:
    try:
        await _service(session).delete_recipe(user.id, recipe_id, expected_version)
    except RuntimeError as exc:
        _raise_nutrition_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@nutrition_router.post(
    "/entry-drafts:parse-text",
    response_model=NutritionEntryDraftResponse,
    status_code=201,
)
async def parse_nutrition_text_draft(
    body: NutritionTextDraftRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> NutritionEntryDraftResponse:
    idem, decision = await begin_idempotent(
        session,
        user.id,
        idempotency_key,
        "POST /nutrition/entry-drafts:parse-text",
        body.model_dump(mode="json"),
    )
    if replayed := replay_response(decision, NutritionEntryDraftResponse, 201):
        return replayed
    response = _entry_draft_response(await _service(session).parse_text_draft(user.id, body))
    await complete_idempotent(idem, decision, response, 201)
    return response


@nutrition_router.get("/entry-drafts/{draft_id}", response_model=NutritionEntryDraftResponse)
async def get_nutrition_entry_draft(
    draft_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> NutritionEntryDraftResponse:
    item = await SqlAlchemyNutritionRepository(session).get_entry_draft(user.id, draft_id)
    if item is None:
        raise ApiError(
            status_code=404,
            code="NUTRITION_NOT_FOUND",
            message="Nutrition entry draft not found",
        )
    return _entry_draft_response(item)


@nutrition_router.patch("/entry-drafts/{draft_id}", response_model=NutritionEntryDraftResponse)
async def update_nutrition_entry_draft(
    draft_id: UUID,
    body: NutritionEntryDraftUpdateRequest,
    user: CurrentUser,
    session: DbSession,
) -> NutritionEntryDraftResponse:
    try:
        return _entry_draft_response(
            await _service(session).update_entry_draft(user.id, draft_id, body)
        )
    except RuntimeError as exc:
        _raise_nutrition_error(exc)


@nutrition_router.post(
    "/entry-drafts/{draft_id}/submit",
    response_model=ConfirmationSubmitResponse,
)
async def submit_nutrition_entry_draft(
    draft_id: UUID,
    body: ExpectedVersionRequest,
    idempotency_key: IdempotencyKey,
    user: CurrentUser,
    session: DbSession,
) -> ConfirmationSubmitResponse:
    operation = f"POST /nutrition/entry-drafts/{draft_id}/submit"
    idem, decision = await begin_idempotent(
        session, user.id, idempotency_key, operation, body.model_dump(mode="json")
    )
    if replayed := replay_response(decision, ConfirmationSubmitResponse, 200):
        return replayed
    try:
        response = _confirmation_response(
            await _service(session).submit_entry_draft(user.id, draft_id, body.expected_version)
        )
    except RuntimeError as exc:
        _raise_nutrition_error(exc)
    await complete_idempotent(idem, decision, response, 200)
    return response


@nutrition_router.post(
    "/entry-drafts:estimate-image",
    response_model=NutritionImageDraftResponse,
)
async def estimate_nutrition_image_draft(
    body: NutritionImageEstimateRequest,
    user: CurrentUser,
    session: DbSession,
) -> NutritionImageDraftResponse:
    try:
        estimator = _build_nutrition_image_estimator(session)

        return await estimator.estimate(
            user_id=user.id,
            body=body,
        )
    except AgentImageAssetNotFoundError as exc:
        raise ApiError(
            status_code=404,
            code="IMAGE_ASSET_NOT_FOUND",
            message="Image asset not found",
        ) from exc
    except AgentImageAssetNotReadyError as exc:
        raise ApiError(
            status_code=409,
            code="IMAGE_ASSET_NOT_READY",
            message="Image asset is not ready",
        ) from exc
    except NutritionImagePurposeError as exc:
        raise ApiError(
            status_code=422,
            code="NUTRITION_IMAGE_PURPOSE_INVALID",
            message="Image purpose must be nutrition_entry",
        ) from exc
    except StorageProviderError as exc:
        raise ApiError(
            status_code=503,
            code="IMAGE_STORAGE_UNAVAILABLE",
            message="Image storage is temporarily unavailable",
        ) from exc
    except (
        FoodImageRecognitionError,
        FoodNutritionFallbackError,
    ) as exc:
        raise ApiError(
            status_code=502,
            code="VISION_MODEL_INVALID_RESPONSE",
            message="Vision model returned an invalid response",
        ) from exc
    except (
        ModelConfigurationError,
        StorageConfigurationError,
    ) as exc:
        raise ApiError(
            status_code=503,
            code="NUTRITION_IMAGE_NOT_CONFIGURED",
            message=str(exc),
        ) from exc
