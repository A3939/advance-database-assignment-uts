"""D02-only PostgreSQL tests against B's real definitions and runtime objects.

Requires an isolated database migrated with the fixed A 001--011 SQL. The
runner script provisions it; never point these tests at a shared database.
No platform inventory, FP1 implementation, D03 or publication is fabricated.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest

if not os.environ.get("D02_LOADER_DSN"):
    pytest.skip("Run tools/verify_postgres.py to provision an isolated database", allow_module_level=True)

import psycopg
from psycopg.types.json import Jsonb

B_ROOT = Path(os.environ["ARSIA_B_ROOT"]).resolve()
A_ROOT = Path(os.environ["ARSIA_A_ROOT"]).resolve()
D_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ["D02_EVIDENCE_DIR"]).resolve()
sys.path.insert(0, str(B_ROOT / "src"))
sys.path.insert(0, str(D_ROOT / "src"))

from arsia_d02.dimensions import (  # noqa: E402
    DimensionContractError, build_dimension_rows, load_dimensions, runner_callback,
)
from arsia_ingest.manifest import (  # noqa: E402
    FrozenManifest, REQUIRED_CHECKS, freeze_manifest, read_json, s0_definitions,
)
from arsia_ingest.models import IntakeError  # noqa: E402
from arsia_ingest.pipeline import prepare  # noqa: E402
from arsia_ingest.raw_load import _PreparedRun  # noqa: E402
from arsia_ingest.runner import (  # noqa: E402
    BuildModules, ModuleBinding, ModuleConnection, RunContext, RunEvidence,
    _bindings, run_build,
)

COUNTS = {"dim_source": 3, "dim_month": 60, "dim_severity": 12}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(name, value):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / name).write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


@pytest.fixture(scope="session")
def definitions():
    return s0_definitions(B_ROOT / "tests/fixtures/s0/contract.json")


@pytest.fixture(scope="session")
def prepared():
    result = prepare(B_ROOT / "tests/fixtures/s0/config.json", EVIDENCE / "native-intake")
    assert result["status"] == "prepared"
    assert result["raw_count"] == 19
    return Path(result["run_dir"])


@pytest.fixture(scope="session")
def manifest(definitions, prepared):
    """Real FrozenManifest constructor; deliberately NOT a full B09 freeze.

    Only actual available code/schema bytes are indexed. No missing component
    is filled with a placeholder or another component's implementation.
    """
    run = _PreparedRun(prepared)
    run.check_files()
    code = [
        {"path": "D02/" + str(p.relative_to(D_ROOT)), "sha256": digest(p)}
        for p in sorted((D_ROOT / "src/arsia_d02").glob("*.py"))
    ] + [{"path": "D02/pyproject.toml", "sha256": digest(D_ROOT / "pyproject.toml")}]
    code += [{"path": "src/arsia_ingest/" + name, "sha256": digest(B_ROOT / "src/arsia_ingest" / name)}
             for name in ("manifest.py", "runner.py")]
    schema = [{"path": "sql/migrations/" + p.name, "sha256": digest(p)}
              for p in sorted((A_ROOT / "sql/migrations").glob("*.sql"))]
    value = {
        "contract_version": "team-v1.1", "dataset_kind": "synthetic",
        "analysis": definitions["analysis"], "sources": definitions["sources"],
        "files": run.files,
        "rules": {key: definitions[key] for key in ("contracts", "mappings", "severity")}
                 | {"qa_contract": read_json(B_ROOT / "config/qa-team-v1.1.json"),
                    "code_files": code, "schema_files": schema},
        "required_checks": list(REQUIRED_CHECKS),
        "provenance": {
            "prepared_at": run.run["finished_at"],
            "prepared_by": "D02 interface test only; incomplete platform inventory; no FP1/publication",
            "files": [
                {k: run.provenance[f["resource_id"]][k] for k in
                 ("resource_id", "file_sha256", "archive_relpath", "original_filename")}
                | {"download_url": None, "evidence_ref": "tests/fixtures/s0/contract.json"}
                for f in run.files
            ],
        },
    }
    frozen = FrozenManifest(json.dumps(value))
    assert type(frozen) is FrozenManifest
    write("typed-manifest-interface-only.json", frozen.as_dict())
    return frozen


@pytest.fixture
def connection():
    conn = psycopg.connect(os.environ["D02_LOADER_DSN"], autocommit=False)
    try:
        conn.execute("SET TIME ZONE 'UTC'")
        conn.execute("SET client_encoding TO 'UTF8'")
        yield conn
    finally:
        conn.rollback()
        conn.close()


def register(conn, definitions, *, sources=True, batch=None):
    batch = batch or str(uuid4())
    if sources:
        for source in definitions["sources"]:
            conn.execute("""INSERT INTO meta.source(source_id,jurisdiction_code,source_name,publisher)
                VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                         tuple(source[k] for k in ("source_id", "jurisdiction_code", "source_name", "publisher")))
    # This digest is a test identifier satisfying A's column format, NOT E's FP1.
    identity = hashlib.sha256(("D02 isolated test batch " + batch).encode()).hexdigest()
    conn.execute("""INSERT INTO meta.batch(batch_id,dataset_kind,input_fingerprint,manifest)
                 VALUES (%s,'synthetic',%s,%s)""",
                 (batch, identity, Jsonb({"purpose": "D02-only test; no FP1; no publication"})))
    return batch


def actual(conn, batch):
    result = {}
    for name, columns, order in (
        ("dim_source", "batch_id::text,source_id,source_name,jurisdiction_code,release_label,release_scope", "source_id"),
        ("dim_severity", "batch_id::text,source_id,severity_code,severity_label,definition_version,definition_text", "source_id,severity_code"),
    ):
        result[name] = sorted(conn.execute(f"SELECT {columns} FROM dw.{name} WHERE batch_id=%s ORDER BY {order}", (batch,)).fetchall())
    result["dim_month"] = conn.execute("SELECT month_id,calendar_year,calendar_month FROM dw.dim_month ORDER BY month_id").fetchall()
    return result


def expected(definitions, batch):
    # Independent field selection, not build_dimension_rows() used as the oracle.
    return {
        "dim_source": sorted([(batch,) + tuple(s[k] for k in
                               ("source_id", "source_name", "jurisdiction_code", "release_label", "release_scope"))
                              for s in definitions["sources"]], key=lambda x: x[1]),
        "dim_month": [(y * 100 + m, y, m) for y in range(2020, 2025) for m in range(1, 13)],
        "dim_severity": sorted([(batch,) + tuple(s[k] for k in
                                 ("source_id", "severity_code", "severity_label", "definition_version", "definition_text"))
                                for s in definitions["severity"]], key=lambda x: (x[1], x[2])),
    }


def test_server_loader_identity_and_011(connection):
    row = connection.execute("""SELECT current_user, session_user, current_setting('server_version_num'),
        current_setting('server_encoding'),current_setting('TimeZone'),
        rolsuper,rolcreatedb,rolcreaterole,rolbypassrls
        FROM pg_roles WHERE rolname=current_user""").fetchone()
    assert row[:2] == ("arsia_loader", "arsia_loader")
    assert 160000 <= int(row[2]) < 170000
    assert row[3:] == ("UTF8", "UTC", False, False, False, False)
    constraint = connection.execute("""SELECT pg_get_constraintdef(oid) FROM pg_constraint
        WHERE conrelid='canonical.crash'::regclass AND conname LIKE '%map%elig%'""").fetchone()[0]
    assert "location_crs IS NOT NULL" in constraint
    collation = connection.execute("SELECT datcollate,datctype FROM pg_database WHERE datname=current_database()").fetchone()
    write("environment.json", {"database_identity": row, "collation": collation, "map_constraint": constraint,
                              "python": sys.version, "psycopg": psycopg.__version__})


def test_postgres_and_python_collation_regression(connection, definitions):
    codes = ["F", "I", "N", "__MISSING__"]
    database_order = [r[0] for r in connection.execute(
        "SELECT code FROM unnest(%s::text[]) AS code ORDER BY code", (codes,))]
    batch = register(connection, definitions)
    assert load_dimensions(connection, batch, definitions) == COUNTS
    write("collation-regression.json", {"database_order": database_order, "python_order": sorted(codes),
          "ordering_differs": database_order != sorted(codes), "exact_content_load": "passed"})


def test_s0_exact_fields_complete_months_unused_categories_and_missing(connection, definitions):
    batch = register(connection, definitions)
    assert load_dimensions(connection, batch, definitions) == COUNTS
    rows = actual(connection, batch)
    assert rows == expected(definitions, batch)
    assert all({r[2] for r in rows["dim_severity"] if r[1] == s["source_id"]}
               == {"F", "I", "N", "__MISSING__"} for s in definitions["sources"])
    assert rows["dim_month"][0][0] == 202001 and rows["dim_month"][-1][0] == 202412
    assert connection.execute("SELECT count(*) FROM dw.fact_crash").fetchone() == (0,)
    write("s0-exact-rows.json", {"scope": "fixed S0 definitions; no facts/publication", "counts": COUNTS, "rows": rows})


def test_idempotent_repeated_call(connection, definitions):
    batch = register(connection, definitions)
    assert load_dimensions(connection, batch, definitions) == COUNTS
    before = actual(connection, batch)
    assert load_dimensions(connection, batch, definitions) == COUNTS
    assert actual(connection, batch) == before


@pytest.mark.parametrize("group,field", [
    ("sources", "source_name"), ("sources", "jurisdiction_code"),
    ("sources", "release_label"), ("sources", "release_scope"),
    ("severity", "severity_label"), ("severity", "definition_version"),
    ("severity", "definition_text"),
])
def test_same_key_changed_content_rejected(connection, definitions, group, field):
    batch = register(connection, definitions)
    load_dimensions(connection, batch, definitions)
    before = actual(connection, batch)
    changed = deepcopy(definitions)
    changed[group][0][field] += " changed"
    with pytest.raises(DimensionContractError) as error:
        load_dimensions(connection, batch, changed)
    assert error.value.code == "D02_DATABASE_MISMATCH"
    assert actual(connection, batch) == before


def test_extra_category_in_same_batch_rejected(connection, definitions):
    batch = register(connection, definitions)
    load_dimensions(connection, batch, definitions)
    connection.execute("""INSERT INTO dw.dim_severity VALUES (%s,'syn_nsw','X','Extra','syn-1','unexpected')""", (batch,))
    with pytest.raises(DimensionContractError) as error:
        load_dimensions(connection, batch, definitions)
    assert error.value.code == "D02_DATABASE_MISMATCH"


def test_batch_fk(connection, definitions):
    register(connection, definitions)
    with pytest.raises(psycopg.errors.ForeignKeyViolation) as error:
        load_dimensions(connection, str(uuid4()), definitions)
    assert error.value.diag.constraint_name == "dim_source_batch_fk"


def test_source_fk(connection, definitions):
    value = deepcopy(definitions)
    old = value["sources"][0]["source_id"]
    value["sources"][0]["source_id"] = "syn_absent_" + uuid4().hex
    for severity in value["severity"]:
        if severity["source_id"] == old:
            severity["source_id"] = value["sources"][0]["source_id"]
    batch = register(connection, value, sources=False)
    with pytest.raises(psycopg.errors.ForeignKeyViolation) as error:
        load_dimensions(connection, batch, value)
    assert error.value.diag.constraint_name == "dim_source_source_fk"


def test_severity_composite_fk(connection, definitions):
    batch = register(connection, definitions)
    with pytest.raises(psycopg.errors.ForeignKeyViolation) as error:
        connection.execute("INSERT INTO dw.dim_severity VALUES (%s,'syn_nsw','F','Fatal','syn-1','test')", (batch,))
    assert error.value.diag.constraint_name == "dim_severity_source_fk"


@pytest.mark.parametrize("statement", [
    "UPDATE dw.dim_source SET source_name='forbidden'",
    "UPDATE dw.dim_severity SET severity_label='forbidden'",
    "UPDATE dw.dim_month SET calendar_year=0",
    "DELETE FROM dw.dim_source", "TRUNCATE dw.dim_month",
    "CREATE TABLE dw.forbidden(value integer)", "SET ROLE arsia_migrator",
])
def test_actual_permission_denials(connection, statement):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        connection.execute(statement)


def test_caller_rollback_removes_all_new_writes(connection, definitions):
    batch = register(connection, definitions)
    load_dimensions(connection, batch, definitions)
    assert connection.closed is False and connection.autocommit is False
    # A separate real session cannot see uncommitted data from this module.
    with psycopg.connect(os.environ["D02_LOADER_DSN"]) as observer:
        assert observer.execute("SELECT count(*) FROM dw.dim_source WHERE batch_id=%s", (batch,)).fetchone() == (0,)
        assert observer.execute("SELECT count(*) FROM dw.dim_month").fetchone() == (0,)
    connection.rollback()
    assert actual(connection, batch) == {"dim_source": [], "dim_severity": [], "dim_month": []}
    assert connection.execute("SELECT count(*) FROM meta.batch WHERE batch_id=%s", (batch,)).fetchone() == (0,)


def test_new_batch_keeps_old_source_and_severity_definitions(connection, definitions):
    first = register(connection, definitions)
    load_dimensions(connection, first, definitions)
    before = actual(connection, first)
    changed = deepcopy(definitions)
    for source in changed["sources"]:
        source["source_name"] += " revised"
        source["release_label"] += " revision 2"
    for severity in changed["severity"]:
        severity["definition_version"] = "syn-2"
        severity["definition_text"] += " Revised test-only definition."
    second = register(connection, changed)
    load_dimensions(connection, second, changed)
    assert actual(connection, first) == before
    assert actual(connection, second) == expected(changed, second)
    assert connection.execute("SELECT count(*) FROM dw.dim_source").fetchone() == (6,)
    assert connection.execute("SELECT count(*) FROM dw.dim_severity").fetchone() == (24,)
    assert connection.execute("SELECT count(*) FROM dw.dim_month").fetchone() == (60,)


def test_committed_batches_preserve_history_across_sessions(connection, definitions):
    batches = []
    try:
        first = register(connection, definitions)
        batches.append(first)
        load_dimensions(connection, first, definitions)
        connection.commit()  # Only the test caller commits, never D02.
        changed = deepcopy(definitions)
        changed["sources"][0]["source_name"] += " revision 2"
        changed["severity"][0]["definition_text"] += " revision 2"
        second = register(connection, changed)
        batches.append(second)
        load_dimensions(connection, second, changed)
        connection.commit()
        with psycopg.connect(os.environ["D02_LOADER_DSN"]) as observer:
            assert actual(observer, first) == expected(definitions, first)
            assert actual(observer, second) == expected(changed, second)
        write("committed-history.json", {"batches": batches, "old_snapshot_unchanged": True,
              "new_snapshot_verified": True, "publication_performed": False})
    finally:
        connection.rollback()
        # Admin cleanup belongs only to this isolated test harness. Loader grants
        # remain unchanged; the preceding permission tests reject loader DELETE.
        with psycopg.connect(os.environ["D02_ADMIN_DSN"]) as admin:
            for batch in batches:
                admin.execute("DELETE FROM dw.dim_severity WHERE batch_id=%s", (batch,))
                admin.execute("DELETE FROM dw.dim_source WHERE batch_id=%s", (batch,))
                admin.execute("DELETE FROM meta.batch WHERE batch_id=%s", (batch,))
            admin.execute("DELETE FROM dw.dim_month")
            for source in definitions["sources"]:
                admin.execute("DELETE FROM meta.source WHERE source_id=%s", (source["source_id"],))


def test_real_frozen_manifest_and_real_b10_context_evidence(connection, definitions, manifest):
    batch = register(connection, definitions)
    context = RunContext(str(uuid4()), "synthetic", batch,
                         hashlib.sha256(b"test context identifier; not FP1").hexdigest(), None,
                         manifest, RunEvidence(EVIDENCE / "callback"))
    shared = ModuleConnection(connection)
    assert not hasattr(shared, "commit") and not hasattr(shared, "rollback") and not hasattr(shared, "close")
    assert runner_callback(shared, context) == COUNTS
    assert actual(connection, batch) == expected(definitions, batch)
    path = context.evidence.directory / "d02-dimensions.json"
    assert json.loads(path.read_text()) == {"batch_id": batch, "counts": COUNTS}
    ref = context.evidence.write_json("evidence-reference.json", {"path": path.name, "sha256": digest(path)})
    assert ref["sha256"] == digest(context.evidence.directory / "evidence-reference.json")
    assert ref["row_count"] == 1
    before = manifest.as_dict()
    detached = manifest.as_dict()
    detached["sources"][0]["source_name"] = "mutation must not escape"
    assert manifest.as_dict() == before
    connection.rollback()
    assert actual(connection, batch) == {"dim_source": [], "dim_severity": [], "dim_month": []}
    write("callback-interface-result.json", {"manifest_class": type(manifest).__module__ + "." + type(manifest).__name__,
          "context_class": type(context).__module__ + "." + type(context).__name__,
          "connection_class": type(shared).__module__ + "." + type(shared).__name__,
          "counts": COUNTS, "evidence_sha256": digest(path), "reference": ref,
          "rollback_verified": True, "complete_b10_build": False})


def test_callback_translates_contract_conflict_to_b_intake_error(connection, definitions, manifest, tmp_path):
    batch = register(connection, definitions)
    changed = deepcopy(definitions)
    changed["sources"][0]["source_name"] += " conflicting existing row"
    load_dimensions(connection, batch, changed)
    context = RunContext(str(uuid4()), "synthetic", batch, "test-only-not-fp1", None,
                         manifest, RunEvidence(tmp_path))
    with pytest.raises(IntakeError) as error:
        runner_callback(ModuleConnection(connection), context)
    assert error.value.code == "D02_DATABASE_MISMATCH"
    assert not (tmp_path / "d02-dimensions.json").exists()


def partial_inventory():
    return {"components": {"dw": ["D02/src/arsia_d02/dimensions.py", "D02/src/arsia_d02/__init__.py", "D02/pyproject.toml"]},
            "schema_files": ["sql/migrations/" + p.name for p in sorted((A_ROOT / "sql/migrations").glob("*.sql"))]}


def test_full_freeze_refuses_incomplete_platform_inventory(manifest):
    with pytest.raises(IntakeError) as error:
        freeze_manifest(manifest.as_dict(), project_root=D_ROOT.parent, inventory=partial_inventory())
    assert error.value.code == "MANIFEST_VERSION_MISSING"
    write("full-freeze-dependency.json", {"status": "blocked_as_expected", "error_code": error.value.code,
          "details": error.value.details, "available_inventory_scope": "D02-only fragment"})


def test_real_b10_build_stops_in_preflight_without_fake_dependencies(manifest, prepared):
    connects = []
    def connect():
        connects.append(True)
        return psycopg.connect(os.environ["D02_LOADER_DSN"])
    modules = BuildModules(dw=ModuleBinding(runner_callback, "D02/src/arsia_d02/dimensions.py", "0.1.0"))
    result = run_build(connect=connect, prepared_run=prepared, manifest=manifest,
                       project_root=D_ROOT.parent, inventory=partial_inventory(), modules=modules,
                       evidence_root=EVIDENCE / "full-build-preflight", fp1=None)
    value = result.as_dict()
    assert result.exit_code == 1 and value["result"] == "failed"
    assert not connects
    write("full-build-preflight-result.json", value)
    with pytest.raises(IntakeError) as error:
        _bindings(modules, None, partial_inventory())
    assert error.value.code == "MODULE_UNAVAILABLE"
    assert set(error.value.details["modules"]) == {"project", "vault", "canonical", "qa_c", "qa_d", "publish"}
    write("missing-bindings.json", {"error_code": error.value.code, "details": error.value.details,
                                   "fp1": "unavailable; not substituted", "dw": "D02 only; D03 required"})
