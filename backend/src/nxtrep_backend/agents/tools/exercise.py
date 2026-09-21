from uuid import UUID

from langchain.tools import tool
from langchain_core.tools import BaseTool

from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.services.exercise import ExerciseNotFoundError


def build_exercise_tools(context: AgentToolContext) -> list[BaseTool]:
    @tool
    async def search_exercises(
        keyword: str | None = None,
        equipment: str | None = None,
        muscle: str | None = None,
        limit: int = 10,
    ) -> dict:
        """Search visible exercises by name, alias, equipment, or muscle code."""
        safe_limit = min(max(limit, 1), 20)
        result = await context.exercises_service.list_exercises(
            user_id=context.user_id,
            keyword=keyword,
            equipment=equipment,
            muscle=muscle,
            page=1,
            page_size=safe_limit,
        )
        return {
            "status": "available",
            "total": result.total,
            "returned_count": len(result.items),
            "has_more": result.has_more,
            "exercises": [
                {
                    "id": str(item.exercise.id),
                    "name_zh": item.exercise.name_zh,
                    "aliases": item.aliases,
                    "equipment": item.exercise.equipment,
                    "primary_muscles": item.primary_muscles,
                    "is_custom": item.exercise.is_custom,
                }
                for item in result.items
            ],
        }

    @tool
    async def read_exercise_detail(exercise_id: UUID) -> dict:
        """Read technique, safety notes, and substitutions for one exercise."""
        try:
            result = await context.exercises_service.get_exercise_detail(
                user_id=context.user_id,
                exercise_id=exercise_id,
            )
        except ExerciseNotFoundError:
            return {
                "status": "not_found",
                "message": "The exercise does not exist or is not visible.",
            }

        exercise = result.exercise
        return {
            "status": "available",
            "exercise": {
                "id": str(exercise.id),
                "name_zh": exercise.name_zh,
                "aliases": result.aliases,
                "movement_pattern": exercise.movement_pattern,
                "equipment": exercise.equipment,
                "difficulty": exercise.difficulty,
                "primary_muscles": result.primary_muscles,
                "secondary_muscles": result.secondary_muscles,
                "instructions": exercise.instructions,
                "breathing": exercise.breathing,
                "common_errors": exercise.common_errors,
                "safety_notes": exercise.safety_notes,
                "substitutions": [
                    {
                        "id": str(item.exercise.id),
                        "name_zh": item.exercise.name_zh,
                        "equipment": item.exercise.equipment,
                        "reason": item.reason,
                    }
                    for item in result.substitutions
                ],
            },
        }

    return [search_exercises, read_exercise_detail]
