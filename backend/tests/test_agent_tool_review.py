import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from nxtrep_backend.services.agent_tool_review import unresolved_reviews


def tool(name, payload, call_id=None):
    return ToolMessage(name=name, tool_call_id=call_id or name, content=json.dumps(payload))


def example(family="meal"):
    entity, workout, set_id = str(uuid4()), str(uuid4()), str(uuid4())
    if family == "meal":
        read_name, propose_name, operation = (
            "read_saved_meal_for_change",
            "propose_saved_meal_update",
            "nutrition_entry_update",
        )
        selected_key = "selected_entry"
        selected = {"entry_id": entity, "version": 2, "items": [{"name": "米饭"}]}
        after = {"entry_id": entity, "expected_version": 2}
    elif family == "set":
        read_name, propose_name, operation = (
            "read_workout_set_for_change",
            "propose_workout_set_update",
            "workout_set_update",
        )
        selected_key = "selected_set"
        selected = {"workout_id": workout, "set_id": entity, "version": 2}
        after = {"workout_id": workout, "set_id": entity, "expected_version": 2}
    else:
        read_name, propose_name, operation = (
            "read_workout_record_for_change",
            "propose_workout_record_update",
            "workout_record_update",
        )
        selected_key = "selected_record"
        selected = {
            "workout_id": workout,
            "workout_exercise_id": entity,
            "expected_workout_version": 3,
            "set_versions": [{"set_id": set_id, "expected_version": 2}],
        }
        after = {
            "workout_id": workout,
            "workout_exercise_id": entity,
            "request": {"expected_workout_version": 3, "set_versions": selected["set_versions"]},
        }
    review = {"status": "needs_review", "message": "有多个候选，请选择具体记录。"}
    available = {"status": "available", selected_key: selected}
    proposal = {
        "status": "confirmation_required",
        "confirmation": {
            "confirmation_id": str(uuid4()),
            "operation_type": operation,
            "status": "pending",
            "impact": "批准后更正原记录",
            "version": 1,
            "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "after": after,
        },
    }
    return read_name, propose_name, review, available, proposal, selected


@pytest.mark.parametrize("family", ["meal", "set", "record"])
def test_later_unique_owned_read_and_matching_card_resolve_old_review(family):
    read, propose, review, available, proposal, _ = example(family)
    messages = [tool(read, review), tool(read, available), tool(propose, proposal)]
    assert unresolved_reviews(messages) == []
    assert json.loads(messages[0].content) == review  # History itself is retained.


@pytest.mark.parametrize("family", ["meal", "set", "record"])
@pytest.mark.parametrize(
    "order", ["card_only", "read_only", "read_before_review", "card_before_read"]
)
def test_card_alone_or_wrong_execution_order_never_resolves_review(family, order):
    read, propose, review, available, proposal, _ = example(family)
    rows = {
        "card_only": [tool(read, review), tool(propose, proposal)],
        "read_only": [tool(read, review), tool(read, available)],
        "read_before_review": [tool(read, available), tool(read, review), tool(propose, proposal)],
        "card_before_read": [tool(read, review), tool(propose, proposal), tool(read, available)],
    }
    assert unresolved_reviews(rows[order]) == [review]


@pytest.mark.parametrize("family", ["meal", "set", "record"])
@pytest.mark.parametrize(
    "failure", ["different_id", "wrong_version", "invalid_card", "resolved_card"]
)
def test_unrelated_or_invalid_confirmation_cannot_resolve_review(family, failure):
    read, propose, review, available, proposal, _ = example(family)
    card = proposal["confirmation"]
    if failure == "different_id":
        card["after"]["entry_id" if family == "meal" else "workout_id"] = str(uuid4())
    elif failure == "wrong_version":
        if family == "record":
            card["after"]["request"] = {**card["after"]["request"], "expected_workout_version": 9}
        else:
            card["after"]["expected_version"] = 9
    elif failure == "invalid_card":
        card.pop("confirmation_id")
    else:
        card["status"] = "failed"
    assert unresolved_reviews(
        [tool(read, review), tool(read, available), tool(propose, proposal)]
    ) == [review]


def test_success_for_one_candidate_set_does_not_erase_another_meal_review():
    read, propose, review, available, proposal, selected = example()
    other = {**selected, "entry_id": str(uuid4())}
    earlier = {**review, "candidates": [other], "message": "另一餐仍需选择"}
    matching = {**review, "candidates": [selected, other]}
    assert unresolved_reviews(
        [tool(read, earlier), tool(read, matching), tool(read, available), tool(propose, proposal)]
    ) == [earlier]


def test_original_tool_arguments_bind_review_to_its_real_entity():
    read, propose, review, available, proposal, _ = example()
    original = str(uuid4())
    call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": read,
                "id": "failed-read",
                "args": {"entry_id": original},
            }
        ],
    )
    assert unresolved_reviews(
        [call, tool(read, review, "failed-read"), tool(read, available), tool(propose, proposal)]
    ) == [review]


@pytest.mark.parametrize("family", ["set", "record"])
@pytest.mark.parametrize("grounding", ["candidate", "explicit_id", "none", "different_id"])
def test_canonical_exercise_name_requires_matching_verified_identity(family, grounding):
    read, propose, review, available, proposal, selected = example(family)
    args = {"exercise_name": "卧推"}
    selected["exercise_name"] = "杠铃卧推"
    id_key = "set_id" if family == "set" else "workout_exercise_id"
    if grounding == "candidate":
        review["candidates"] = [selected]
    elif grounding in {"explicit_id", "different_id"}:
        args[id_key] = selected[id_key] if grounding == "explicit_id" else str(uuid4())
    call = AIMessage(content="", tool_calls=[{"name": read, "args": args, "id": "lookup"}])
    result = unresolved_reviews([
        call, tool(read, review, "lookup"), tool(read, available), tool(propose, proposal),
    ])
    assert result == ([] if grounding in {"candidate", "explicit_id"} else [review])


def test_unique_read_for_unrelated_food_cannot_resolve_targeted_lookup():
    read, propose, review, available, proposal, _ = example()
    call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": read,
                "id": "failed-read",
                "args": {"food_name": "鸡胸肉"},
            }
        ],
    )
    assert unresolved_reviews(
        [call, tool(read, review, "failed-read"), tool(read, available), tool(propose, proposal)]
    ) == [review]


def test_late_review_requires_a_fresh_read_instead_of_using_an_old_one():
    read, propose, review, available, proposal, _ = example()
    later = {"status": "needs_review", "message": "最新版本已变化，需重新读取"}
    assert unresolved_reviews(
        [tool(read, review), tool(read, available), tool(propose, proposal), tool(propose, later)]
    ) == [later]


def test_other_domain_and_auth_error_remain_despite_valid_meal_card():
    read, propose, review, available, proposal, _ = example()
    other = {"status": "needs_review", "message": "品牌还未明确"}
    auth = {**review, "error_code": "AUTH_ERROR"}
    assert unresolved_reviews(
        [
            tool("read_custom_food", other),
            tool(read, auth),
            tool(read, available),
            tool(propose, proposal),
        ]
    ) == [other, auth]


def test_record_set_versions_must_match_the_unique_read():
    read, propose, review, available, proposal, _ = example("record")
    proposal = deepcopy(proposal)
    proposal["confirmation"]["after"]["request"]["set_versions"][0]["expected_version"] = 9
    assert unresolved_reviews(
        [tool(read, review), tool(read, available), tool(propose, proposal)]
    ) == [review]


def test_unknown_success_and_textual_claims_are_not_unique_read_evidence():
    read, propose, review, available, proposal, _ = example()
    assert unresolved_reviews(
        [
            tool(read, review),
            AIMessage(content="已经选好了，修改成功。"),
            tool("some_read", available),
            tool(propose, proposal),
        ]
    ) == [review]


def test_wrong_action_cannot_resolve_failed_proposal():
    read, propose, review, available, proposal, _ = example()
    proposal["confirmation"]["operation_type"] = "nutrition_entry_delete"
    assert unresolved_reviews(
        [tool(propose, review), tool(read, available), tool("propose_saved_meal_delete", proposal)]
    ) == [review]


def test_invalid_payloads_are_ignored_without_fabricating_a_resolution():
    read, _, review, _, _, _ = example()
    assert unresolved_reviews(
        [
            tool(read, review),
            ToolMessage(name=read, tool_call_id="invalid", content="not json"),
        ]
    ) == [review]
