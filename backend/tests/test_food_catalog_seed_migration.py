from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

MIGRATION_PATH = (
    Path(__file__).parents[1] / "migrations" / "versions" / "7b9d2e4f6a81_seed_usda_food_catalog.py"
)


class RecordingOperations:
    def __init__(self) -> None:
        self.executed_sql: list[str] = []

    def execute(self, statement: str) -> None:
        self.executed_sql.append(statement)


def load_migration() -> ModuleType:
    spec = spec_from_file_location("food_catalog_seed_migration", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalized_sql(statements: list[str]) -> str:
    return " ".join(" ".join(statements).split()).lower()


def test_food_seed_extends_the_current_image_asset_revision() -> None:
    migration = load_migration()

    assert migration.revision == "7b9d2e4f6a81"
    assert migration.down_revision == "fc07f60845fc"
    assert migration.branch_labels is None
    assert migration.depends_on is None


def test_food_seed_inserts_traceable_public_foods_and_versions() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.upgrade()

    sql = normalized_sql(operations.executed_sql)
    assert "insert into foods" in sql
    assert "insert into food_versions" in sql
    assert "on conflict (id) do nothing" in sql
    assert sql.count("owner_user_id") >= 1
    assert "熟白米饭" in sql
    assert "熟鸡胸肉" in sql
    assert "熟西兰花" in sql
    assert "usda_fdc_168878" in sql
    assert "usda_fdc_171477" in sql
    assert "usda_fdc_169967" in sql


def test_food_seed_uses_kcal_and_macros_per_100_grams() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.upgrade()

    sql = normalized_sql(operations.executed_sql)
    expected_rows = (
        "100.000, 130.00, 2.690, 28.170, 0.280",
        "100.000, 165.00, 31.020, 0.000, 3.570",
        "100.000, 35.00, 2.380, 7.180, 0.410",
    )
    for row in expected_rows:
        assert row.lower() in sql

    assert "146.00, 2.380" not in sql


def test_food_seed_downgrade_removes_only_seeded_versions_and_foods() -> None:
    migration = load_migration()
    operations = RecordingOperations()
    migration.op = operations

    migration.downgrade()

    sql = normalized_sql(operations.executed_sql)
    assert "delete from food_versions" in sql
    assert "delete from foods" in sql
    assert "where id in" in sql
    assert "owner_user_id is null" not in sql
