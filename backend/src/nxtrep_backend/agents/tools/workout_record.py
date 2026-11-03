from datetime import date
from uuid import UUID

from langchain.tools import tool
from langchain_core.tools import BaseTool

from nxtrep_backend.agents.tools.common import confirmation_payload
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.schemas.workout_record import (
    WorkoutRecordDraftRequest,
    WorkoutRecordUpdateRequest,
    WorkoutRecordVoidRequest,
)
from nxtrep_backend.services.workout import WorkoutConflictError, WorkoutNotFoundError


def build_workout_record_tools(context: AgentToolContext) -> list[BaseTool]:
    service = getattr(context, "workout_record_service", None)
    if service is None:
        return []
    read_versions: dict[tuple[UUID, UUID], dict] = {}

    def review(exc: RuntimeError) -> dict:
        return {
            "status": "needs_review",
            "error_code": "WORKOUT_RECORD_NOT_FOUND"
            if isinstance(exc, WorkoutNotFoundError)
            else "WORKOUT_RECORD_CHANGED",
            "message": str(exc),
        }

    @tool
    async def propose_workout_record(request: WorkoutRecordDraftRequest) -> dict:
        """Draft actual exercise sets only after exercise, weight, sets and reps are supplied.

        Approval is required before any workout data is written. Append to an existing
        session only with its real workout_id and latest expected_workout_version.
        A new exercise must get fresh weight, sets and reps; never inherit these values.
        """
        scope = getattr(context, "task_scope", {})
        parameters = scope.get("_task_parameters", {})
        updates = {}
        if isinstance(parameters.get("exercise_name"), str):
            updates["exercise_name"] = parameters["exercise_name"]
        if parameters.get("workout_date"):
            expected_date = date.fromisoformat(str(parameters["workout_date"]))
            if request.workout_date is not None and request.workout_date != expected_date:
                return {
                    "status": "needs_review",
                    "missing_fields": ["workout_date"],
                    "error_code": "WORKOUT_TASK_DATE_MISMATCH",
                    "message": "所选训练的日期与本次任务不一致，请先核实要追加哪次训练，"
                    "不能为通过校验改日期。",
                }
            updates["workout_date"] = expected_date
        if updates:
            request = request.model_copy(update=updates)
        try:
            conversation_id = getattr(context, "trace_context", {}).get("conversation_id")
            scope_kwargs = (
                {"conversation_id": UUID(str(conversation_id))} if conversation_id else {}
            )
            result = await service.propose_record(context.user_id, request, **scope_kwargs)
        except (WorkoutNotFoundError, WorkoutConflictError) as exc:
            return review(exc)
        if isinstance(result, dict):
            return result
        return {"status": "confirmation_required", "confirmation": confirmation_payload(result)}

    @tool
    async def read_workout_record_for_change(
        workout_id: UUID | None = None,
        workout_date: date | None = None,
        exercise_name: str | None = None,
        workout_exercise_id: UUID | None = None,
    ) -> dict:
        """Resolve one recorded exercise and read all its current effective sets and versions.

        Returns real workout_id/workout_exercise_id and set_versions for a subsequent
        correction or void draft. Multiple matches require selection, never guessing.
        """
        try:
            result = await service.read_for_change(
                context.user_id, workout_id, workout_date, exercise_name, workout_exercise_id
            )
        except (WorkoutNotFoundError, WorkoutConflictError) as exc:
            return review(exc)
        if result.get("status") == "available":
            selected = result["selected_record"]
            read_versions[(UUID(selected["workout_id"]), UUID(selected["workout_exercise_id"]))] = {
                "expected_workout_version": selected["expected_workout_version"],
                "set_versions": selected["set_versions"],
            }
        return result

    async def propose(workout_id, workout_exercise_id, request):
        read = read_versions.get((workout_id, workout_exercise_id))
        supplied = request.model_dump(
            mode="json", include={"expected_workout_version", "set_versions"}
        )
        if read is None or supplied != read:
            return {
                "status": "needs_review",
                "missing_fields": ["current_record"],
                "message": "请先读取并核对这个动作的最新训练组和版本。",
            }
        try:
            result = await service.propose_change(
                context.user_id, workout_id, workout_exercise_id, request
            )
        except (WorkoutNotFoundError, WorkoutConflictError) as exc:
            return review(exc)
        return {"status": "confirmation_required", "confirmation": confirmation_payload(result)}

    @tool
    async def propose_workout_record_update(
        workout_id: UUID,
        workout_exercise_id: UUID,
        request: WorkoutRecordUpdateRequest,
    ) -> dict:
        """Draft a recorded exercise's weight/reps/total set count correction.

        Read its current record first. Reuse its real IDs, workout version and complete
        set_versions. Approval applies one atomic batch; it creates no new workout.
        sets reduces by voiding the last sets, or appends sets. Added sets require
        explicit weight/reps unless all existing sets agree. Never omit requested changes.
        """
        return await propose(workout_id, workout_exercise_id, request)

    @tool
    async def propose_workout_record_void(
        workout_id: UUID,
        workout_exercise_id: UUID,
        request: WorkoutRecordVoidRequest,
    ) -> dict:
        """Draft voiding all actual sets of one selected recorded exercise; approval required.

        Read its current versions first. Preserve revision history and other exercises;
        cancelling task state alone does not undo already recorded business data.
        """
        return await propose(workout_id, workout_exercise_id, request)

    return [
        propose_workout_record,
        read_workout_record_for_change,
        propose_workout_record_update,
        propose_workout_record_void,
    ]
