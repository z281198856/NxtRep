from nxtrep_backend.schemas.agent import (
    AgentBranchError,
    AgentBranchResult,
    AgentExecutionBundle,
)


class AgentExecutionSafetyValidator:
    """Enforce deterministic write-safety rules after model/tool execution."""

    _confirmation_required_tasks = {
        "workout_record_draft",
        "workout_record_update_draft",
        "workout_record_void_draft",
        "profile_update_draft",
        "workout_set_update_draft",
        "workout_set_void_draft",
        "nutrition_entry_update_draft",
        "nutrition_entry_delete_draft",
        "food_catalog_draft",
        "training_plan_draft",
        "schedule_change_draft",
        "training_progression_draft",
        "nutrition_record_draft",
        "nutrition_target_draft",
        "body_measurement_draft",
        "water_record_draft",
    }

    def validate(self, bundle: AgentExecutionBundle) -> AgentExecutionBundle:
        return bundle.model_copy(
            update={
                "branch_results": [
                    self._validate_branch(branch) for branch in bundle.branch_results
                ]
            }
        )

    def _validate_branch(self, branch: AgentBranchResult) -> AgentBranchResult:
        if branch.task_type == "confirmation_cancel" and branch.status == "completed":
            if not any(item.get("status") == "cancelled" for item in branch.operation_results):
                return self._failure(
                    branch, "CONFIRMATION_CANCEL_NOT_EXECUTED", "尚未核实草稿已取消，请重试。"
                )
        if (
            branch.task_type == "memory_write"
            and branch.status == "completed"
            and not any(
                item.get("status") in {"saved", "updated", "deleted"}
                for item in branch.operation_results
            )
        ):
            return self._failure(
                branch, "MEMORY_OPERATION_NOT_EXECUTED", "未完成长期记忆修改，请重试。"
            )
        expected_operations = {
            "workout_record_draft": "workout_record_create",
            "workout_record_update_draft": "workout_record_update",
            "workout_record_void_draft": "workout_record_void",
            "nutrition_entry_update_draft": {
                "nutrition_entry_update", "nutrition_entries_date_change"
            },
            "nutrition_entry_delete_draft": {"nutrition_entry_delete", "nutrition_entry_update"},
            "profile_update_draft": "profile_update",
            "workout_set_update_draft": "workout_set_update",
            "workout_set_void_draft": "workout_set_void",
            "food_catalog_draft": {"food_create", "food_update", "food_delete"},
            "training_plan_draft": "training_plan_activate",
            "schedule_change_draft": "calendar_reschedule",
            "training_progression_draft": "training_progression_apply",
            "nutrition_target_draft": "nutrition_target_activate",
            "nutrition_record_draft": "nutrition_entry_create",
            "body_measurement_draft": "body_measurement_create",
            "water_record_draft": "water_entry_create",
        }
        expected = expected_operations.get(branch.task_type)
        if branch.status == "completed" and branch.confirmation_cards and expected is not None:
            permitted = expected if isinstance(expected, set) else {expected}
            if any(card.operation_type not in permitted for card in branch.confirmation_cards):
                return self._failure(
                    branch,
                    "CONFIRMATION_OPERATION_MISMATCH",
                    "生成的确认项与请求不一致，请重新生成草稿。",
                )
        confirmation_operations = [
            item
            for item in branch.operation_results
            if item.get("status") == "confirmation_required"
        ]
        recovered_success = (
            bool((branch.result or {}).get("task_recovery"))
            and bool(branch.confirmation_cards)
            and all(card.status == "succeeded" for card in branch.confirmation_cards)
        )
        must_confirm = (
            (branch.task_type in self._confirmation_required_tasks and branch.status == "completed")
            and not recovered_success
            or bool(confirmation_operations)
        )

        if must_confirm and not branch.confirmation_cards:
            return self._failure(
                branch, "UNSAFE_WRITE_RESULT", "缺少可确认的草稿，无法执行正式修改，请重新生成。"
            )

        if branch.requires_confirmation and not branch.confirmation_cards:
            return self._failure(
                branch,
                "MISSING_CONFIRMATION_CARD",
                "本次需要用户确认，但确认项尚未生成，请重新生成草稿。",
            )

        if branch.confirmation_cards and not branch.requires_confirmation and not recovered_success:
            return branch.model_copy(update={"requires_confirmation": True})

        return branch

    @staticmethod
    def _failure(branch: AgentBranchResult, code: str, message: str) -> AgentBranchResult:
        return AgentBranchResult(
            task_type=branch.task_type,
            asset_ids=branch.asset_ids,
            status="failed",
            tool_runs=branch.tool_runs,
            error=AgentBranchError(code=code, message=message, retryable=True),
        )
