from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from nxtrep_backend.api.deps import CurrentUser, DbSession
from nxtrep_backend.api.errors import ApiError
from nxtrep_backend.api.idempotency import (
    IdempotencyKey,
    begin_idempotent,
    complete_idempotent,
    replay_response,
)
from nxtrep_backend.api.routes.training import _confirmation_response
from nxtrep_backend.repositories.confirmation import SqlAlchemyConfirmationRepository
from nxtrep_backend.repositories.nutrition import SqlAlchemyNutritionRepository
from nxtrep_backend.schemas.confirmation import ConfirmationSubmitResponse
from nxtrep_backend.schemas.nutrition import (
    DailyNutritionSummaryResponse,
    ExpectedVersionRequest,
    FoodCreateRequest,
    FoodResponse,
    FoodSearchResponse,
    NutritionEntryCreateRequest,
    NutritionEntryResponse,
    NutritionEntryUpdateRequest,
    NutritionTargetDraftRequest,
    NutritionTargetDraftResponse,
    NutritionTotals,
)
from nxtrep_backend.services.nutrition import (
    NutritionConflictError,
    NutritionNotFoundError,
    NutritionService,
)

foods_router = APIRouter()
nutrition_router = APIRouter()
EntryDate = Annotated[date, Query(alias="date")]


def _service(session: DbSession) -> NutritionService:
    return NutritionService(
        SqlAlchemyNutritionRepository(session), SqlAlchemyConfirmationRepository(session)
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


@foods_router.get("/search", response_model=FoodSearchResponse)
async def search_foods(
    user: CurrentUser,
    session: DbSession,
    keyword: str = Query(min_length=1, max_length=160),
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


@nutrition_router.get("/daily-summary", response_model=DailyNutritionSummaryResponse)
async def get_daily_summary(
    date_value: EntryDate, user: CurrentUser, session: DbSession
) -> DailyNutritionSummaryResponse:
    return DailyNutritionSummaryResponse.model_validate(
        await _service(session).daily_summary(user.id, date_value)
    )


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
