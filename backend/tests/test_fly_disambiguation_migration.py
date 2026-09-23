from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "a2b3c4d5e6f7_disambiguate_fly_exercises.py"
)


def load_migration() -> ModuleType:
    spec = spec_from_file_location("fly_disambiguation_migration", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fly_disambiguation_extends_catalog_expansion() -> None:
    migration = load_migration()

    assert migration.revision == "a2b3c4d5e6f7"
    assert migration.down_revision == "f1c2d3e4a5b6"


def test_fly_disambiguation_adds_unambiguous_search_aliases() -> None:
    migration = load_migration()
    aliases_by_exercise = {
        exercise_id: {
            alias
            for _, item_id, alias in migration.NEW_ALIASES
            if item_id == exercise_id
        }
        for exercise_id in (migration.CHEST_FLY_ID, migration.LATERAL_RAISE_ID)
    }

    assert aliases_by_exercise[migration.CHEST_FLY_ID] == {"胸部飞鸟"}
    assert aliases_by_exercise[migration.LATERAL_RAISE_ID] == {
        "肩部飞鸟",
        "站姿哑铃飞鸟",
    }
    assert all(alias != "哑铃飞鸟" for _, _, alias in migration.NEW_ALIASES)
