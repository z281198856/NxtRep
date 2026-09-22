from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "f1c2d3e4a5b6_expand_food_and_exercise_catalogs.py"
)


def load_migration() -> ModuleType:
    spec = spec_from_file_location("catalog_expansion_migration", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalog_expansion_extends_current_head() -> None:
    migration = load_migration()

    assert migration.revision == "f1c2d3e4a5b6"
    assert migration.down_revision == "e4b7c2a9d851"


def test_catalog_expansion_contains_browsable_common_foods() -> None:
    migration = load_migration()
    names = {row[1] for row in migration.FOODS}

    assert len(migration.FOODS) >= 25
    assert {"水煮鸡蛋", "全脂牛奶", "原味燕麦片", "香蕉", "熟菠菜"} <= names
    assert all(len(row) == 8 for row in migration.FOODS)


def test_catalog_expansion_adds_dumbbell_and_cable_families() -> None:
    migration = load_migration()
    dumbbell = {row[1] for row in migration.EXERCISES if row[3] == "dumbbell"}
    cable = {row[1] for row in migration.EXERCISES if row[3] == "cable"}

    assert len(dumbbell) >= 12
    assert len(cable) >= 12
    assert {"哑铃高脚杯深蹲", "单臂哑铃划船", "坐姿哑铃推举"} <= dumbbell
    assert {"绳索坐姿划船", "绳索面拉", "绳索三头下压"} <= cable
    assert all(row[5] for row in migration.EXERCISES)
    assert all(row[7] for row in migration.EXERCISES)


def test_catalog_expansion_keeps_every_visible_equipment_filter_useful() -> None:
    migration = load_migration()
    counts = {
        equipment: sum(1 for row in migration.EXERCISES if row[3] == equipment)
        for equipment in ("bodyweight", "dumbbell", "machine", "cable")
    }

    assert counts["bodyweight"] >= 6
    assert counts["dumbbell"] >= 12
    assert counts["machine"] >= 4
    assert counts["cable"] >= 12
