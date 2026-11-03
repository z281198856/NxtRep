from datetime import date

from langchain.tools import tool
from langchain_core.tools import BaseTool

from nxtrep_backend.agents.tools.common import confirmation_payload
from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.schemas.profile import ProfileUpdateRequest
from nxtrep_backend.services.goals import GoalsNotFoundError
from nxtrep_backend.services.profile import ProfileNotFoundError, ProfileVersionConflictError


def build_profile_tools(context: AgentToolContext) -> list[BaseTool]:
    @tool
    async def read_profile_summary() -> dict:
        """Read the current user's fitness-related profile summary."""
        try:
            profile = await context.profile_service.get_profile(
                user_id=context.user_id,
            )
        except ProfileNotFoundError:
            return {
                "status": "not_configured",
                "message": "The user has not configured a profile.",
            }

        age_years = None
        if profile.birth_date is not None:
            today = date.today()
            age_years = (
                today.year
                - profile.birth_date.year
                - ((today.month, today.day) < (profile.birth_date.month, profile.birth_date.day))
            )

        return {
            "status": "available",
            "profile": {
                "sex": profile.sex,
                "age_years": age_years,
                "height_cm": (str(profile.height_cm) if profile.height_cm is not None else None),
                "experience_level": profile.experience_level,
                "weekly_training_days": profile.weekly_training_days,
                "session_duration_minutes": profile.session_duration_minutes,
                "timezone": profile.timezone,
            },
        }

    @tool
    async def read_active_goal() -> dict:
        """Read the current user's active goal and safety constraints."""
        try:
            result = await context.goals_service.get_goals_and_constraints(
                user_id=context.user_id,
            )
        except GoalsNotFoundError:
            return {
                "status": "not_configured",
                "message": "The user has not configured a goal and constraints.",
            }

        goal = result.goal
        constraints = result.constraints
        return {
            "status": "available",
            "goal": {
                "goal_type": goal.goal_type,
                "target_date": (
                    goal.target_date.isoformat() if goal.target_date is not None else None
                ),
                "target_weight_kg": (
                    str(goal.target_weight_kg) if goal.target_weight_kg is not None else None
                ),
            },
            "constraints": {
                "equipment": constraints.equipment,
                "pain_or_injuries": constraints.pain_or_injuries,
                "allergies": constraints.allergies,
                "dietary_preferences": constraints.dietary_preferences,
                "preferred_exercise_ids": constraints.preferred_exercise_ids,
                "disliked_exercise_ids": constraints.disliked_exercise_ids,
            },
            "warnings": result.warnings,
        }

    return [read_profile_summary, read_active_goal]


def build_profile_draft_tools(context: AgentToolContext) -> list[BaseTool]:
    read_version: int | None = None
    proposals: dict[str, dict] = {}

    @tool
    async def read_profile_for_update() -> dict:
        """Read personal profile, latest recorded weight and version before edits."""
        nonlocal read_version
        try:
            profile = await context.profile_service.read_update_snapshot(context.user_id)
        except ProfileNotFoundError:
            return {"status": "needs_review", "message": "尚未建立个人资料，请先完成账号资料设置。"}
        read_version = profile["version"]
        return {"status": "available", "profile": profile}

    @tool
    async def propose_profile_update(changes: ProfileUpdateRequest) -> dict:
        """Draft requested profile fields; read first, approve later. No goal/plan edits."""
        if read_version != changes.expected_version:
            return {"status": "needs_review", "message": "请先读取最新个人资料，再生成修改草稿。"}
        key = changes.model_dump_json(exclude_unset=True)
        if key in proposals:
            return proposals[key]
        try:
            confirmation = await context.profile_service.propose_update(context.user_id, changes)
        except (ProfileNotFoundError, ProfileVersionConflictError):
            return {
                "status": "needs_review",
                "message": "个人资料已变化或不存在，请重新读取后核对。",
            }
        except ValueError as exc:
            return {"status": "needs_review", "message": str(exc)}
        payload = {
            "status": "confirmation_required",
            "confirmation": confirmation_payload(confirmation),
        }
        proposals[key] = payload
        return payload

    return [read_profile_for_update, propose_profile_update]
