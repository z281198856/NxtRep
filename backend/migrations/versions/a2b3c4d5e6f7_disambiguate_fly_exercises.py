"""disambiguate fly exercises

Revision ID: a2b3c4d5e6f7
Revises: f1c2d3e4a5b6
Create Date: 2026-09-23
"""

from collections.abc import Sequence
from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a2b3c4d5e6f7"
down_revision: str | Sequence[str] | None = "f1c2d3e4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAMESPACE = UUID("aafcebd3-aa88-47e3-9390-9ebdf3a7fe9f")


def _id(kind: str, slug: str) -> UUID:
    return uuid5(_NAMESPACE, f"nxtrep:{kind}:{slug}")


CHEST_FLY_ID = _id("exercise", "dumbbell-fly")
LATERAL_RAISE_ID = _id("exercise", "dumbbell-lateral-raise")

NEW_ALIASES = (
    ("dumbbell-fly:chest-fly", CHEST_FLY_ID, "胸部飞鸟"),
    ("dumbbell-lateral-raise:shoulder-fly", LATERAL_RAISE_ID, "肩部飞鸟"),
    (
        "dumbbell-lateral-raise:standing-dumbbell-fly",
        LATERAL_RAISE_ID,
        "站姿哑铃飞鸟",
    ),
)


def upgrade() -> None:
    exercises = sa.table(
        "exercises",
        sa.column("id", sa.Uuid()),
        sa.column("name_zh", sa.String()),
        sa.column("instructions", postgresql.JSONB()),
    )
    exercise_aliases = sa.table(
        "exercise_aliases",
        sa.column("id", sa.Uuid()),
        sa.column("exercise_id", sa.Uuid()),
        sa.column("alias", sa.String()),
        sa.column("normalized_alias", sa.String()),
    )

    op.execute(
        exercises.update()
        .where(exercises.c.id == CHEST_FLY_ID)
        .values(name_zh="平板哑铃胸部飞鸟")
    )
    op.execute(
        exercises.update()
        .where(exercises.c.id == LATERAL_RAISE_ID)
        .values(
            instructions=[
                "双手持哑铃贴近大腿两侧，肘部保持轻微弯曲",
                "向身体两侧抬至肩高，沿原轨迹缓慢下放",
            ]
        )
    )
    op.bulk_insert(
        exercise_aliases,
        [
            {
                "id": _id("exercise-alias", slug),
                "exercise_id": exercise_id,
                "alias": alias,
                "normalized_alias": alias.strip().casefold(),
            }
            for slug, exercise_id, alias in NEW_ALIASES
        ],
    )


def downgrade() -> None:
    exercises = sa.table(
        "exercises",
        sa.column("id", sa.Uuid()),
        sa.column("name_zh", sa.String()),
        sa.column("instructions", postgresql.JSONB()),
    )
    alias_ids = [_id("exercise-alias", row[0]) for row in NEW_ALIASES]

    op.execute(
        sa.text("DELETE FROM exercise_aliases WHERE id IN :ids").bindparams(
            sa.bindparam("ids", expanding=True, value=alias_ids)
        )
    )
    op.execute(
        exercises.update()
        .where(exercises.c.id == CHEST_FLY_ID)
        .values(name_zh="哑铃飞鸟")
    )
    op.execute(
        exercises.update()
        .where(exercises.c.id == LATERAL_RAISE_ID)
        .values(
            instructions=[
                "双臂自然下垂，肘部保持轻微弯曲",
                "向身体两侧抬至肩高，缓慢下放",
            ]
        )
    )
