"""Read authenticated, current facts before asking the user for profile details."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nxtrep_backend.agents.tools.context import AgentToolContext
from nxtrep_backend.services.goals import GoalsNotFoundError
from nxtrep_backend.services.profile import ProfileNotFoundError

# These describe optional personalisation, not permission or clinical safety.
OPTIONAL_DRAFT_FIELDS = frozenset(
    {
        "age",
        "age_years",
        "birth_date",
        "height",
        "height_cm",
        "weight",
        "weight_kg",
        "sex",
        "gender",
        "body_fat",
        "body_fat_percent",
        "goal",
        "goal_type",
        "weekly_training_days",
        "training_frequency",
        "session_duration_minutes",
        "experience_level",
        "equipment",
        "activity_level",
        "target_date",
        "effective_from",
        "年龄",
        "生日",
        "身高",
        "体重",
        "性别",
        "体脂",
        "体脂率",
        "训练经验",
        "训练频率",
        "训练目标",
        "训练时长",
        "器械",
        "活动水平",
    }
)


async def load_personal_context(tools: AgentToolContext, user_id) -> dict:
    if user_id != tools.user_id:
        raise ValueError("Personal context must belong to the authenticated user")
    context: dict = {}
    try:
        profile = await tools.profile_service.get_profile(user_id=user_id)
    except ProfileNotFoundError:
        pass
    else:
        try:
            zone = ZoneInfo(profile.timezone or "Asia/Shanghai")
        except ZoneInfoNotFoundError:
            zone = ZoneInfo("Asia/Shanghai")
        today = datetime.now(zone).date()
        born = profile.birth_date
        context["today"] = today.isoformat()
        context["timezone"] = str(zone)
        context["profile"] = {
            "sex": profile.sex,
            "age_years": (
                today.year - born.year - ((today.month, today.day) < (born.month, born.day))
            )
            if born
            else None,
            "height_cm": format(profile.height_cm.normalize(), "f")
            if profile.height_cm is not None
            else None,
            "experience_level": profile.experience_level,
            "weekly_training_days": profile.weekly_training_days,
            "session_duration_minutes": profile.session_duration_minutes,
        }
    try:
        goals = await tools.goals_service.get_goals_and_constraints(user_id=user_id)
    except GoalsNotFoundError:
        pass
    else:
        context["goal_type"] = goals.goal.goal_type
        context["constraints"] = {
            "equipment": goals.constraints.equipment,
            "pain_or_injuries": goals.constraints.pain_or_injuries,
            "allergies": goals.constraints.allergies,
            "dietary_preferences": goals.constraints.dietary_preferences,
        }
    context["measurements"] = await tools.body_service.recent_measurement_summary(user_id)
    return context


def remaining_missing_fields(fields: list[str], context: dict, *, draft: bool) -> list[str]:
    values = {
        **context.get("profile", {}),
        **context.get("measurements", {}),
        **context.get("constraints", {}),
        "goal_type": context.get("goal_type"),
    }
    aliases = {
        "age": "age_years",
        "年龄": "age_years",
        "height": "height_cm",
        "身高": "height_cm",
        "weight": "weight_kg",
        "体重": "weight_kg",
        "性别": "sex",
        "gender": "sex",
    }
    remaining = []
    for name in dict.fromkeys(fields):
        if draft and name in OPTIONAL_DRAFT_FIELDS:
            continue
        if values.get(aliases.get(name, name)) is not None:
            continue
        remaining.append(name)
    return remaining
