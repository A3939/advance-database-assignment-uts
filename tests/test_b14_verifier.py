"""Reject schema drift before a B14 verifier can start Docker or claim A's version."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def verifier(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location("b14_verifier_test", ROOT / "tools/verify_b14_postgres.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "checkout"
    shutil.copytree(ROOT / "sql/migrations", root / "sql/migrations")
    (root / "config").mkdir()
    shutil.copyfile(ROOT / "config/ac-inventory.json", root / "config/ac-inventory.json")
    return root


def reject_before_side_effects(verifier, checkout, monkeypatch, tmp_path, capsys, message):
    out = tmp_path / "must-not-exist"
    monkeypatch.setattr(verifier, "ROOT", checkout)
    monkeypatch.setattr(sys, "argv", ["verify_b14_postgres.py", "--output", str(out)])

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid migrations reached package checking or an external process")

    monkeypatch.setattr(verifier, "check_install", forbidden)
    monkeypatch.setattr(verifier, "run", forbidden)
    monkeypatch.setattr(verifier.subprocess, "run", forbidden)
    with pytest.raises(SystemExit) as error:
        verifier.main()
    assert error.value.code == 2
    assert message in capsys.readouterr().err
    assert not out.exists()


def test_original_migrations_match_pinned_version(verifier, checkout):
    contents = verifier.pinned_migrations(checkout)
    assert len(contents) == 11
    assert {p.name for p in contents} == {p.name for p in (ROOT / "sql/migrations").glob("*.sql")}
    assert all(content == (ROOT / "sql/migrations" / p.name).read_bytes()
               for p, content in contents.items())


@pytest.mark.parametrize("name,change", [
    ("009_database_roles.sql", b"\nGRANT ALL ON meta.batch TO arsia_loader;\n"),
    ("011_review_validation_fixes.sql", b"\n-- changed after reference verification\n"),
])
def test_changed_migration_with_updated_inventory_is_rejected(
        verifier, checkout, monkeypatch, tmp_path, capsys, name, change):
    path = checkout / "sql/migrations" / name
    path.write_bytes(path.read_bytes() + change)
    inventory_path = checkout / "config/ac-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    entry = next(item for item in inventory["schema_files"] if item["path"] == "sql/migrations/" + name)
    entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    assert entry["sha256"] != verifier.A_MIGRATIONS[name]
    reject_before_side_effects(verifier, checkout, monkeypatch, tmp_path, capsys,
                              "Migration differs from A " + verifier.A_VERSION + ": " + name)


@pytest.mark.parametrize("change", ["missing", "extra", "renamed"])
def test_exact_migration_filenames_are_required(verifier, checkout, monkeypatch, tmp_path, capsys, change):
    path = checkout / "sql/migrations/011_review_validation_fixes.sql"
    if change == "missing":
        path.unlink()
    elif change == "extra":
        (path.parent / "012_extra.sql").write_text("SELECT 1;\n", encoding="utf-8")
    else:
        path.rename(path.with_name("011_different_name.sql"))
    reject_before_side_effects(verifier, checkout, monkeypatch, tmp_path, capsys,
                              "Expected the exact 11 migration filenames")


def test_validated_bytes_are_kept_for_application(verifier, checkout):
    contents = verifier.pinned_migrations(checkout)
    path = checkout / "sql/migrations/009_database_roles.sql"
    checked = contents[path]
    path.write_bytes(checked + b"\nGRANT ALL ON meta.batch TO arsia_loader;\n")
    assert contents[path] == (ROOT / "sql/migrations/009_database_roles.sql").read_bytes()
    assert contents[path] != path.read_bytes()
