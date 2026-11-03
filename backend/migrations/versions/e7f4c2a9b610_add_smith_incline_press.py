"""Add the missing Smith incline press without aliasing it to a free barbell press."""

from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert

revision = "e7f4c2a9b610"
down_revision = "da6e91c7b240"
branch_labels = None
depends_on = None

NAMESPACE = UUID("aafcebd3-aa88-47e3-9390-9ebdf3a7fe9f")
EXERCISE_ID = uuid5(NAMESPACE, "nxtrep:exercise:smith-incline-press")
ALIASES = ("史密斯上斜卧推", "上斜史密斯卧推", "史密斯机上斜推胸", "Smith incline bench press")


def upgrade() -> None:
    exercises = sa.table(
        "exercises",
        sa.column("id", sa.Uuid()),
        sa.column("name_zh", sa.String()),
        sa.column("equipment", sa.String()),
    )
    aliases = sa.table(
        "exercise_aliases",
        sa.column("id", sa.Uuid()),
        sa.column("exercise_id", sa.Uuid()),
        sa.column("alias", sa.String()),
        sa.column("normalized_alias", sa.String()),
    )
    muscles = sa.table(
        "exercise_muscles",
        sa.column("exercise_id", sa.Uuid()),
        sa.column("muscle_code", sa.String()),
        sa.column("role", sa.String()),
    )
    op.execute(
        insert(exercises)
        .values(
            id=EXERCISE_ID,
            name_zh="史密斯上斜推胸",
            equipment="smith_machine",
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    for alias in ALIASES:
        op.execute(
            insert(aliases)
            .values(
                id=uuid5(NAMESPACE, f"nxtrep:exercise-alias:smith-incline-press:{alias}"),
                exercise_id=EXERCISE_ID,
                alias=alias,
                normalized_alias=alias.strip().casefold(),
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
    op.execute(
        insert(muscles)
        .values(
            exercise_id=EXERCISE_ID,
            muscle_code="chest",
            role="primary",
        )
        .on_conflict_do_nothing(index_elements=["exercise_id", "muscle_code"])
    )


def downgrade() -> None:
    # Preserve the catalog entry and any workout references on downgrade.
    pass
