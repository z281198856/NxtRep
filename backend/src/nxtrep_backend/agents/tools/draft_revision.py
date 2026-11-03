"""Patch existing pending business drafts using their original schemas and services."""

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from langchain.tools import tool
from pydantic import Field, ValidationError

from nxtrep_backend.agents.tools.common import confirmation_payload, json_safe
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.schemas.body import BodyMeasurementCreateRequest
from nxtrep_backend.schemas.nutrition import (
    CustomFoodDraftRequest,
    CustomFoodPatchRequest,
    NutritionTargetDraftRequest,
)
from nxtrep_backend.schemas.profile import ProfileUpdateRequest
from nxtrep_backend.schemas.training import PlanDraftCreateRequest
from nxtrep_backend.schemas.water import WaterEntryCreateRequest
from nxtrep_backend.services.confirmation import (
    DatabaseConfirmationConflictError,
    DatabaseConfirmationService,
)
from nxtrep_backend.services.nutrition import NutritionConflictError, NutritionNotFoundError
from nxtrep_backend.services.profile import ProfileNotFoundError, ProfileVersionConflictError
from nxtrep_backend.services.training import (
    TrainingConflictError,
    TrainingNotFoundError,
    draft_payload,
)

REVISION_OPERATIONS = {
    "profile_update_draft": {"profile_update"},
    "food_catalog_draft": {"food_create", "food_update"},
    "body_measurement_draft": {"body_measurement_create"},
    "water_record_draft": {"water_entry_create"},
    "nutrition_target_draft": {"nutrition_target_activate"},
    "training_plan_draft": {"training_plan_activate"},
}


async def pending_revision_preflight(tool_name, context, scope):
    operations = {
        "propose_profile_update": {"profile_update"},
        "propose_custom_food": {"food_create"},
        "propose_custom_food_update": {"food_update"},
        "propose_body_measurement": {"body_measurement_create"},
        "propose_water_entry": {"water_entry_create"},
        "propose_nutrition_target": {"nutrition_target_activate"},
        "propose_training_plan": {"training_plan_activate"},
    }.get(tool_name)
    if not operations or not context or not scope.get("confirmation_id"):
        return None
    service = context.confirmation_service
    if not isinstance(service, DatabaseConfirmationService):
        return None
    old = await service.get(
        user_id=context.user_id, confirmation_id=UUID(str(scope["confirmation_id"]))
    )
    if old.status == "pending" and old.operation_type in operations:
        return {
            "status": "needs_review",
            "error_code": "DRAFT_REVISION_REQUIRED",
            "required_tool": "propose_pending_draft_revision",
            "message": "当前正在修订已有待确认草稿，请先读取该草稿并提交局部修订，"
            "不能另建独立草稿。",
        }
    return None


def _patch(model, original, changes, *, reserved=()):
    if not changes or set(changes) - (set(model.model_fields) - set(reserved)):
        raise ValueError("请只提供本次要修改的业务字段，不能更换记录ID、版本或操作类型。")
    return model.model_validate({**deepcopy(original), **changes})


def _food_changes(original, changes):
    # Changing reference grams retains per-gram values unless nutrients were
    # explicitly corrected in the same request, matching the existing food service.
    if "basis_amount_g" not in changes:
        return changes
    validated = _patch(
        CustomFoodPatchRequest,
        {
            key: value
            for key, value in original.items()
            if key in CustomFoodPatchRequest.model_fields
        },
        changes,
    )
    if validated.basis_amount_g is None:
        raise ValueError("食品基准克数必须大于0，不能清空。")
    ratio = validated.basis_amount_g / Decimal(str(original["basis_amount_g"]))
    result = dict(changes)
    for key in ("kcal", "protein_g", "carbs_g", "fat_g"):
        if key not in changes:
            result[key] = (Decimal(str(original[key])) * ratio).quantize(
                Decimal("0.01") if key == "kcal" else Decimal("0.001")
            )
    return result


async def _propose(context, old, changes):
    user_id, after = context.user_id, old.after
    extra = {}
    if old.operation_type == "profile_update":
        body = _patch(
            ProfileUpdateRequest,
            {**after["changes"], "expected_version": after["expected_version"]},
            changes,
            reserved={"expected_version"},
        )
        card = await context.profile_service.propose_update(user_id, body)
    elif old.operation_type == "body_measurement_create":
        body = _patch(BodyMeasurementCreateRequest, after["measurement"], changes)
        card = await context.body_service.propose_measurement(user_id=user_id, body=body)
    elif old.operation_type == "water_entry_create":
        body = _patch(WaterEntryCreateRequest, after["water"], changes)
        if context.water_service is None:
            raise ValueError("饮水记录暂时不可用。")
        card = await context.water_service.propose_entry(user_id, body)
    elif old.operation_type == "food_create":
        body = _patch(CustomFoodDraftRequest, after["food"], _food_changes(after["food"], changes))
        card = await context.nutrition_service.propose_custom_food(user_id=user_id, body=body)
        extra["draft"] = card.after["food"]
    elif old.operation_type == "food_update":
        # Preserve the *pending* food, not the older saved food it was based on.
        original = {
            key: value
            for key, value in after["food"].items()
            if key in CustomFoodPatchRequest.model_fields
        }
        body = _patch(CustomFoodPatchRequest, original, _food_changes(original, changes))
        card = await context.nutrition_service.propose_custom_food_change(
            user_id=user_id,
            food_id=UUID(after["food_id"]),
            expected_version=after["expected_version"],
            patch=body,
        )
        extra["draft"] = card.after["food"]
    elif old.operation_type == "nutrition_target_activate":
        service = context.nutrition_service
        draft = await service.repository.get_target_draft(
            user_id, UUID(after["target_id"]), lock=True
        )
        if draft is None or draft.version != after["draft_version"] or draft.status != "submitted":
            raise ValueError("原营养目标草稿已变化，请重新读取。")
        body = _patch(
            NutritionTargetDraftRequest,
            {key: getattr(draft, key) for key in NutritionTargetDraftRequest.model_fields},
            changes,
        )
        new = await service.create_target_draft(user_id, body)
        card = await service.submit_target(user_id, new.id, new.version)
        extra["draft"] = {
            "id": str(new.id),
            "status": new.status,
            "version": new.version,
            "effective_from": new.effective_from.isoformat(),
            "values": body.model_dump(mode="json", exclude={"effective_from"}),
        }
    else:
        service = context.training_service
        draft = await service.repository.get_draft(user_id, UUID(after["plan_draft_id"]), lock=True)
        if draft is None or draft.version != after["draft_version"] or draft.status != "submitted":
            raise ValueError("原训练计划草稿已变化，请重新读取。")
        # Stored snapshots have internal IDs; the existing input schema does not.
        days = [
            {key: day[key] for key in ("day_index", "name", "estimated_minutes", "exercises")}
            for day in draft.days
        ]
        for day in days:
            day["exercises"] = [
                {key: value for key, value in exercise.items() if key != "id"}
                for exercise in day["exercises"]
            ]
        body = _patch(
            PlanDraftCreateRequest,
            {"name": draft.name, "weekly_frequency": draft.weekly_frequency, "days": days},
            changes,
        )
        new = await service.create_manual_draft(user_id, body)
        if new.validation_errors:
            raise ValueError(
                "修订计划未通过业务校验："
                + "；".join(str(item) for item in new.validation_errors)[:1000]
            )
        card = await service.submit_draft(user_id, new.id, new.version)
        extra["draft"] = json_safe(draft_payload(new))
    for key in ("base_plan_version_id", "base_target_version_id"):
        if key in after and card.after.get(key) != after[key]:
            raise ValueError("已生效的计划或目标已变化，请先核对最新版本再重新生成草稿。")
    return card, extra


def build_pending_revision_tools(context: AgentToolContext):
    @tool
    async def read_pending_business_draft(confirmation_id: UUID) -> dict:
        """Read the original profile/food/body/target/plan draft fields before patching it.

        Returns actual pending values, confirmation version and operation type. Use
        these fields to preserve other plan days/exercises when editing nested lists.
        """
        old = await context.confirmation_service.get(
            user_id=context.user_id, confirmation_id=confirmation_id
        )
        if old.operation_type not in REVISION_OPERATIONS.get(context.task_type, set()):
            return {
                "status": "needs_review",
                "message": "草稿类型与当前任务不一致，请核对要修订的卡片。",
            }
        if old.status != "pending" or old.expires_at <= datetime.now(UTC):
            return {
                "status": "needs_review",
                "message": "这份草稿已不在有效待确认状态，请核对当前记录。",
            }
        after = old.after
        if old.operation_type in {"food_create", "food_update"}:
            fields = after["food"]
        elif old.operation_type == "profile_update":
            fields = after["changes"]
        elif old.operation_type == "body_measurement_create":
            fields = after["measurement"]
        elif old.operation_type == "water_entry_create":
            fields = after["water"]
        elif old.operation_type == "nutrition_target_activate":
            draft = await context.nutrition_service.repository.get_target_draft(
                context.user_id, UUID(after["target_id"])
            )
            if draft is None:
                return {"status": "needs_review", "message": "原目标草稿不存在，请重新选择。"}
            fields = {key: getattr(draft, key) for key in NutritionTargetDraftRequest.model_fields}
        else:
            draft = await context.training_service.repository.get_draft(
                context.user_id, UUID(after["plan_draft_id"])
            )
            if draft is None:
                return {"status": "needs_review", "message": "原计划草稿不存在，请重新选择。"}
            fields = {
                "name": draft.name,
                "weekly_frequency": draft.weekly_frequency,
                "days": draft.days,
            }
        return {
            "status": "available",
            "confirmation": confirmation_payload(old),
            "draft": json_safe(fields),
        }

    @tool
    async def propose_pending_draft_revision(
        confirmation_id: UUID,
        expected_version: Annotated[int, Field(ge=1)],
        changes: dict,
    ) -> dict:
        """Patch a pending profile/food/body/target/plan after read_pending_business_draft.

        Supply only changed business fields at the top level, e.g. {height_cm: 175},
        {fat_g: 10, notes: 'new estimate basis'}, {name: 'new plan name'}.
        Unmentioned pending fields are preserved. Lists replace the corresponding list;
        read and retain unmodified days/exercises when changing a plan's days.
        This is NOT an edit to saved data. No IDs, versions, status or operation in changes.
        Uses existing business validators, atomically retires the old card, and still
        requires approval of the new card. Meals and calendar use their dedicated tools.
        """
        repository = context.confirmation_service.repository
        try:
            async with repository.session.begin_nested():
                old = await repository.get_confirmation(context.user_id, confirmation_id, lock=True)
                if old is None:
                    raise ValueError("未找到属于当前账户的待确认草稿。")
                allowed = REVISION_OPERATIONS.get(context.task_type, set())
                if old.operation_type not in allowed:
                    raise ValueError("草稿类型与当前任务不一致，请返回对应任务修订。")
                if (
                    old.status != "pending"
                    or old.version != expected_version
                    or old.expires_at <= datetime.now(UTC)
                ):
                    raise ValueError("这份草稿已确认、关闭、过期或版本已变化，请核对当前卡片。")
                card, extra = await _propose(context, old, changes)
                card.after = {**card.after, "replaces_confirmation_id": str(old.id)}
                old.status, old.version = "rejected", old.version + 1
                old.after = {**old.after, "replaced_by_confirmation_id": str(card.id)}
                await repository.session.flush()
                return {
                    "status": "confirmation_required",
                    "confirmation": confirmation_payload(card),
                    **extra,
                }
        except ValidationError as exc:
            fields = "、".join(
                ".".join(map(str, error["loc"])) or "字段组合"
                for error in exc.errors(include_input=False)
            )
            message = "修订字段不符合要求，请核对：" + fields[:300]
        except (
            ValueError,
            DatabaseConfirmationConflictError,
            NutritionConflictError,
            NutritionNotFoundError,
            ProfileNotFoundError,
            ProfileVersionConflictError,
            TrainingConflictError,
            TrainingNotFoundError,
        ) as exc:
            message = str(exc)
        return {
            "status": "needs_review",
            "error_code": "DRAFT_REVISION_REVIEW_REQUIRED",
            "message": message,
        }

    return [read_pending_business_draft, propose_pending_draft_revision]
