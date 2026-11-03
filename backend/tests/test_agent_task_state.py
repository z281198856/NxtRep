from uuid import UUID, uuid4

import pytest

from nxtrep_backend.schemas.agent_task import (
    AgentTask,
    AgentTaskCandidate,
    AgentTaskState,
    AgentTaskUpdate,
)
from nxtrep_backend.services.agent_task_state import TaskStateManager


def collecting(**parameters):
    return TaskStateManager.apply_plan(
        {},
        "workout_record_draft",
        AgentTaskUpdate(transition="new", parameters={"exercise_name": "卧推", **parameters}),
    )


def test_parameters_are_accumulated_without_replaying_messages():
    state = collecting()
    first = TaskStateManager.prepare_turn(state.model_dump(mode="json"), "60kg。")
    assert first.parameters == {"weight_kg": "60"}
    assert first.state.active_task.missing_fields == ["sets", "reps"]
    second = TaskStateManager.prepare_turn(first.state, "四组，每组8个。")
    task = second.state.active_task
    assert task.parameters["weight_kg"] == "60"
    assert task.parameters["sets"] == 4
    assert task.parameters["reps"] == 8
    assert task.missing_fields == []
    assert task.status == "ready"
    assert task.task_id == state.active_task.task_id


def test_only_unambiguous_bare_number_completes_slot():
    state = collecting(weight_kg=60, sets=4)
    result = TaskStateManager.prepare_turn(state, "8")
    assert result.parameters == {"reps": 8}
    assert result.state.active_task.status == "ready"
    ambiguous = TaskStateManager.prepare_turn(collecting(), "8")
    assert ambiguous.parameters == {}
    assert ambiguous.clarification_required


def test_correction_uses_last_changed_field_not_any_recent_chat_number():
    state = TaskStateManager.prepare_turn(collecting(), "60kg").state
    corrected = TaskStateManager.prepare_turn(state, "不对，是55")
    assert corrected.transition == "correct"
    assert corrected.parameters == {"weight_kg": "55"}
    assert corrected.state.active_task.parameters["weight_kg"] == "55"
    assert state.active_task.parameters["weight_kg"] == "60"


def test_bare_correction_after_multiple_numbers_requires_clarification():
    state = TaskStateManager.prepare_turn(collecting(), "60kg").state
    state = TaskStateManager.prepare_turn(state, "四组每组8个").state
    result = TaskStateManager.prepare_turn(state, "不对，是55")
    assert result.parameters == {}
    assert result.clarification_required


def test_planner_cannot_replace_previously_bound_business_id_or_item_index():
    state = meal_state()
    state.active_task.entities["item_index"] = 1
    original = state.active_task.entities["entry_id"]
    result = TaskStateManager.apply_plan(
        state,
        "nutrition_entry_update_draft",
        {
            "transition": "correct",
            "entities": {"entry_id": str(uuid4()), "item_index": 0},
            "parameters": {"amount_g": "200"},
        },
    )
    assert result.active_task.entities["entry_id"] == original
    assert result.active_task.entities["item_index"] == 1
    assert result.active_task.missing_fields == ["selection"]


def test_meal_selection_clears_previously_selected_food_index():
    state = meal_state()
    state.active_task.entities["item_index"] = 1
    result = TaskStateManager.prepare_turn(state, "删除整顿午饭")
    assert result.selection.kind == "meal"
    assert "item_index" not in result.entities
    assert "item_index" not in result.state.active_task.entities


def test_completed_suspended_task_stays_completed_on_resume():
    state = collecting(weight_kg=60, sets=4, reps=8)
    state.active_task.status = "completed"
    state.active_task.entities["confirmation_id"] = str(uuid4())
    state.suspended_task, state.active_task = state.active_task, None
    result = TaskStateManager.prepare_turn(state, "继续刚才的训练")
    assert result.state.active_task.status == "completed"


@pytest.mark.parametrize(
    "message", ["卧推60kg，上斜55kg", "不要用60kg", "鸡腿饭60克多少热量", "55kg or 60kg", "-55kg"]
)
def test_complex_or_negated_input_is_left_to_existing_planner(message):
    result = TaskStateManager.prepare_turn(collecting(), message)
    assert result.parameters == {}


@pytest.mark.parametrize("message", ["10000kg", "1.5组", "0组", "1001次", "nan公斤"])
def test_out_of_range_numbers_do_not_enter_persisted_task(message):
    result = TaskStateManager.prepare_turn(collecting(), message)
    assert result.parameters == {}


def test_new_exercise_inherits_session_but_not_training_numbers():
    state = collecting(weight_kg=55, sets=4, reps=8, date="2026-10-08")
    identifier = str(uuid4())
    state.active_task.entities = {"workout_id": identifier, "workout_exercise_id": str(uuid4())}
    state.active_task.status = "completed"
    previous_id = state.active_task.task_id
    updated = TaskStateManager.apply_plan(
        state,
        "workout_record_draft",
        {
            "parameters": {"exercise_name": "上斜卧推"},
        },
    )
    task = updated.active_task
    assert task.task_id != previous_id
    assert task.entities == {"workout_id": identifier}
    assert task.parameters == {"exercise_name": "上斜卧推", "date": "2026-10-08"}
    assert task.missing_fields == ["weight_kg", "sets", "reps"]


def test_food_query_suspends_and_resume_restores_original_task():
    state = collecting(weight_kg=60)
    identifier = state.active_task.task_id
    interrupted = TaskStateManager.apply_plan(state, "general_question")
    assert interrupted.active_task is None
    assert interrupted.suspended_task.task_id == identifier
    resumed = TaskStateManager.prepare_turn(interrupted, "继续刚才的训练")
    assert resumed.handled and resumed.transition == "resume"
    assert resumed.state.suspended_task is None
    assert resumed.state.active_task.task_id == identifier
    assert resumed.state.active_task.parameters["weight_kg"] == "60"
    assert resumed.state.active_task.missing_fields == ["sets", "reps"]


def test_resume_returns_existing_pending_card_instead_of_starting_new_draft():
    state = collecting(weight_kg=60, sets=4, reps=8)
    confirmation = str(uuid4())
    state.active_task.entities = {"confirmation_id": confirmation}
    state.active_task.status = "awaiting_confirmation"
    interrupted = TaskStateManager.apply_plan(state, "knowledge_retrieval")
    resumed = TaskStateManager.prepare_turn(interrupted, "恢复刚才的计划")
    assert resumed.state.active_task.status == "awaiting_confirmation"
    assert resumed.entities["confirmation_id"] == confirmation


def test_read_only_query_does_not_erase_completed_record_focus():
    state = collecting(weight_kg=60, sets=4, reps=8)
    state.active_task.status = "completed"
    state.active_task.entities = {"workout_id": str(uuid4())}
    interrupted = TaskStateManager.apply_plan(state, "knowledge_retrieval")
    assert interrupted.active_task == state.active_task


def test_cross_domain_task_never_inherits_slots_even_if_planner_says_continue():
    state = collecting(weight_kg=60)
    switched = TaskStateManager.apply_plan(
        state,
        "nutrition_record_draft",
        {
            "parameters": {"meal_type": "lunch"},
            "missing_fields": ["items"],
        },
    )
    assert switched.active_task.parameters == {"meal_type": "lunch"}
    assert switched.suspended_task.parameters["weight_kg"] == "60"
    assert switched.active_task.task_id != state.active_task.task_id


def test_cancel_unexecuted_task_does_not_request_business_delete():
    state = collecting(weight_kg=60)
    # A previous read has no business write to undo.
    state.active_task.last_tool_result = {"status": "available"}
    result = TaskStateManager.prepare_turn(state, "算了，不记了")
    assert result.handled and result.transition == "cancel"
    assert not result.requires_business_action
    assert result.state.active_task.status == "cancelled"
    assert result.state.active_task.missing_fields == []


def test_cancel_executed_record_keeps_real_target_for_existing_void_tool():
    state = collecting(weight_kg=60, sets=4, reps=8)
    workout = str(uuid4())
    state.active_task.status = "completed"
    state.active_task.entities = {"workout_id": workout}
    result = TaskStateManager.prepare_turn(state, "算了，刚才那条不要了")
    assert result.requires_business_action and not result.handled
    assert result.state.active_task.status == "completed"
    assert result.entities["workout_id"] == workout


def test_cancel_pending_confirmation_requires_actual_card_cancellation():
    state = collecting(weight_kg=60, sets=4, reps=8)
    confirmation = str(uuid4())
    state.active_task.status = "awaiting_confirmation"
    state.active_task.entities = {"confirmation_id": confirmation}
    result = TaskStateManager.prepare_turn(state, "取消刚才的草稿")
    assert result.requires_business_action
    assert result.entities["confirmation_id"] == confirmation
    assert result.state.active_task.status == "awaiting_confirmation"


def test_cancel_multiple_recovered_cards_requires_selection_and_keeps_card_choices():
    state = collecting(weight_kg=60, sets=4, reps=8)
    identifiers = [uuid4(), uuid4()]
    state.active_task.candidates = [
        AgentTaskCandidate(kind="confirmation", id=identifier, label=f"第{index}份草稿")
        for index, identifier in enumerate(identifiers, 1)
    ]
    state.active_task.status = "collecting"
    state.active_task.missing_fields = ["selection"]
    prepared = TaskStateManager.prepare_turn(state, "算了")
    assert not prepared.handled
    assert prepared.requires_business_action and prepared.clarification_required
    assert prepared.state.active_task.status == "awaiting_confirmation"
    assert prepared.state.active_task.missing_fields == ["selection"]
    assert [candidate.id for candidate in prepared.state.active_task.candidates] == identifiers
    cancellation = TaskStateManager.apply_plan(
        prepared.state,
        "confirmation_cancel",
        {"transition": "correct", "missing_fields": ["selection"]},
    )
    assert [candidate.id for candidate in cancellation.active_task.candidates] == identifiers
    assert cancellation.active_task.missing_fields == ["selection"]
    selected = TaskStateManager.prepare_turn(cancellation, "第二个")
    assert selected.entities["confirmation_id"] == str(identifiers[1])
    assert selected.state.active_task.task_type == "confirmation_cancel"
    assert selected.state.active_task.missing_fields == []


def meal_state():
    entry = str(uuid4())
    state = AgentTaskState(active_task=AgentTask(task_type="nutrition_entry_update_draft"))
    return TaskStateManager.commit_results(
        state,
        [
            {
                "status": "available",
                "selected_entry": {
                    "entry_id": entry,
                    "version": 3,
                    "date": "2026-10-08",
                    "meal_type": "lunch",
                    "items": [
                        {"name": "米饭", "amount_g": "200"},
                        {"name": "鸡胸肉", "amount_g": "150"},
                    ],
                },
            }
        ],
    )


def test_named_reference_resolves_real_meal_id_and_item_index():
    state = meal_state()
    result = TaskStateManager.prepare_turn(state, "刚才那个鸡胸肉改成200g")
    assert result.selection.label == "鸡胸肉"
    assert result.entities == {"entry_id": state.active_task.entities["entry_id"], "item_index": 1}
    assert not result.clarification_required


@pytest.mark.parametrize("name,item_index", [("鸡胸肉", 1), ("米饭", 0)])
def test_unique_food_short_name_resolves_cooked_database_label(name, item_index):
    state = meal_state()
    for candidate in state.active_task.candidates:
        if candidate.kind == "meal_item":
            candidate.label = ["熟白米饭", "熟鸡胸肉"][candidate.item_index]
    result = TaskStateManager.prepare_turn(state, f"刚才那个{name}改成200g")
    assert result.selection.item_index == item_index
    assert result.entities["item_index"] == item_index
    assert result.parameters == {"amount_g": "200"}
    assert not result.clarification_required


def test_food_short_name_does_not_guess_between_raw_and_cooked_candidates():
    state = meal_state()
    for candidate in state.active_task.candidates:
        if candidate.kind == "meal_item":
            candidate.label = ["生鸡胸肉", "熟鸡胸肉"][candidate.item_index]
    result = TaskStateManager.prepare_turn(state, "刚才那个鸡胸肉改成200g")
    assert result.selection is None
    assert result.parameters == {}
    assert result.clarification_required
    exact = TaskStateManager.prepare_turn(state, "刚才那个熟鸡胸肉改成200g")
    assert exact.selection.item_index == 1
    assert exact.parameters == {"amount_g": "200"}


def test_two_named_food_changes_are_not_reduced_to_one_short_name_match():
    state = meal_state()
    for candidate in state.active_task.candidates:
        if candidate.kind == "meal_item":
            candidate.label = ["熟白米饭", "熟鸡胸肉"][candidate.item_index]
    result = TaskStateManager.prepare_turn(state, "刚才那个鸡胸肉和米饭改成200g")
    assert result.selection is None
    assert result.clarification_required


def test_preserved_foods_and_meal_are_not_selected_as_deletion_targets():
    state = meal_state()
    state.active_task.parameters["food_name"] = "米饭"
    result = TaskStateManager.prepare_turn(state, "只删除午饭中的鸡胸肉，保留米饭和整顿午饭")
    assert result.selection.kind == "meal_item"
    assert result.selection.label == "鸡胸肉"
    assert result.entities["item_index"] == 1
    assert result.state.active_task.parameters["food_name"] == "鸡胸肉"
    assert not result.clarification_required


def test_selecting_whole_meal_clears_old_child_food_focus():
    state = meal_state()
    state.active_task.parameters["food_name"] = "鸡胸肉"
    state.active_task.entities["item_index"] = 1
    result = TaskStateManager.prepare_turn(state, "删除整顿午饭")
    assert result.selection.kind == "meal"
    assert "food_name" not in result.state.active_task.parameters
    assert "item_index" not in result.state.active_task.entities


def test_rejected_unique_object_is_not_selected_again():
    state = meal_state()
    state.active_task.candidates = [state.active_task.candidates[-1]]
    result = TaskStateManager.prepare_turn(state, "不是这个")
    assert result.selection is None
    assert result.clarification_required
    assert result.state.active_task.candidates == []
    assert result.state.active_task.missing_fields == ["selection"]


@pytest.mark.parametrize("value", [-55, "nan", None, "1.2345"])
def test_invalid_numeric_correction_cannot_silently_reuse_previous_value(value):
    state = collecting(weight_kg=60, sets=4, reps=8)
    update = AgentTaskUpdate(transition="correct", parameters={"weight_kg": value})
    assert update.invalid_fields == ["weight_kg"]
    assert "invalid_fields" not in update.model_dump()
    result = TaskStateManager.apply_plan(state, "workout_record_draft", update)
    assert "weight_kg" not in result.active_task.parameters
    assert result.active_task.missing_fields == ["weight_kg"]
    assert result.active_task.invalid_fields == ["weight_kg"]


def test_invalid_meal_portion_survives_persistence_and_unrelated_followup():
    state = TaskStateManager.apply_plan(
        {},
        "nutrition_record_draft",
        AgentTaskUpdate(parameters={"food_name": "米饭", "amount_g": -150}),
    )
    raw = state.model_dump(mode="json")
    assert raw["active_task"]["invalid_fields"] == ["amount_g"]

    result = TaskStateManager.apply_plan(
        raw,
        "nutrition_record_draft",
        AgentTaskUpdate(parameters={"meal_type": "lunch"}),
    )
    assert result.active_task.invalid_fields == ["amount_g"]
    assert result.active_task.missing_fields == ["amount_g"]
    assert result.active_task.status == "collecting"
    assert "amount_g" not in result.active_task.parameters


def test_valid_followup_resolves_only_the_corresponding_invalid_field():
    state = AgentTaskState(
        active_task=AgentTask(
            task_type="nutrition_record_draft",
            parameters={"food_name": "米饭"},
            invalid_fields=["amount_g", "food_id"],
            missing_fields=["amount_g", "food_id"],
        )
    )
    state = TaskStateManager.apply_plan(
        state, "nutrition_record_draft", AgentTaskUpdate(parameters={"amount_g": 150})
    )
    assert state.active_task.invalid_fields == ["food_id"]
    assert state.active_task.missing_fields == ["food_id"]
    assert state.active_task.parameters["amount_g"] == "150"

    food_id = str(uuid4())
    state = TaskStateManager.apply_plan(
        state, "nutrition_record_draft", AgentTaskUpdate(entities={"food_id": food_id})
    )
    assert state.active_task.invalid_fields == []
    assert state.active_task.missing_fields == []
    assert state.active_task.entities["food_id"] == food_id


def test_deterministic_numeric_followup_clears_persisted_invalid_value():
    state = TaskStateManager.apply_plan(
        collecting(weight_kg=60, sets=4, reps=8),
        "workout_record_draft",
        AgentTaskUpdate(parameters={"weight_kg": -55}),
    )
    result = TaskStateManager.prepare_turn(state.model_dump(mode="json"), "55kg")
    assert result.state.active_task.parameters["weight_kg"] == "55"
    assert result.state.active_task.invalid_fields == []
    assert result.state.active_task.missing_fields == []
    assert result.state.active_task.status == "ready"


def test_old_task_state_without_invalid_fields_remains_compatible():
    state = collecting(weight_kg=60, sets=4, reps=8)
    raw = state.model_dump(mode="json")
    raw["active_task"].pop("invalid_fields")
    assert TaskStateManager.load(raw).active_task.invalid_fields == []


@pytest.mark.parametrize("value", ["一盒", None, -150, True, False])
def test_invalid_top_level_portion_preserves_original_input_without_relaxing_validation(value):
    raw = {"food_name": "米饭", "amount_g": value}
    update = AgentTaskUpdate(parameters=raw)
    assert update.parameters["_amount_g_input"] == value
    assert "amount_g" not in update.parameters
    assert update.invalid_fields == ["amount_g"]
    assert "_amount_g_input" not in raw


@pytest.mark.parametrize(
    "value,expected",
    [
        (float("nan"), "nan"),
        (float("inf"), "inf"),
        (10**20, str(10**20)),
        (1e20, str(1e20)),
    ],
)
def test_nonfinite_portion_hint_is_not_mistaken_for_an_empty_input(value, expected):
    update = AgentTaskUpdate(parameters={"food_name": "米饭", "amount_g": value})
    assert update.parameters["_amount_g_input"] == expected
    assert update.invalid_fields == ["amount_g"]


@pytest.mark.parametrize("value", [200, "200"])
def test_valid_portion_does_not_keep_an_obsolete_input_hint(value):
    update = AgentTaskUpdate(
        parameters={"food_name": "米饭", "amount_g": value, "_amount_g_input": "一盒"}
    )
    assert update.parameters["amount_g"] == "200"
    assert "_amount_g_input" not in update.parameters
    assert update.invalid_fields == []


def test_resume_current_completed_focus_does_not_require_a_suspended_copy():
    state = collecting(weight_kg=60, sets=4, reps=8)
    state.active_task.status = "completed"
    state.active_task.entities["confirmation_id"] = str(uuid4())
    result = TaskStateManager.prepare_turn(state, "继续刚才的训练")
    assert result.handled and result.transition == "resume"
    assert result.state.active_task.status == "completed"


def test_delete_ambiguous_meal_or_food_requires_clarification():
    result = TaskStateManager.prepare_turn(meal_state(), "把刚才那个删了")
    assert result.selection is None
    assert result.clarification_required


def test_unambiguous_ordinal_resolves_candidate_uuid():
    identifiers = [str(uuid4()), str(uuid4())]
    state = AgentTaskState(active_task=AgentTask(task_type="workout_set_update_draft"))
    state = TaskStateManager.commit_results(
        state,
        [
            {
                "status": "needs_review",
                "candidates": [
                    {
                        "set_id": identifier,
                        "workout_id": str(uuid4()),
                        "exercise_name": "卧推",
                        "set_index": index,
                    }
                    for index, identifier in enumerate(identifiers, 1)
                ],
            }
        ],
    )
    result = TaskStateManager.prepare_turn(state, "第二个")
    assert result.selection.id == UUID(identifiers[1])
    assert result.entities["set_id"] == identifiers[1]
    assert result.state.active_task.missing_fields == []


def test_valid_confirmation_is_pending_not_business_success():
    state = collecting(weight_kg=60, sets=4, reps=8)
    confirmation = str(uuid4())
    result = TaskStateManager.commit_results(
        state,
        [
            {
                "status": "confirmation_required",
                "confirmation": {
                    "confirmation_id": confirmation,
                    "status": "pending",
                    "operation_type": "workout_record_create",
                },
            }
        ],
    )
    assert result.active_task.status == "awaiting_confirmation"
    assert result.active_task.entities == {"confirmation_id": confirmation}
    assert state.active_task.status == "ready"


def test_invalid_card_and_success_prose_never_complete_task():
    state = collecting(weight_kg=60)
    result = TaskStateManager.commit_results(
        state,
        [{"message": "记录成功，workout_id=刚才那个"}],
        [
            {"confirmation_id": "刚才那个", "status": "succeeded"},
        ],
    )
    assert result.active_task.status == "collecting"
    assert result.active_task.entities == {}


def test_structured_result_completes_task_without_an_llm_decision():
    state = collecting(weight_kg=60, sets=4, reps=8)
    workout, exercise = str(uuid4()), str(uuid4())
    result = TaskStateManager.commit_results(
        state,
        [
            {
                "success": True,
                "workout_id": workout,
                "workout_exercise_id": exercise,
                "expected_workout_version": 4,
            }
        ],
    )
    assert result.active_task.status == "completed"
    assert result.active_task.entities == {
        "workout_id": workout,
        "workout_exercise_id": exercise,
        "expected_workout_version": 4,
    }


def test_state_serialization_is_bounded_and_invalid_raw_is_safe():
    state = collecting(weight_kg=60)
    result = TaskStateManager.commit_results(state, [{"success": False, "message": "a" * 20_000}])
    assert len(result.active_task.last_tool_result["message"]) == 600
    assert result.active_task.status == "failed"
    assert TaskStateManager.load({"active_task": {"task_id": "not-uuid"}}).active_task is None
    assert TaskStateManager.load({"schema_version": 2}).active_task is None


def test_parallel_food_names_and_portions_become_valid_structured_items():
    raw = {"food_name": [" 米饭 ", "鸡胸肉"], "amount_g": [200, "150.000"], "meal_type": "lunch"}
    update = AgentTaskUpdate(parameters=raw)
    assert update.parameters == {
        "items": [
            {"food_name": "米饭", "amount_g": "200"},
            {"food_name": "鸡胸肉", "amount_g": "150"},
        ],
        "meal_type": "lunch",
    }
    assert update.invalid_fields == []
    assert raw["amount_g"] == [200, "150.000"]
    assert "items" not in raw


@pytest.mark.parametrize(
    "names,amounts",
    [
        (["米饭", "鸡胸肉"], [200]),
        (["米饭", ""], [200, 150]),
        (["米饭", None], [200, 150]),
        (["米饭", "鸡胸肉"], [200, -150]),
        (["米饭", "鸡胸肉"], [200, "nan"]),
        (["米饭", "鸡胸肉"], [200, float("inf")]),
        (["米饭", "鸡胸肉"], [200, True]),
        (["米饭"] * 21, [200] * 21),
    ],
    ids=[
        "length_mismatch",
        "blank_name",
        "null_name",
        "negative",
        "nan",
        "inf",
        "bool",
        "too_many",
    ],
)
def test_invalid_parallel_food_lists_are_not_presented_as_complete_items(names, amounts):
    update = AgentTaskUpdate(parameters={"food_name": names, "amount_g": amounts})
    assert "items" not in update.parameters
    assert update.invalid_fields == ["amount_g"]


def test_parallel_food_compatibility_preserves_other_invalid_numeric_fields():
    update = AgentTaskUpdate(
        parameters={"food_name": ["米饭"], "amount_g": [200], "weight_kg": -55}
    )
    assert update.parameters["items"] == [{"food_name": "米饭", "amount_g": "200"}]
    assert update.invalid_fields == ["weight_kg"]


def test_parallel_food_lists_do_not_overwrite_existing_conflicting_items():
    update = AgentTaskUpdate(
        parameters={
            "food_name": ["米饭"],
            "amount_g": [200],
            "items": [{"food_name": "鸡胸肉", "amount_g": "150"}],
        }
    )
    assert update.parameters["items"] == [{"food_name": "鸡胸肉", "amount_g": "150"}]
    assert update.invalid_fields == ["amount_g"]
