"""Date correction over existing saved-meal tools and confirmation runtime."""

from dataclasses import replace
from datetime import date

from nxtrep_backend.agents.tools import build_tools
from nxtrep_backend.schemas.agent import AgentBranchResult, AgentConfirmationCard

MEAL_NAMES = {"breakfast": "早餐", "lunch": "午饭", "dinner": "晚饭", "snack": "加餐"}


async def handle_meal_date_change(context, request) -> AgentBranchResult | None:
    task = request.task
    update = task.task_update
    if task.task_type != "nutrition_entry_update_draft" or update is None:
        return None
    parameters, entities = update.parameters, update.entities
    if parameters.get("action") != "change_date" and "target_date" not in parameters:
        return None
    results = []

    def clarify(message, fields, candidates=None):
        results.append(
            {
                "status": "needs_input",
                "missing_fields": fields,
                "candidates": candidates or [],
                "message": message,
            }
        )
        return AgentBranchResult(
            task_type=task.task_type,
            status="needs_input",
            missing_fields=fields,
            result={"task_answer": message, "task_tool_results": results},
        )

    missing = [key for key in ("source_date", "target_date") if not parameters.get(key)]
    if missing:
        return clarify(
            "要把哪一天的饮食移到哪一天？"
            if len(missing) == 2
            else "原来记在哪一天？"
            if missing == ["source_date"]
            else "应该改到哪一天？",
            missing,
        )
    try:
        source, target = (
            date.fromisoformat(parameters[key]) for key in ("source_date", "target_date")
        )
    except (ValueError, TypeError):
        return clarify(
            "请核对原日期和目标日期，例如10月11日改到10月10日。", ["source_date", "target_date"]
        )
    if source == target:
        return clarify("这两个日期相同，无需移动。应该改到哪一天？", ["target_date"])
    tools = {
        t.name: t
        for t in build_tools(
            replace(context, task_scope=entities, task_id=task.task_id),
            groups={"nutrition_changes", "confirmation", "confirmation_cancel"},
        )
    }

    async def call(name, args):
        result = await tools[name].ainvoke(args)
        results.append(result)
        return result

    old_card = None
    if entities.get("confirmation_id"):
        payload = await call(
            "read_confirmation_status", {"confirmation_id": entities["confirmation_id"]}
        )
        old_card = payload.get("confirmation")
        if old_card and old_card.get("status") == "succeeded":
            previous = (old_card.get("after") or {}).get("request") or {}
            if source.isoformat() == previous.get("source_date"):
                source = date.fromisoformat(previous["target_date"])
        if (
            old_card
            and old_card.get("status") == "pending"
            and old_card.get("operation_type") != "nutrition_entries_date_change"
        ):
            return clarify(
                "这餐还有其他待确认修改，请先确认或取消那份草稿，再调整日期。",
                ["pending_confirmation"],
            )
    args = {"day": source.isoformat(), "all_meals": True}
    if entities.get("entry_id") and parameters.get("scope") not in {"day", "meals"}:
        args["entry_id"] = entities["entry_id"]
    elif parameters.get("meal_type") and parameters.get("scope") not in {"day", "meals"}:
        args["meal_type"] = parameters["meal_type"]
    if parameters.get("eaten_time"):
        args["eaten_time"] = parameters["eaten_time"]
    read = await call("read_saved_meal_for_change", args)
    if read.get("status") != "available":
        return clarify(read.get("message") or "读取餐食失败，日期尚未修改。", ["source_date"])
    entries = read.get("selected_entries", [])
    if parameters.get("scope") == "meals":
        requested = parameters.get("meal_types")
        if (
            not isinstance(requested, list) or not requested
            or any(not isinstance(kind, str) or kind not in MEAL_NAMES for kind in requested)
        ):
            return clarify("要移动哪些餐次？请说明早餐、午饭、晚饭或加餐。", ["selection"])
        entries = [e for e in entries if e["meal_type"] in requested]
        missing_meals = set(requested) - {e["meal_type"] for e in entries}
        if missing_meals:
            labels = "、".join(MEAL_NAMES[kind] for kind in requested if kind in missing_meals)
            return clarify(
                f"{source}没有找到{labels}记录，尚未生成修改草稿。请核对原日期和餐次。",
                ["selection"],
            )
    if not entries:
        return clarify("这一天没有找到对应已保存饮食，日期尚未修改。", ["source_date"])
    if len(entries) > 1 and parameters.get("scope") not in {"day", "meals"}:
        names = {
            "breakfast": "早餐",
            "lunch": "午饭",
            "dinner": "晚饭",
            "snack": "加餐",
            "other": "餐食",
        }
        candidates = [
            {
                "kind": "meal",
                "id": e["entry_id"],
                "label": f"{e['eaten_at'][11:16]}的{names.get(e['meal_type'], '餐食')}",
            }
            for e in entries
        ]
        return clarify(
            f"{source}有"
            + "、".join(c["label"] for c in candidates)
            + f"。是全部移到{target}，还是只移动其中一餐？",
            ["selection"],
            candidates,
        )
    payload = await call(
        "propose_saved_meals_date_change",
        {
            "request": {
                "source_date": source.isoformat(),
                "target_date": target.isoformat(),
                "entries": [
                    {"entry_id": e["entry_id"], "expected_version": e["version"]} for e in entries
                ],
                "reason": "用户更正饮食记录归属日期",
            }
        },
    )
    if payload.get("status") != "confirmation_required":
        return clarify(
            payload.get("message") or "日期更正草稿未生成，原记录未修改。", ["current_record"]
        )
    card = AgentConfirmationCard.model_validate(payload["confirmation"])
    return AgentBranchResult(
        task_type=task.task_type,
        status="completed",
        requires_confirmation=True,
        confirmation_cards=[card],
        operation_results=[payload],
        result={
            "task_answer": (
                f"这{len(entries)}餐只调整记录日期，食物、份量和营养保持原样。"
            ),
            "task_tool_results": results,
        },
    )
