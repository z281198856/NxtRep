"""Check concrete meal operations against the current structured plan, before writes."""

from pydantic import BaseModel


def meal_action_preflight(tool_name: str, arguments: dict, scope: dict) -> dict | None:
    parameters = scope.get("_task_parameters") or {}
    reference = scope.get("_reference_entities") or {}
    if tool_name == "propose_nutrition_entry" and (
        reference.get("entry_id")
        or reference.get("meal_id")
        or parameters.get("reference_meal_type")
    ):
        return {
            "status": "needs_review",
            "error_code": "REFERENCE_TOOL_REQUIRED",
            "required_tool": "propose_nutrition_entry_from_reference",
            "message": "请使用参考餐工具复制原食物并提交新增、替换或移除，避免遗漏原餐。",
        }
    if tool_name not in {
        "propose_nutrition_entry_from_reference",
        "propose_nutrition_entry_revision",
        "propose_saved_meal_update",
    }:
        return None
    body = arguments.get("request", arguments)
    body = body.model_dump() if isinstance(body, BaseModel) else body
    changes = [c.model_dump() if isinstance(c, BaseModel) else c for c in body.get("changes", [])]
    expected = {
        "additions": parameters.get("additions") or [],
        "replacements": parameters.get("replacements")
        or ([parameters["replace_item"]] if parameters.get("replace_item") else []),
        "removals": parameters.get("remove_item_indices") or parameters.get("removals") or [],
    }
    # On a follow-up, inherited instructions must not be replayed as new operations.
    changed = parameters.get("_changed_fields")
    if changed is not None and tool_name != "propose_nutrition_entry_from_reference":
        aliases = {
            "additions": {"additions"},
            "replacements": {"replacements", "replace_item"},
            "removals": {"remove_item_indices", "removals"},
        }
        expected = {
            key: value if aliases[key] & set(changed) else [] for key, value in expected.items()
        }
    if not any(expected.values()) and not (
        tool_name == "propose_nutrition_entry_from_reference" and "_task_parameters" in scope
    ):
        return None
    actual = {
        "additions": body.get("additions") or [],
        "replacements": body.get("replacements") or [c for c in changes if c.get("replacement")],
        "removals": body.get("remove_item_indices") or [],
    }
    missing = [key for key in expected if len(actual[key]) != len(expected[key])]
    if missing:
        return {
            "status": "needs_review",
            "error_code": "MEAL_ACTION_MISMATCH",
            "unhandled_fields": missing,
            "requested_operations": {k: len(v) for k, v in expected.items()},
            "proposed_operations": {k: len(v) for k, v in actual.items()},
            "message": "食物新增、替换或移除与本轮要求不一致，尚未生成草稿。"
            "请完整执行要求；不能把追加变成替换，也不能遗漏修改。",
        }
    return None
