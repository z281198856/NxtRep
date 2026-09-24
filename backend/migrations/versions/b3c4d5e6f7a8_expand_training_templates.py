"""Seed equipment-specific plans with one to seven weekly sessions.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-09-24

The catalog and UUID namespaces are frozen here so replaying migrations never
depends on application code. Existing plans and calendar snapshots are untouched.
"""

from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None

CATALOG_NAMESPACE = UUID("aafcebd3-aa88-47e3-9390-9ebdf3a7fe9f")
PLAN_NAMESPACE = UUID("543141ef-fc32-4082-80cb-09b9cab33f4c")
EQUIPMENT = {"bodyweight": "徒手", "dumbbell": "哑铃", "barbell": "杠铃", "cable": "绳索"}
PROFILES = {
    "muscle": ("增肌塑形", ["muscle_gain", "recomposition"], 3, 8, 12, 2, 90),
    "conditioning": ("减脂保肌与保持", ["fat_loss_retain", "maintain"], 2, 10, 15, 3, 90),
    "strength": ("力量基础", ["strength"], 3, 5, 8, 3, 180),
}
# day_index is an offset within the activation week, not a sequential session ID.
SCHEDULES = {
    1: ((1, "full_a"),),
    2: ((1, "full_a"), (4, "full_b")),
    3: ((1, "full_a"), (3, "full_b"), (5, "full_a")),
    4: ((1, "upper"), (2, "lower"), (4, "upper"), (5, "lower")),
    5: ((1, "upper"), (2, "lower"), (3, "recovery"), (4, "upper"), (5, "lower")),
    6: ((1, "upper"), (2, "lower"), (3, "recovery"), (4, "upper"), (5, "lower"), (6, "recovery")),
    7: (
        (1, "upper"),
        (2, "lower"),
        (3, "recovery"),
        (4, "upper"),
        (5, "lower"),
        (6, "recovery"),
        (7, "recovery"),
    ),
}
DAY_LABELS = {
    "full_a": "全身 A",
    "full_b": "全身 B",
    "upper": "上肢",
    "lower": "下肢",
    "recovery": "轻量恢复（轻松完成）",
}
NEW_EXERCISES = (
    (
        "bodyweight-prone-w-raise",
        "俯卧 W 提拉",
        "horizontal_pull",
        "bodyweight",
        "back",
        [
            "俯卧，屈肘让双臂呈 W 形，额头朝向地面。",
            "肩胛轻轻向后收，双手和手肘稍离地。",
            "停顿后缓慢放回，躯干不后仰。",
        ],
        "用于肩胛控制和背部辅助练习，不等同于负重划船。",
    ),
    (
        "dumbbell-floor-press",
        "哑铃地板卧推",
        "horizontal_push",
        "dumbbell",
        "chest",
        [
            "仰卧地面，屈膝踩稳，双手握哑铃。",
            "上臂轻触地面后，将哑铃推至胸部上方。",
            "缓慢下降，避免手肘撞击地面。",
        ],
        "无需训练凳；地面限制下降幅度，先使用可控重量。",
    ),
)


def exercise_id(slug: str) -> UUID:
    original = {"squat": 1, "bench": 2, "deadlift": 3, "row": 4, "press": 5}
    if slug in original:
        return UUID(f"10000000-0000-4000-8000-{original[slug]:012d}")
    return uuid5(CATALOG_NAMESPACE, f"nxtrep:exercise:{slug}")


MOVEMENTS = {
    "bodyweight": {
        "upper": ("bodyweight-push-up", "bodyweight-prone-w-raise"),
        "lower": ("bodyweight-squat", "bodyweight-glute-bridge", "bodyweight-reverse-lunge"),
        "full_a": (
            "bodyweight-squat",
            "bodyweight-push-up",
            "bodyweight-prone-w-raise",
            "bodyweight-glute-bridge",
        ),
        "full_b": (
            "bodyweight-reverse-lunge",
            "bodyweight-push-up",
            "bodyweight-prone-w-raise",
            "bodyweight-glute-bridge",
        ),
    },
    "dumbbell": {
        "upper": (
            "dumbbell-floor-press",
            "dumbbell-one-arm-row",
            "dumbbell-lateral-raise",
            "dumbbell-curl",
        ),
        "lower": (
            "dumbbell-goblet-squat",
            "dumbbell-romanian-deadlift",
            "bodyweight-reverse-lunge",
            "bodyweight-glute-bridge",
        ),
        "full_a": (
            "dumbbell-goblet-squat",
            "dumbbell-floor-press",
            "dumbbell-one-arm-row",
            "dumbbell-romanian-deadlift",
        ),
        "full_b": (
            "bodyweight-reverse-lunge",
            "dumbbell-floor-press",
            "dumbbell-one-arm-row",
            "dumbbell-lateral-raise",
        ),
    },
    "barbell": {
        "upper": ("bench", "row", "press"),
        "lower": ("squat", "deadlift", "bodyweight-reverse-lunge", "bodyweight-glute-bridge"),
        "full_a": ("squat", "bench", "row", "bodyweight-glute-bridge"),
        "full_b": ("deadlift", "press", "row", "bodyweight-reverse-lunge"),
    },
    "cable": {
        "upper": (
            "cable-chest-fly",
            "cable-seated-row",
            "cable-face-pull",
            "cable-triceps-pushdown",
        ),
        "lower": (
            "bodyweight-squat",
            "bodyweight-reverse-lunge",
            "cable-glute-kickback",
            "cable-hip-abduction",
        ),
        "full_a": (
            "bodyweight-squat",
            "cable-chest-fly",
            "cable-seated-row",
            "cable-glute-kickback",
        ),
        "full_b": (
            "bodyweight-reverse-lunge",
            "bodyweight-push-up",
            "cable-seated-row",
            "cable-face-pull",
        ),
    },
}
# Small-muscle and unloaded movements retain moderate reps in the strength track.
HEAVY_COMPOUNDS = {
    "squat",
    "bench",
    "deadlift",
    "row",
    "press",
    "dumbbell-goblet-squat",
    "dumbbell-floor-press",
    "dumbbell-one-arm-row",
    "dumbbell-romanian-deadlift",
}


def template_rows() -> list[dict]:
    rows = []
    for equipment, equipment_label in EQUIPMENT.items():
        for frequency, schedule in SCHEDULES.items():
            for profile, (label, goals, sets, rep_min, rep_max, rir, rest) in PROFILES.items():
                key = f"{equipment}:{frequency}:{profile}"
                days = []
                for day_index, kind in schedule:
                    recovery = kind == "recovery"
                    slugs = (
                        ("bodyweight-glute-bridge", "bodyweight-prone-w-raise")
                        if recovery
                        else MOVEMENTS[equipment][kind]
                    )
                    items = []
                    for order, slug in enumerate(slugs, 1):
                        strength_accessory = profile == "strength" and slug not in HEAVY_COMPOUNDS
                        items.append(
                            {
                                "id": str(uuid5(PLAN_NAMESPACE, f"{key}:{day_index}:{order}")),
                                "exercise_id": str(exercise_id(slug)),
                                "order_no": order,
                                "target_sets": 1 if recovery else sets,
                                "rep_min": 8 if recovery or strength_accessory else rep_min,
                                "rep_max": 12 if recovery or strength_accessory else rep_max,
                                "target_load_kg": None,
                                "target_rir": 5 if recovery else rir,
                                "rest_seconds": 60
                                if recovery
                                else 90
                                if strength_accessory
                                else rest,
                            }
                        )
                    minutes = (
                        15
                        if recovery
                        else 10
                        + sum(item["target_sets"] * (45 + item["rest_seconds"]) for item in items)
                        // 60
                    )
                    days.append(
                        {
                            "id": str(uuid5(PLAN_NAMESPACE, f"{key}:{day_index}")),
                            "day_index": day_index,
                            "name": f"{equipment_label} · {DAY_LABELS[kind]}",
                            "estimated_minutes": minutes,
                            "exercises": items,
                        }
                    )
                suffix = "（含轻量恢复）" if frequency >= 5 else ""
                rows.append(
                    {
                        "id": uuid5(PLAN_NAMESPACE, key),
                        "name": f"{equipment_label} · {frequency} 天{label}{suffix}",
                        "goal_types": goals,
                        "days_per_week": frequency,
                        "duration_minutes": max(day["estimated_minutes"] for day in days),
                        "equipment": (
                            ["bodyweight"]
                            if equipment == "bodyweight"
                            else [equipment, "bodyweight"]
                        ),
                        "days": days,
                        "is_active": True,
                    }
                )
    return rows


def upgrade() -> None:
    exercises = sa.table(
        "exercises",
        sa.column("id", sa.Uuid()),
        sa.column("name_zh", sa.String()),
        sa.column("movement_pattern", sa.String()),
        sa.column("equipment", sa.String()),
        sa.column("difficulty", sa.String()),
        sa.column("instructions", postgresql.JSONB()),
        sa.column("notes", sa.String()),
    )
    muscles = sa.table(
        "exercise_muscles",
        sa.column("exercise_id", sa.Uuid()),
        sa.column("muscle_code", sa.String()),
        sa.column("role", sa.String()),
    )
    op.execute(
        postgresql.insert(exercises)
        .values(
            [
                {
                    "id": exercise_id(slug),
                    "name_zh": name,
                    "movement_pattern": pattern,
                    "equipment": gear,
                    "difficulty": "beginner",
                    "instructions": steps,
                    "notes": notes,
                }
                for slug, name, pattern, gear, _, steps, notes in NEW_EXERCISES
            ]
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    op.execute(
        postgresql.insert(muscles)
        .values(
            [
                {"exercise_id": exercise_id(slug), "muscle_code": muscle, "role": "primary"}
                for slug, _, _, _, muscle, _, _ in NEW_EXERCISES
            ]
        )
        .on_conflict_do_nothing(index_elements=["exercise_id", "muscle_code"])
    )
    templates = sa.table(
        "training_templates",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("goal_types", postgresql.JSONB()),
        sa.column("days_per_week", sa.Integer()),
        sa.column("duration_minutes", sa.Integer()),
        sa.column("equipment", postgresql.JSONB()),
        sa.column("days", postgresql.JSONB()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(templates, template_rows())


def downgrade() -> None:
    # Exact seed IDs only; never rewrite activated plan or workout snapshots.
    ids = ", ".join(f"'{row['id']}'" for row in template_rows())
    op.execute(f"DELETE FROM training_templates WHERE id IN ({ids})")
    # Keep the two exercise references: saved workouts may already reference them.
