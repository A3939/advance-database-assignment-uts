"""C09 adversarial and shared-session checks against A02/011 and real A06."""

from copy import deepcopy
import json
from uuid import uuid4
from pathlib import Path
import importlib.util

import pytest

from test_c09_postgres import C09Case, FakeContext, connection, pytestmark
from arsia_ingest.models import IntakeError
from arsia_ingest.runner import ModuleConnection
from arsia_ingest.vault_load import load_vault
from arsia_c.canonical import load_canonical
from arsia_c.canonical_validation import reconcile


def run(case):
    load_canonical(ModuleConnection(case.connection), case.context)


def vault(case):
    load_vault(ModuleConnection(case.connection), case.context)


def direct_satellites(case, *, crash_change=None, unit_change=None, link=True):
    """Fault-injection fixture: deliberately bypass A06, without changing old rows."""
    conn = case.connection
    for kind in ("crash", "unit"):
        conn.execute(
            f"INSERT INTO rv.hub_{kind}(source_id,release_scope,{kind}_key,first_seen_batch_id) SELECT source_id,release_scope,{kind}_key,batch_id FROM pg_temp.arsia_i_{kind}"
        )
        attributes = conn.execute(
            f"SELECT to_jsonb(p)-ARRAY['batch_id','source_id','release_scope','{kind}_key','raw_record_id'] FROM pg_temp.arsia_i_{kind} p"
        ).fetchone()[0]
        change = crash_change if kind == "crash" else unit_change
        if change:
            attributes.update(change)
        conn.execute(
            f"INSERT INTO rv.sat_{kind} SELECT batch_id,source_id,release_scope,{kind}_key,raw_record_id,%s::jsonb FROM pg_temp.arsia_i_{kind}",
            (json.dumps(attributes),),
        )
    if link:
        conn.execute(
            "INSERT INTO rv.link_crash_unit SELECT batch_id,source_id,release_scope,unit_key,crash_key FROM pg_temp.arsia_i_unit"
        )


@pytest.mark.parametrize(
    "part", ["file_sha256", "parser_version", "source_id", "release_scope"]
)
def test_rejects_satellite_outside_frozen_selection(connection, part):
    case = C09Case(connection)
    vault(case)
    value = case.context.manifest._value
    if part in {"file_sha256", "parser_version"}:
        replacement = "f" * 64 if part == "file_sha256" else "unselected-parser"
        value["files"][0][part] = replacement
        value["rules"]["contracts"][0]["content"]["input"][part] = replacement
    elif part == "release_scope":
        value["sources"][0][part] = "another-release"
        for contract in value["rules"]["contracts"]:
            contract["content"]["identity"][part] = "another-release"
    else:
        value["sources"][0][part] = "another-source"
    with pytest.raises(IntakeError):
        run(case)
    assert (
        connection.execute(
            "SELECT count(*) FROM canonical.crash WHERE batch_id=%s", (case.batch_id,)
        ).fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("entity", ["crash", "unit"])
def test_rejects_raw_key_from_another_entity(connection, entity):
    case = C09Case(connection)
    # Typed rows have a valid full shape, but the primary Raw row has another key.
    column = "crash_key" if entity == "crash" else "unit_key"
    connection.execute(
        f"UPDATE pg_temp.arsia_i_{entity} SET {column}=%s", ('["WRONG"]',)
    )
    if entity == "crash":
        connection.execute(
            "UPDATE pg_temp.arsia_i_unit SET crash_key=%s", ('["WRONG"]',)
        )
    vault(case)
    with pytest.raises(IntakeError, match="Satellite identity"):
        run(case)


def test_missing_link_is_not_silently_filtered_out(connection):
    case = C09Case(connection)
    direct_satellites(case, link=False)
    with pytest.raises(IntakeError, match="parent is invalid"):
        run(case)


def test_attribute_parent_must_match_link(connection):
    case = C09Case(connection)
    direct_satellites(case, unit_change={"crash_key": '["different"]'})
    with pytest.raises(IntakeError, match="parent is invalid"):
        run(case)


def add_location(
    case, *, crash_id="000123", node_id="NODE01", selected=True, kind="node_raw"
):
    conn = case.connection
    rid = case.source_id + "_location"
    raw_id = uuid4()
    conn.execute(
        "INSERT INTO meta.resource VALUES (%s,%s,%s,%s)",
        (rid, case.source_id, "node" if kind == "node_raw" else "crash", kind),
    )
    conn.execute(
        "INSERT INTO raw.record(raw_record_id,resource_id,source_id,file_sha256,parser_version,row_locator,payload) VALUES (%s,%s,%s,%s,%s,'csv:2',%s::jsonb)",
        (
            raw_id,
            rid,
            case.source_id,
            "d" * 64,
            case.parser_version,
            json.dumps({"Crash ID": crash_id, "NODE_ID": node_id}),
        ),
    )
    if selected:
        value = case.context.manifest._value
        file = {
            "source_id": case.source_id,
            "resource_id": rid,
            "file_sha256": "d" * 64,
            "parser_version": case.parser_version,
            "entity_kind": kind,
        }
        value["files"].append(file)
        value["rules"]["contracts"].append(
            {
                "id": rid,
                "status": "synthetic_defined",
                "content": {
                    "input": dict(file),
                    "identity": {
                        "release_scope": case.release_scope,
                        "key": {"fields": ["Crash ID", "NODE_ID"]},
                        "parent": (
                            {
                                "resource_id": case.crash_resource_id,
                                "fields": ["Crash ID", "NODE_ID"],
                                "parent_fields": ["Crash ID", "NODE_ID"],
                            }
                            if kind == "node_raw"
                            else None
                        ),
                    },
                },
            }
        )
    conn.execute(
        "UPDATE pg_temp.arsia_i_crash SET latitude=-37.8,longitude=144.9,location_crs='EPSG:4326',map_eligible=true,location_record_id=%s,quality_notes='{}'",
        (raw_id,),
    )
    return raw_id


class NodeCase(C09Case):
    def _insert_raw_rows(self):
        # Same native ID contract; this variant explicitly carries a Node join key.
        for raw_id, rid, sha, locator, payload in [
            (
                self.crash_raw_id,
                self.crash_resource_id,
                self.crash_sha,
                "crash:1",
                {"Crash ID": "000123", "NODE_ID": "NODE01"},
            ),
            (
                self.unit_raw_id,
                self.unit_resource_id,
                self.unit_sha,
                "unit:1",
                {"Crash ID": "000123", "Traffic unit ID": "01"},
            ),
        ]:
            self.connection.execute(
                "INSERT INTO raw.record(raw_record_id,resource_id,source_id,file_sha256,parser_version,row_locator,payload) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)",
                (
                    raw_id,
                    rid,
                    self.source_id,
                    sha,
                    self.parser_version,
                    locator,
                    json.dumps(payload),
                ),
            )


@pytest.mark.parametrize(
    "crash_id,node_id", [("other", "NODE01"), ("000123", "other"), ("000123", None)]
)
def test_rejects_wrong_accident_or_node_even_in_selected_file(
    connection, crash_id, node_id
):
    case = NodeCase(connection)
    add_location(case, crash_id=crash_id, node_id=node_id)
    vault(case)  # A06 verifies file membership, not this native relationship.
    with pytest.raises(IntakeError, match="exact Node"):
        run(case)


def test_valid_selected_node_preserves_location_lineage(connection):
    case = NodeCase(connection)
    raw_id = add_location(case)
    vault(case)
    run(case)
    assert connection.execute(
        "SELECT location_record_id,latitude::text,longitude::text FROM canonical.crash WHERE batch_id=%s",
        (case.batch_id,),
    ).fetchone() == (raw_id, "-37.8000000", "144.9000000")


def test_direct_location_must_be_the_same_crash_raw_row(connection):
    case = NodeCase(connection)
    add_location(case, kind="crash")
    vault(case)
    with pytest.raises(IntakeError, match="selected crash"):
        run(case)


def test_rejects_unselected_location_file(connection):
    case = NodeCase(connection)
    add_location(case, selected=False)
    direct_satellites(case)
    with pytest.raises(IntakeError, match="Location lineage"):
        run(case)


def test_shared_transaction_rolls_back_partial_canonical_and_vault(connection):
    with pytest.raises(IntakeError, match="structured"):
        with connection.transaction():
            case = C09Case(connection)
            direct_satellites(
                case,
                unit_change={
                    "quality_notes": {"fields": [{"field": "unit_type_code"}]}
                },
            )
            run(case)  # Crashes have been inserted before the unit fails.
    for table in (
        "raw.record",
        "rv.sat_crash",
        "rv.sat_unit",
        "canonical.crash",
        "canonical.unit",
        "meta.batch",
    ):
        assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_retry_rejects_existing_rows_and_keeps_successful_history(connection):
    case = C09Case(connection)
    vault(case)
    run(case)
    previous = connection.execute(
        "SELECT to_jsonb(c) FROM canonical.crash c WHERE batch_id=%s", (case.batch_id,)
    ).fetchall()
    with pytest.raises(IntakeError, match="already contains"):
        run(case)
    connection.execute(
        "UPDATE meta.batch SET status='succeeded',finished_at=now() WHERE batch_id=%s",
        (case.batch_id,),
    )
    with pytest.raises(IntakeError, match="running candidate"):
        run(case)
    old = case.batch_id
    case.batch_id = uuid4()
    connection.execute(
        "INSERT INTO meta.batch(batch_id,dataset_kind,input_fingerprint,manifest,status) VALUES (%s,'synthetic',%s,'{}','running')",
        (case.batch_id, "d" * 64),
    )
    for kind in ("crash", "unit"):
        connection.execute(
            f"UPDATE pg_temp.arsia_i_{kind} SET batch_id=%s", (case.batch_id,)
        )
    case.context.batch_id = case.batch_id
    vault(case)
    run(case)
    assert (
        connection.execute(
            "SELECT to_jsonb(c) FROM canonical.crash c WHERE batch_id=%s", (old,)
        ).fetchall()
        == previous
    )
    assert connection.execute("SELECT count(*) FROM canonical.crash").fetchone()[0] == 2
    connection.rollback()
    assert connection.execute("SELECT count(*) FROM canonical.crash").fetchone()[0] == 0


def test_reconciliation_detects_missing_persisted_rows(connection):
    case = C09Case(connection)
    vault(case)
    with pytest.raises(IntakeError, match="differ from selected"):
        reconcile(ModuleConnection(connection), case.context)


def test_actual_b08_c03_a06_c09_pipeline(connection, tmp_path):
    from test_c03_nsw_projection import component_manifest
    from arsia_ingest.pipeline import prepare
    from arsia_ingest.raw_load import load_prepared
    from arsia_c.projections.nsw import project

    root = Path(__file__).resolve().parents[1]
    manifest = component_manifest()
    prepared = prepare(root / "tests/fixtures/s0/config.json", tmp_path / "intake")
    assert prepared["status"] == "prepared"
    loaded = load_prepared(connection, prepared["run_dir"], manifest["sources"])
    assert loaded.raw_count == 19
    before = connection.execute(
        "SELECT raw_record_id,payload FROM raw.record ORDER BY raw_record_id"
    ).fetchall()
    batch = uuid4()
    context = FakeContext(batch, manifest)
    connection.execute(
        "INSERT INTO meta.batch(batch_id,dataset_kind,input_fingerprint,manifest) VALUES (%s,'synthetic',%s,%s::jsonb)",
        (batch, "e" * 64, json.dumps(manifest)),
    )
    shared = ModuleConnection(connection)
    project(shared, context)
    load_vault(shared, context)
    load_canonical(shared, context)
    assert connection.execute(
        "SELECT count(*),sum(fatality_count),sum(casualty_count),count(*) FILTER(WHERE map_eligible) FROM canonical.crash WHERE batch_id=%s",
        (batch,),
    ).fetchone() == (2, 2, 3, 1)
    assert (
        connection.execute(
            "SELECT count(*) FROM canonical.unit WHERE batch_id=%s", (batch,)
        ).fetchone()[0]
        == 3
    )
    assert (
        connection.execute(
            "SELECT raw_record_id,payload FROM raw.record ORDER BY raw_record_id"
        ).fetchall()
        == before
    )
    assert (
        context.evidence.files["c09-canonical-counts.json"]["satellite_reconciled"]
        is True
    )
    connection.rollback()
    assert connection.execute("SELECT count(*) FROM canonical.crash").fetchone()[0] == 0


def test_three_state_c01_snapshot_through_real_b08_a06_c09(connection, tmp_path):
    """C01 expected projections test this boundary; C04/C05 are not claimed executed."""
    from test_c03_nsw_projection import component_manifest
    from test_c09_postgres import CRASH_TABLE_SQL, UNIT_TABLE_SQL
    from arsia_ingest.pipeline import prepare
    from arsia_ingest.raw_load import load_prepared
    from psycopg.types.json import Jsonb
    import re

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "c09_c01_examples", root / "tests/fixtures/c01/c01_projection.py"
    )
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    manifest = component_manifest()
    batch = uuid4()
    context = FakeContext(batch, manifest)
    prepared = prepare(root / "tests/fixtures/s0/config.json", tmp_path / "intake")
    loaded = load_prepared(connection, prepared["run_dir"], manifest["sources"])
    assert loaded.raw_count == 19
    ids = {}
    for resource, base in [
        ("syn_nsw_crash", 1000),
        ("syn_nsw_traffic_unit", 2000),
        ("syn_vic_accident", 3000),
        ("syn_vic_vehicle", 4000),
        ("syn_vic_node", 6000),
        ("syn_qld_crash", 7000),
    ]:
        rows = connection.execute(
            "SELECT raw_record_id,row_locator FROM raw.record WHERE resource_id=%s",
            (resource,),
        ).fetchall()
        for index, (raw_id, _) in enumerate(
            sorted(rows, key=lambda r: int(re.findall(r"\d+", r[1])[-1])), 1
        ):
            ids[str(fixture._raw(base + index))] = str(raw_id)

    def substitute(value):
        if isinstance(value, dict):
            return {k: substitute(v) for k, v in value.items()}
        if isinstance(value, list):
            return [substitute(v) for v in value]
        if isinstance(value, str):
            return ids.get(value, value)
        return value

    connection.execute(
        "INSERT INTO meta.batch(batch_id,dataset_kind,input_fingerprint,manifest) VALUES (%s,'synthetic',%s,%s::jsonb)",
        (batch, "f" * 64, json.dumps(manifest)),
    )
    connection.execute(CRASH_TABLE_SQL)
    connection.execute(UNIT_TABLE_SQL)
    for kind, fields, rows in [
        ("crash", fixture.CRASH_FIELDS, fixture.S0_CRASHES.values()),
        ("unit", fixture.UNIT_FIELDS, fixture.S0_UNITS),
    ]:
        for example in rows:
            row = deepcopy(example)
            row["batch_id"] = batch
            row["raw_record_id"] = ids[str(row["raw_record_id"])]
            if row.get("location_record_id") is not None:
                row["location_record_id"] = ids[str(row["location_record_id"])]
            for key in ("crash_key", "unit_key"):
                if key in row:
                    row[key] = connection.execute(
                        "SELECT rv.encode_business_key(VARIADIC %s::text[])",
                        (json.loads(row[key]),),
                    ).fetchone()[0]
            row["quality_notes"] = Jsonb(substitute(row["quality_notes"]))
            connection.execute(
                f"INSERT INTO pg_temp.arsia_i_{kind} ({','.join(fields)}) VALUES ({','.join(['%s']*len(fields))})",
                tuple(row[k] for k in fields),
            )
    shared = ModuleConnection(connection)
    load_vault(shared, context)
    load_canonical(shared, context)
    for kind in ("crash", "unit"):
        assert (
            connection.execute(
                f"SELECT to_jsonb(c) FROM canonical.{kind} c WHERE batch_id=%s ORDER BY source_id,{kind}_key",
                (batch,),
            ).fetchall()
            == connection.execute(
                f"SELECT to_jsonb(p) FROM pg_temp.arsia_i_{kind} p ORDER BY source_id,{kind}_key"
            ).fetchall()
        )
    assert connection.execute(
        "SELECT count(*),sum(fatality_count),sum(casualty_count),count(*) FILTER(WHERE map_eligible) FROM canonical.crash"
    ).fetchone() == (6, 3, 7, 4)
    assert (
        connection.execute(
            "SELECT count(*) FROM canonical.unit WHERE source_id='syn_qld'"
        ).fetchone()[0]
        == 0
    )
    assert connection.execute("SELECT count(*) FROM raw.record").fetchone()[0] == 19


def test_reads_satellites_even_when_projection_changes_after_vault(connection):
    case = C09Case(connection)
    vault(case)
    connection.execute("UPDATE pg_temp.arsia_i_crash SET fatality_count=999")
    run(case)
    assert (
        connection.execute(
            "SELECT fatality_count FROM canonical.crash WHERE batch_id=%s",
            (case.batch_id,),
        ).fetchone()[0]
        == 1
    )


@pytest.mark.parametrize("bad", ["draft", "missing", "duplicate"])
def test_rejects_missing_or_ambiguous_contracts(connection, bad):
    case = C09Case(connection)
    vault(case)
    contracts = case.context.manifest._value["rules"]["contracts"]
    if bad == "draft":
        contracts[0]["status"] = "draft"
    elif bad == "missing":
        contracts.pop(0)
    else:
        contracts.append(deepcopy(contracts[0]))
    with pytest.raises(IntakeError):
        run(case)


def test_more_than_one_insert_chunk_preserves_every_row(connection):
    case = C09Case(connection)
    # Extra crashes use real distinct Raw IDs and SQL-encoded native keys.
    connection.execute(
        """WITH added AS (
      INSERT INTO raw.record(raw_record_id,resource_id,source_id,file_sha256,parser_version,row_locator,payload)
      SELECT gen_random_uuid(),%s,%s,%s,%s,'chunk:'||i,jsonb_build_object('Crash ID','bulk-'||i)
      FROM generate_series(1,1001) i RETURNING raw_record_id,payload)
      INSERT INTO pg_temp.arsia_i_crash
      SELECT p.batch_id,p.source_id,p.release_scope,rv.encode_business_key(a.payload->>'Crash ID'),a.raw_record_id,
        p.occurrence_year,p.occurrence_month,p.occurrence_date,p.date_precision,p.severity_raw,p.severity_code,
        p.severity_definition_version,p.is_fatal_crash,p.fatality_count,p.casualty_count,p.fatal_crash_eligible,
        p.fatality_eligible,p.casualty_eligible,p.latitude,p.longitude,p.location_crs,p.map_eligible,p.location_record_id,p.quality_notes
      FROM added a CROSS JOIN pg_temp.arsia_i_crash p""",
        (case.crash_resource_id, case.source_id, case.crash_sha, case.parser_version),
    )
    vault(case)
    run(case)
    assert (
        connection.execute(
            "SELECT count(*) FROM canonical.crash WHERE batch_id=%s", (case.batch_id,)
        ).fetchone()[0]
        == 1002
    )
    assert (
        case.context.evidence.files["c09-canonical-counts.json"]["crash_count"] == 1002
    )
