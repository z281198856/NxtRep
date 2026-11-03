"""Deterministic continuations using the registered tools and existing confirmations."""

import re
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from nxtrep_backend.agents.tools import AgentToolContext, build_tools
from nxtrep_backend.schemas.agent import AgentBranchResult, AgentConfirmationCard
from nxtrep_backend.schemas.nutrition import NutritionPortionChange
from nxtrep_backend.services.agent_execution import AgentBranchInput
from nxtrep_backend.services.agent_handlers.meal_date_change import handle_meal_date_change
from nxtrep_backend.services.agent_nutrition_feedback import is_nutrition_estimate_feedback
from nxtrep_backend.services.agent_resolution import blocking_input_fields
from nxtrep_backend.services.agent_task_state import TaskStateManager


def task_clarification(fields: list[str], candidates=()) -> str:
    if candidates and "selection" in fields:
        return "你是指" + "、".join(item.label for item in candidates[:8]) + "？"
    if any(field.startswith("items[") and field.endswith(".amount_g") for field in fields):
        return (
            "食物份量里有无效的克数，请改为大于0的有效克数；"
            "如果没有称重，也可以说一盒、一碗等大致份量。"
        )
    if fields and set(fields) <= {"exercise_name", "exercise_id", "weight_kg", "sets", "reps"}:
        if "exercise_name" in fields or "exercise_id" in fields:
            return "这次做了哪些动作？可以一个个告诉我。"
        if "weight_kg" in fields:
            return "用了多少公斤？"
        if "sets" in fields and "reps" in fields:
            return "做了几组，每组多少次？"
        return "做了几组？" if "sets" in fields else "每组多少次？"
    labels = {
        "food_name": "这顿饭吃了哪些食物",
        "food_details": "这顿饭吃了哪些食物",
        "items": "这顿饭吃了哪些食物",
        "identifiable_food": "能够辨认的食物名称或清晰照片",
        "exercise_name": "动作名称",
        "weight_kg": "多少公斤",
        "sets": "做了几组",
        "reps": "每组多少次",
        "amount_g": "食物改成多少克",
        "workout_date": "有效的训练日期（例如今天或具体日期）",
        "selection": "具体哪条记录或哪项食物",
        "exercise_id": "具体动作名称",
        "workout_id": "哪次训练",
        "workout_exercise_id": "具体动作记录",
        "entry_id": "哪顿餐食",
        "expected_workout_version": "需要重新核对的训练记录",
        "current_record": "需要重新核对的记录",
        "nutrition_correction": "要更正的食物份量或烹调方式",
    }
    return "请补充" + "、".join(labels.get(key, "这项操作需要的信息") for key in fields[:4]) + "。"


def deferred_training_response(request: AgentBranchInput) -> AgentBranchResult | None:
    """Acknowledge a semantic deferral without proposing invented business data."""
    task = request.task
    update = task.task_update
    if (
        task.task_type not in {"workout_record_draft", "training_plan_draft"}
        or update is None
        or update.parameters.get("awaiting_user_details") is not True
        or update.transition == "cancel"
        or update.invalid_fields
        or "selection" in task.missing_fields
        or update.entities.get("confirmation_id")
    ):
        return None
    return AgentBranchResult(
        task_type=task.task_type,
        asset_ids=task.asset_ids,
        status="needs_input",
        missing_fields=task.missing_fields or ["training_details"],
        result={
            "task_answer": (
                "好，先在对话里留着这次训练，等你把动作发来，我们接着补。"
                if task.task_type == "workout_record_draft"
                else "好，先在对话里留着这份训练计划，等你发具体内容后再完善。"
            ),
        },
    )


class TaskActionHandler:
    def __init__(self, context: AgentToolContext):
        self.context = context

    async def execute(self, request: AgentBranchInput) -> AgentBranchResult | None:
        deferred = deferred_training_response(request)
        if deferred is not None:
            return deferred
        state = TaskStateManager.load(request.conversation_context.task_state)
        active = state.active_task
        task = request.task
        update = task.task_update
        if (
            task.task_type == "general_question"
            and update
            and update.transition == "cancel"
            and active
            and active.status == "cancelled"
        ):
            return AgentBranchResult(
                task_type=task.task_type,
                status="completed",
                result={"task_answer": "好的，这次记录已取消。还没有写入正式记录。"},
            )
        if update is None:
            return None
        parameters, entities = update.parameters, update.entities
        kind = task.task_type
        date_change = await handle_meal_date_change(self.context, request)
        if date_change is not None:
            return date_change
        if kind == "nutrition_entry_update_draft" and update.invalid_fields:
            return AgentBranchResult(
                task_type=kind, status="needs_input", missing_fields=task.missing_fields,
                result={"task_answer": task_clarification(
                    task.missing_fields, active.candidates if active else (),
                )},
            )
        changed_fields = set(parameters.get("_changed_fields", parameters))
        portion_fields = {"amount_g", "food_name", "date", "meal_type", "reason", "note", "notes"}
        if kind == "nutrition_entry_update_draft" and (
            is_nutrition_estimate_feedback(request.message)
            or re.search(r"脂肪|蛋白质|碳水|热量|用油|做法", request.message)
            or parameters.get("replace_item")
            or parameters.get("replacements")
            or parameters.get("action") not in (None, "change_portion", "change_portions")
            or changed_fields - portion_fields - {"_changed_fields", "action"}
        ):
            # A cooking/nutrient reassessment needs the planner's estimate proposal,
            # not the deterministic portion editor (which may hold stale grams).
            return None
        if kind == "nutrition_entry_update_draft" and not parameters.get("amount_g"):
            # A general edit is not necessarily a portion edit. Let the tool-enabled
            # model interpret it instead of inventing a missing-grams requirement.
            return None
        handled_kind = kind in {
            "workout_record_draft",
            "workout_record_update_draft",
            "workout_record_void_draft",
            "nutrition_entry_update_draft",
            "nutrition_entry_delete_draft",
            "confirmation_cancel",
        }
        # Other handlers first resolve saved profile data and draft assumptions.
        # A router gap is not a hard execution requirement for every task.
        if handled_kind and task.missing_fields:
            blocking_fields = blocking_input_fields(task, task.missing_fields)
            if not blocking_fields:
                return None
            return AgentBranchResult(
                task_type=task.task_type,
                status="needs_input",
                missing_fields=blocking_fields,
                result={
                    "task_answer": task_clarification(
                        blocking_fields, active.candidates if active else ()
                    )
                },
            )
        if update.transition == "resume" and entities.get("confirmation_id"):
            tools = {tool.name: tool for tool in build_tools(self.context, groups={"confirmation"})}
            result = await tools["read_confirmation_status"].ainvoke(
                {"confirmation_id": entities["confirmation_id"]}
            )
            if result.get("status") == "available" and result["confirmation"].get("status") in {
                "pending",
                "succeeded",
            }:
                card = AgentConfirmationCard.model_validate(result["confirmation"])
                pending = card.status == "pending"
                payload = {
                    "status": "confirmation_required" if pending else "completed",
                    "confirmation": result["confirmation"],
                }
                return AgentBranchResult(
                    task_type=task.task_type,
                    status="completed",
                    result={
                        "task_answer": "继续刚才的内容，明细在下面。"
                        if pending
                        else "刚才的记录已确认生效，继续时可以修改它或追加新动作。",
                        "task_tool_results": [result],
                        "task_recovery": True,
                    },
                    operation_results=[payload],
                    confirmation_cards=[card],
                    requires_confirmation=pending,
                )
        pending_revision = await self._pending_meal_portion(request)
        if pending_revision is not None:
            return pending_revision
        if not handled_kind:
            return None
        context = replace(self.context, task_scope={**entities, "_task_parameters": parameters},
                          task_id=task.task_id)
        groups = {
            "workout_record",
            "workout_read",
            "nutrition_changes",
            "confirmation",
            "confirmation_cancel",
        }
        tools = {tool.name: tool for tool in build_tools(context, groups=groups)}
        results = []

        async def call(name, arguments):
            result = await tools[name].ainvoke(arguments)
            results.append(result)
            return result

        def reviewed(payload):
            if not results or results[-1] is not payload:
                results.append(payload)
            candidates = TaskStateManager._candidates(payload.get("candidates") or [])
            fields = payload.get("missing_fields") or ["selection"]
            show_choices = bool(
                candidates and set(fields) & {"exercise_id", "exercise_name", "workout_id"}
            )
            if show_choices:
                fields = [
                    field for field in fields
                    if field not in {"exercise_id", "exercise_name", "workout_id"}
                ] + ["selection"]
            answer = (
                task_clarification(fields, candidates)
                if show_choices
                else payload.get("message") or "请核对具体记录。"
            )
            return AgentBranchResult(
                task_type=kind,
                status="needs_input",
                missing_fields=fields,
                result={
                    "task_answer": answer,
                    "task_tool_results": results,
                },
            )

        old_card = None
        if entities.get("confirmation_id"):
            payload = await call(
                "read_confirmation_status", {"confirmation_id": entities["confirmation_id"]}
            )
            old_card = payload.get("confirmation") if payload.get("status") == "available" else None
        if kind == "confirmation_cancel":
            if not old_card:
                return reviewed({"message": "没有找到对应待确认草稿，请选择要取消的卡片。"})
            if old_card.get("status") != "pending":
                return reviewed(
                    {
                        "message": (
                            "这份草稿已不在待确认状态。撤销正式记录需要读取原记录并生成撤销草稿。"
                        )
                    }
                )
            payload = await call(
                "cancel_confirmation",
                {
                    "confirmation_id": old_card["confirmation_id"],
                    "expected_version": old_card["version"],
                },
            )
            return AgentBranchResult(
                task_type=kind,
                status="completed",
                operation_results=[payload],
                result={"task_answer": "这份待确认草稿已取消。", "task_tool_results": results},
            )

        if kind == "workout_record_draft":
            body = {
                key: value
                for key, value in parameters.items()
                if key
                in {
                    "exercise_name",
                    "weight_kg",
                    "sets",
                    "reps",
                    "workout_date",
                    "started_at",
                    "notes",
                }
            }
            body.update(
                {
                    key: value
                    for key, value in entities.items()
                    if key in {"exercise_id", "workout_id"}
                }
            )
            if body.get("workout_id"):
                detail = await call("read_workout_detail", {"workout_id": body["workout_id"]})
                workout = detail.get("workout", {})
                if not workout.get("version"):
                    return reviewed({"message": "尚不能核实要追加的训练，请先选择训练记录。"})
                body["expected_workout_version"] = workout["version"]
            if "workout_date" not in body:
                now = request.context_hints.occurred_at or datetime.now(ZoneInfo("Asia/Shanghai"))
                body["workout_date"] = now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
            payload = await call("propose_workout_record", {"request": body})
        elif kind.startswith("workout_record_"):
            if not entities.get("workout_id"):
                return None
            read = await call(
                "read_workout_record_for_change",
                {
                    key: value
                    for key, value in {
                        "workout_id": entities.get("workout_id"),
                        "workout_exercise_id": entities.get("workout_exercise_id"),
                        "exercise_name": parameters.get("exercise_name"),
                    }.items()
                    if value is not None
                },
            )
            if read.get("status") != "available":
                return reviewed(read)
            selected = read["selected_record"]
            body = {
                "expected_workout_version": selected["expected_workout_version"],
                "set_versions": selected["set_versions"],
                "reason": "用户在对话中更正或撤销刚才的训练记录",
            }
            if kind == "workout_record_update_draft":
                changed = parameters.get("_changed_fields", ["weight_kg", "reps", "sets"])
                unsupported = set(changed) - {"weight_kg", "reps", "sets", "exercise_name"}
                unsupported = {name for name in unsupported if not name.startswith("_")}
                # A semantic plan may repeat the selected record's date as context.
                # Only a genuinely different date is an unsupported modification.
                for field in ("workout_date", "date"):
                    if (selected.get("date") is not None
                            and str(parameters.get(field)) == str(selected["date"])):
                        unsupported.discard(field)
                if unsupported:
                    return reviewed({"error_code": "UNHANDLED_WORKOUT_FIELDS",
                        "unhandled_fields": sorted(unsupported),
                        "message": "这次修改包含当前训练更正尚不支持的内容，尚未生成部分修改草稿。"
                                   "目前可更正该动作的重量、每组次数和总组数；其他修改请明确具体要求。"})
                body.update(
                    {
                        key: parameters[key]
                        for key in ("weight_kg", "reps", "sets")
                        if key in parameters and key in changed
                    }
                )
                if not any(key in body for key in ("weight_kg", "reps", "sets")):
                    return reviewed(
                        {
                            "missing_fields": ["weight_kg", "reps"],
                            "message": "需要把重量、每组次数或组数改成多少？",
                        }
                    )
            payload = await call(
                "propose_workout_record_update"
                if kind.endswith("update_draft")
                else "propose_workout_record_void",
                {
                    "workout_id": selected["workout_id"],
                    "workout_exercise_id": selected["workout_exercise_id"],
                    "request": body,
                },
            )
        else:
            if not entities.get("entry_id"):
                return None
            read = await call("read_saved_meal_for_change", {"entry_id": entities["entry_id"]})
            if read.get("status") != "available":
                return reviewed(read)
            selected = read["selected_entry"]
            indices = []
            if "item_index" in entities:
                indices = [entities["item_index"]]
                current = next(
                    (item for item in selected["items"] if item.get("item_index") == indices[0]),
                    None,
                )
                expected_name = parameters.get("food_name")
                stale_unbound = not expected_name and entities.get("version") not in (
                    None,
                    selected["version"],
                )
                if (
                    current is None
                    or stale_unbound
                    or (expected_name and expected_name not in current.get("name", ""))
                ):
                    return reviewed(
                        {
                            "missing_fields": ["selection"],
                            "candidates": [selected],
                            "message": "这餐的食物已经变化，原来选中的项目不再对应。"
                            "请重新选择要操作的食物。",
                        }
                    )
            elif parameters.get("food_name"):
                indices = [
                    item["item_index"]
                    for item in selected["items"]
                    if parameters["food_name"] in item.get("name", "")
                ]
            if kind == "nutrition_entry_update_draft":
                if len(indices) != 1 or "amount_g" not in parameters:
                    if "amount_g" not in parameters and any(
                        word in request.message for word in ("脂肪", "蛋白质", "碳水", "热量")
                    ):
                        return reviewed(
                            {
                                "missing_fields": ["nutrition_correction"],
                                "message": (
                                    "这餐已保存。目前更正会按原营养依据重算食物份量；"
                                    "不能直接把估算的脂肪改成一个精确数字。"
                                    "你是想改具体食物份量，还是核对这餐用了多少油或哪种做法？"
                                ),
                            }
                        )
                    return reviewed(
                        {
                            "missing_fields": ["selection"] if len(indices) != 1 else ["amount_g"],
                            "message": "请说明要修改哪项食物，以及改成多少克。",
                            "candidates": [selected],
                        }
                    )
                body = {
                    "expected_version": selected["version"],
                    "changes": [{"item_index": indices[0], "amount_g": parameters["amount_g"]}],
                    "reason": "用户在对话中更正刚才这餐的食物份量",
                }
                payload = await call(
                    "propose_saved_meal_update", {"entry_id": selected["entry_id"], "request": body}
                )
            else:
                if len(indices) == 1:
                    payload = await call(
                        "propose_saved_meal_item_remove",
                        {
                            "entry_id": selected["entry_id"],
                            "item_index": indices[0],
                            "expected_version": selected["version"],
                            "reason": "用户在对话中移除这餐的指定食物",
                        },
                    )
                elif len(indices) > 1:
                    return reviewed(
                        {"message": "有多个同名食物，请选择具体哪项。", "candidates": [selected]}
                    )
                else:
                    payload = await call(
                        "propose_saved_meal_delete",
                        {
                            "entry_id": selected["entry_id"],
                            "request": {
                                "expected_version": selected["version"],
                                "reason": "用户在对话中撤销刚才这餐",
                            },
                        },
                    )
        if payload.get("status") != "confirmation_required":
            return reviewed(payload)
        card = AgentConfirmationCard.model_validate(payload["confirmation"])
        if (
            old_card
            and old_card.get("status") == "pending"
            and old_card["confirmation_id"] != str(card.confirmation_id)
            and (card.after or {}).get("replaces_confirmation_id") != old_card["confirmation_id"]
        ):
            await call(
                "cancel_confirmation",
                {
                    "confirmation_id": old_card["confirmation_id"],
                    "expected_version": old_card["version"],
                },
            )
        return AgentBranchResult(
            task_type=kind,
            status="completed",
            result={
                "task_answer": self._proposal_content(kind, card),
                "task_tool_results": results,
            },
            operation_results=[payload],
            confirmation_cards=[card],
            requires_confirmation=True,
        )

    @staticmethod
    def _proposal_content(kind: str, card: AgentConfirmationCard) -> str:
        preview = (card.after or {}).get("preview")
        if isinstance(preview, dict) and kind == "workout_record_draft":
            fields = ("exercise_name", "weight_kg", "sets", "reps")
            if all(preview.get(field) is not None for field in fields):
                return (
                    f"{preview['exercise_name']}按 {preview['weight_kg']} 公斤、"
                    f"{preview['sets']} 组，每组 {preview['reps']} 次。"
                )
        if kind.startswith("workout_record_"):
            return "这次训练的动作和组数明细在下面。"
        return "这餐的调整内容在下面，食物和份量按本次要求处理。"

    async def _pending_meal_portion(self, request: AgentBranchInput) -> AgentBranchResult | None:
        """Resolve a single explicit portion correction against the actual pending card."""
        task = request.task
        update = task.task_update
        if (
            task.task_type != "nutrition_record_draft"
            or update is None
            or update.transition not in {"continue", "correct"}
            or not update.entities.get("confirmation_id")
            or task.missing_fields
            or update.invalid_fields
        ):
            return None
        # Only shortcut one quantity edit with optional preservation clauses.
        # The explicit current expression supplies the new amount, even when the
        # router used items[] rather than a top-level amount_g. Never reuse old grams.
        match = re.fullmatch(
            r"(?P<target>[^,，;；。！？\n]*?)(?:改成|改为|改回|调整为|调整到|设为)\s*"
            r"(?P<amount>\d+(?:\.\d+)?)\s*(?:克|[gG])\s*(?:吧)?"
            r"(?P<tail>(?:[,，;；]\s*[^,，;；。！？\n]+)*)[。！!]?",
            request.message.strip(),
        )
        if match is None:
            return None
        clauses = re.split(r"[,，;；]", match["tail"])[1:]
        if any(
            not clause.strip().endswith(("不变", "不动", "照旧", "保持原样"))
            or re.search(r"\d|改成|改为|改回|调整|删除|去掉|换成|加上|再加", clause)
            for clause in clauses
        ):
            return None
        amount = Decimal(match["amount"])
        try:
            NutritionPortionChange(item_index=0, amount_g=amount)
        except ValidationError:
            return None
        context = replace(self.context, task_scope={**update.entities,
                          "_task_parameters": update.parameters}, task_id=task.task_id)
        tools = {
            tool.name: tool
            for tool in build_tools(context, groups={"confirmation", "nutrition_draft"})
        }
        read = await tools["read_confirmation_status"].ainvoke(
            {"confirmation_id": update.entities["confirmation_id"]}
        )
        results = [read]

        def clarify(message):
            return AgentBranchResult(
                task_type=task.task_type,
                status="needs_input",
                missing_fields=["selection"],
                result={"task_answer": message, "task_tool_results": results},
            )

        raw_card = read.get("confirmation") if read.get("status") == "available" else None
        if not raw_card or raw_card.get("operation_type") != "nutrition_entry_create":
            return clarify("没有找到这顿饭对应的待确认草稿，请选择要修改的餐食。")
        card = AgentConfirmationCard.model_validate(raw_card)
        if card.status != "pending" or card.expires_at <= datetime.now(UTC):
            return clarify(
                "这份草稿已不在有效待确认状态。如果已经确认，请选择已保存的餐食进行修改。"
            )
        items = raw_card.get("after", {}).get("preview", {}).get("items", [])
        if not items or not all(isinstance(item, dict) for item in items):
            return clarify("暂时无法核对这份草稿的食物明细，请重新选择原餐食。")
        target = re.sub(
            r"^(?:(?:把|将)|刚才(?:的|那个|那份|那碗)?|之前的?|这份|那份|那个|这个)+",
            "",
            match["target"].strip(),
        )
        target = re.sub(r"(?:的)?(?:份量|重量)$", "", target).strip()
        indices = []
        item_aliases = []
        for index, item in enumerate(items):
            name = re.sub(r"[（(].*?[）)]", "", item.get("name", "")).strip()
            aliases = {name, name[1:] if name.startswith(("熟", "生")) else name}
            if name.endswith("米饭"):
                aliases.add("米饭")
            item_aliases.append(aliases)
            if target in aliases:
                indices.append(index)
        if not target and len(items) == 1:
            indices = [0]
        if len(indices) != 1:
            names = "、".join(item.get("name", "未命名食物") for item in items[:8])
            return clarify(f"你要修改这份草稿中的哪项食物：{names}？")
        index = indices[0]
        context.task_scope["item_index"] = index
        current = items[index]
        if any(alias and alias in clause for alias in item_aliases[index] for clause in clauses):
            return clarify(f"你同时要求修改和保留{current['name']}，请确认这项份量是否需要改变。")
        if Decimal(str(current["amount_g"])) == amount:
            payload = {"status": "confirmation_required", "confirmation": raw_card}
            answer = f"这餐的{current['name']}已经按{amount.normalize():f}克计算，无需重复调整。"
        else:
            payload = await tools["propose_nutrition_entry_revision"].ainvoke(
                {
                    "confirmation_id": raw_card["confirmation_id"],
                    "expected_version": raw_card["version"],
                    "changes": [{"item_index": index, "amount_g": str(amount)}],
                }
            )
            results.append(payload)
            if payload.get("status") != "confirmation_required":
                return clarify(payload.get("message") or "这份草稿暂时无法修订，请重新核对。")
            card = AgentConfirmationCard.model_validate(payload["confirmation"])
            answer = f"这餐的{current['name']}按{amount.normalize():f}克重新计算。"
        return AgentBranchResult(
            task_type=task.task_type,
            status="completed",
            result={"task_answer": answer, "task_tool_results": results},
            operation_results=[payload],
            confirmation_cards=[card],
            requires_confirmation=True,
        )
