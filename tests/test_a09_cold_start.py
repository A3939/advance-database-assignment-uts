import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "config/schema-v1.1.json"
TOOL_PATH = ROOT / "tools/verify_a09_cold_start.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("verify_a09_cold_start", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_schema_contract_has_declared_inventory():
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    tables = contract["tables"]

    assert contract["contract"] == "arsia-schema-v1.1"
    assert len(tables) == contract["dictionary"]["declared_table_count"] == 17
    assert sum(len(columns) for columns in tables.values()) == 129
    assert contract["dictionary"]["declared_field_count"] == 129
    assert len({tuple(column[:2]) for columns in tables.values() for column in columns}) > 0

    for table, columns in tables.items():
        assert "." in table
        assert columns
        assert len({column[0] for column in columns}) == len(columns)
        assert all(len(column) == 3 and isinstance(column[2], bool) for column in columns)


def test_migrations_are_exactly_001_through_011():
    tool = load_tool()
    migrations = tool.find_migrations()

    assert [path.name[:3] for path in migrations] == [f"{number:03}" for number in range(1, 12)]
    assert all(path.suffix == ".sql" for path in migrations)


def test_verifier_uses_pinned_temporary_postgres():
    tool = load_tool()

    assert tool.IMAGE.startswith("postgres:16-bookworm@sha256:")
    assert "--tmpfs" in tool.container_arguments("example", "/tmp/example.env")
    assert "127.0.0.1::5432" in tool.container_arguments("example", "/tmp/example.env")
    assert "/var/lib/postgresql/data" in tool.container_arguments("example", "/tmp/example.env")
