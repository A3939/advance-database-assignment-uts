"""C10 on B's installed component chain and A's unchanged loader role."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path

import pytest

if "ARSIA_TEST_DSN" not in os.environ:
    pytest.skip(
        "Run tools/verify_c10_postgres.py in its private database",
        allow_module_level=True,
    )

from arsia_c import qa
from arsia_ingest.manifest import FrozenManifest
from arsia_ingest.models import IntakeError
from arsia_ingest.runner import ModuleBinding, ModuleConnection
from test_cd_integration_postgres import prepared, canonical, call
from test_ac_integration_postgres import begin, counts, TABLES
from test_raw_load_postgres import connection


@pytest.fixture
def frozen(prepared):
    from cd_support import ROOT, interface_manifest

    value = interface_manifest(prepared[0]).as_dict()
    declared = {entry["path"]: entry for entry in value["rules"]["code_files"]}
    fragment = json.loads((ROOT / "config/c10-inventory.json").read_text())
    for entry in fragment["code_files"]:
        assert (
            hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest()
            == entry["sha256"]
        )
        declared[entry["path"]] = entry
    value["rules"]["code_files"] = list(declared.values())
    return FrozenManifest(json.dumps(value))


@pytest.fixture(autouse=True)
def isolated(connection):
    assert connection.execute(
        "SELECT current_user,session_user,current_setting('arsia.test_run',true)"
    ).fetchone() == ("arsia_loader", "arsia_loader", os.environ["AC_TEST_RUN"])
    assert not any(counts(connection).values())
    connection.rollback()


def chain(connection, prepared, frozen):
    context = begin(connection, prepared, frozen)
    canonical(connection, context)
    call(connection, context, "dw")
    return replace(context, evidence=context.evidence.for_stage("qa_c"))


def results(connection, context):
    return connection.execute(
        "SELECT rule_id,object_key,result,affected_count,actual,expected,evidence FROM qa.check_result WHERE batch_id=%s ORDER BY rule_id,object_key",
        (context.batch_id,),
    ).fetchall()


def test_installed_s0_callback_evidence_and_rollback(connection, prepared, frozen):
    assert type(frozen) is FrozenManifest
    assert Path(qa.__file__).resolve().is_relative_to(Path(__import__("sys").prefix))
    context = chain(connection, prepared, frozen)
    binding = ModuleBinding(
        qa.runner_callback, "src/arsia_c/qa.py", qa.PRODUCER_VERSION
    )
    assert binding.code_path in {
        e["path"] for e in frozen.as_dict()["rules"]["code_files"]
    }
    try:
        outcome = binding.callback(ModuleConnection(connection), context)
    except IntakeError:
        print(json.dumps(results(connection, context), default=str, indent=2))
        raise
    assert outcome == {
        "c10_object_count": 27,
        "c10_summary_count": 4,
        "limited_count": 2,
    }
    rows = results(connection, context)
    assert len(rows) == 31
    concrete = [r for r in rows if r[1] != "batch"]
    assert {r[0] for r in concrete} == set(qa.RULES)
    assert sum(r[2] == "limited" for r in concrete) == 2
    assert all(r[2] == "pass" for r in concrete if r[0] != "QA07_LOCATION")
    location = [r for r in concrete if r[0] == "QA07_LOCATION"]
    assert (
        len(location) == 15
        and sum(r[4]["evaluated_count"] == 0 for r in location) == 10
    )
    for rule, key, state, affected, actual, expected, evidence in concrete:
        assert actual["violation_count"] == 0
        assert actual["evaluated_count"] == expected["evaluated_count"]
        assert all(
            w is None or actual["metrics"][k] == w
            for k, w in expected["metrics"].items()
        )
        assert evidence["references"] and evidence["producer_version"]
        for ref in evidence["references"]:
            if "path" in ref:
                p = Path(ref["path"])
                assert hashlib.sha256(p.read_bytes()).hexdigest() == ref["sha256"]
    assert connection.execute(
        "SELECT count(*) FROM meta.current_release"
    ).fetchone() == (0,)
    with pytest.raises(IntakeError, match="C10 results already exist"):
        qa.runner_callback(ModuleConnection(connection), context)
    connection.rollback()
    assert counts(connection) == dict.fromkeys(TABLES, 0)


FAULTS = [
    (
        "missing_projection",
        "DELETE FROM pg_temp.arsia_i_crash WHERE source_id='syn_qld' AND occurrence_year=2021",
        "QA03_PROJECTED",
    ),
    (
        "wrong_projection_count",
        "UPDATE pg_temp.arsia_i_crash SET fatality_count=7 WHERE source_id='syn_qld' AND occurrence_year=2020",
        "QA03_PROJECTED",
    ),
    (
        "incomplete_raw",
        "UPDATE raw.record SET file_sha256=repeat('0',64) WHERE resource_id='syn_qld_crash' AND row_locator='csv:2'",
        "QA03_PROJECTED",
    ),
    (
        "native_field_missing",
        "UPDATE raw.record SET payload=payload-'Crash_Month' WHERE resource_id='syn_qld_crash' AND row_locator='csv:2'",
        "QA03_PROJECTED",
    ),
    (
        "undefined_severity",
        "UPDATE raw.record SET payload=jsonb_set(payload,'{Crash_Severity}','\"new severity\"') WHERE resource_id='syn_qld_crash' AND row_locator='csv:2'",
        "QA05_SEMANTICS",
    ),
    (
        "negative_count",
        "UPDATE raw.record SET payload=jsonb_set(payload,'{Count_Casualty_Fatality}','\"-1\"') WHERE resource_id='syn_qld_crash' AND row_locator='csv:2'",
        "QA03_PROJECTED",
    ),
    (
        "vehicle_orphan",
        "UPDATE raw.record SET payload=jsonb_set(payload,'{ACCIDENT_NO}','\"unknown\"') WHERE resource_id='syn_vic_vehicle' AND row_locator='csv:2'",
        "QA04_AUXILIARY",
    ),
    (
        "node_orphan",
        "UPDATE raw.record SET payload=jsonb_set(payload,'{ACCIDENT_NO}','\"unknown\"') WHERE resource_id='syn_vic_node' AND row_locator='csv:2'",
        "QA04_AUXILIARY",
    ),
    (
        "person_vehicle_unmatched",
        "UPDATE raw.record SET payload=jsonb_set(payload,'{VEHICLE_ID}','\"unknown\"') WHERE resource_id='syn_vic_person' AND row_locator='csv:2'",
        "QA04_AUXILIARY",
    ),
    (
        "declared_person_mismatch",
        "UPDATE raw.record SET payload=jsonb_set(payload,'{NO_PERSONS}','\"99\"') WHERE resource_id='syn_vic_accident' AND row_locator='csv:2'",
        "QA04_AUXILIARY",
    ),
    (
        "declared_vehicle_mismatch",
        "UPDATE raw.record SET payload=jsonb_set(payload,'{NO_OF_VEHICLES}','\"99\"') WHERE resource_id='syn_vic_accident' AND row_locator='csv:2'",
        "QA04_AUXILIARY",
    ),
    (
        "canonical_semantics",
        "UPDATE canonical.unit SET unit_type_code='wrong' WHERE source_id='syn_vic'",
        "QA05_SEMANTICS",
    ),
    (
        "missing_fact",
        "DELETE FROM dw.fact_crash WHERE source_id='syn_qld' AND occurrence_year=2021",
        "QA07_LOCATION",
    ),
    (
        "wrong_fact_coordinates",
        "UPDATE dw.fact_crash SET latitude=latitude+1 WHERE source_id='syn_qld'",
        "QA07_LOCATION",
    ),
    (
        "wrong_node_lineage",
        "UPDATE canonical.crash SET location_record_id=(SELECT raw_record_id FROM raw.record WHERE resource_id='syn_vic_node' ORDER BY row_locator DESC LIMIT 1) WHERE source_id='syn_vic' AND map_eligible",
        "QA07_LOCATION",
    ),
    (
        "missing_location_reason",
        "UPDATE canonical.crash SET quality_notes=quality_notes-'location' WHERE NOT map_eligible",
        "QA07_LOCATION",
    ),
    (
        "missing_null_reason",
        "UPDATE canonical.crash SET quality_notes=jsonb_set(quality_notes,'{fields}','[]') WHERE NOT fatal_crash_eligible",
        "QA05_SEMANTICS",
    ),
    (
        "wrong_native_year",
        "UPDATE raw.record SET payload=jsonb_set(payload,'{Crash_Year}','\"2019\"') WHERE resource_id='syn_qld_crash' AND row_locator='csv:2'",
        "QA07_LOCATION",
    ),
]

FAULTS += [
    (
        "nsw_declared_units",
        "UPDATE raw.record SET payload=jsonb_set(payload,'{No. of traffic units involved}','\"99\"') WHERE resource_id='syn_nsw_crash'",
        "QA04_AUXILIARY",
    ),
    (
        "missing_declared_people",
        "UPDATE raw.record SET payload=jsonb_set(payload,'{NO_PERSONS}','\"\"') WHERE resource_id='syn_vic_accident'",
        "QA04_AUXILIARY",
    ),
    (
        "missing_declared_units",
        "UPDATE raw.record SET payload=jsonb_set(payload,'{NO_OF_VEHICLES}','\"\"') WHERE resource_id='syn_vic_accident'",
        "QA04_AUXILIARY",
    ),
    (
        "duplicate_projected_crash",
        "INSERT INTO pg_temp.arsia_i_crash SELECT * FROM pg_temp.arsia_i_crash WHERE source_id='syn_qld' AND occurrence_year=2020",
        "QA03_PROJECTED",
    ),
    (
        "duplicate_native_vehicle",
        "UPDATE raw.record SET payload=(SELECT payload FROM raw.record WHERE resource_id='syn_vic_vehicle' AND row_locator='csv:2') WHERE resource_id='syn_vic_vehicle' AND row_locator='csv:3'",
        "QA04_AUXILIARY",
    ),
]


@pytest.mark.parametrize("label,statement,rule", FAULTS, ids=[f[0] for f in FAULTS])
def test_faults_block_with_rows_evidence_and_rollback(
    connection, prepared, frozen, label, statement, rule
):
    import psycopg

    # Only the injected corruption uses the owner. The callback retains loader grants.
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
        owner.execute("SET LOCAL ROLE arsia_loader")
        context = chain(owner, prepared, frozen)
        owner.execute("RESET ROLE")
        changed = owner.execute(statement).rowcount
        assert changed > 0
        owner.execute("SET LOCAL ROLE arsia_loader")
        assert owner.execute("SELECT current_user").fetchone() == ("arsia_loader",)
        with pytest.raises(IntakeError) as exc:
            qa.runner_callback(ModuleConnection(owner), context)
        assert exc.value.code == "C10_BLOCK"
        rows = results(owner, context)
        assert len(rows) == 31
        assert any(r[0] == rule and r[1] != "batch" and r[2] == "block" for r in rows)
        assert next(r for r in rows if r[0] == rule and r[1] == "batch")[2] == "block"
        assert (context.evidence.directory / "c10-results.json").is_file()
        for r in rows:
            if r[2] == "block":
                assert r[3] > 0 and r[4]["violation_count"] > 0 and r[6]["reason_codes"]
        owner.rollback()
    assert not any(counts(connection).values())


def test_loader_cannot_mutate_persistent_inputs_or_results(
    connection, prepared, frozen
):
    import psycopg

    context = chain(connection, prepared, frozen)
    qa.runner_callback(ModuleConnection(connection), context)
    for statement in (
        "DELETE FROM raw.record",
        "UPDATE canonical.crash SET map_eligible=false",
        "DELETE FROM qa.check_result",
        "UPDATE qa.check_result SET result='pass'",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connection.transaction():
                connection.execute(statement)
    assert len(results(connection, context)) == 31
    connection.rollback()


def test_missing_or_changed_batch_is_rejected(connection, prepared, frozen):
    from uuid import uuid4

    context = chain(connection, prepared, frozen)
    with pytest.raises(IntakeError, match="Batch is not running"):
        qa.runner_callback(
            ModuleConnection(connection), replace(context, batch_id=str(uuid4()))
        )
    with pytest.raises(IntakeError, match="dataset kind mismatch"):
        qa.runner_callback(
            ModuleConnection(connection), replace(context, dataset_kind="official")
        )
    assert not results(connection, context)
    connection.rollback()


def official_frozen(template, state, root):
    from arsia_c.projections.source_contracts import vic_definitions, qld_definitions
    from cd_support import ROOT

    d = vic_definitions() if state == "VIC" else qld_definitions()
    value = template.as_dict()
    value.update(
        dataset_kind="official",
        analysis=d["analysis"],
        sources=d["sources"],
        files=[c["content"]["input"] for c in d["contracts"]],
    )
    value["rules"].update({k: d[k] for k in ("contracts", "mappings", "severity")})
    value["rules"]["qa_contract"] = json.loads(
        (
            ROOT
            / (
                "config/qa-team-v1.1-vic-r1.json"
                if state == "VIC"
                else "config/qa-team-v1.1.json"
            )
        ).read_text()
    )
    origins = []
    for f in value["files"]:
        filename = (
            "qld_crash_locations.csv"
            if state == "QLD"
            else f["resource_id"].removeprefix("official_") + ".csv"
        )
        path = Path(os.environ["C10_RAW_ROOT"]) / filename
        assert hashlib.sha256(path.read_bytes()).hexdigest() == f["file_sha256"]
        archived = f"official/archive/sha256/{f['file_sha256'][:2]}/{f['file_sha256']}"
        target = root / archived
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            __import__("shutil").copyfile(path, target)
        origins.append(
            {
                "resource_id": f["resource_id"],
                "file_sha256": f["file_sha256"],
                "archive_relpath": archived,
                "original_filename": filename,
                "download_url": (
                    "https://opendata.transport.vic.gov.au/dataset/victoria-road-crash-data"
                    if state == "VIC"
                    else "https://www.data.qld.gov.au/dataset/f3e0ca94-2d7b-44ee-abef-d6b06e9b0729/resource/e88943c0-5968-4972-a15f-38e120d72ec0"
                ),
                "evidence_ref": (
                    "config/vic-restricted-inputs-v1.json"
                    if state == "VIC"
                    else "config/c05-qld-official-v1.json"
                ),
            }
        )
    value["provenance"].update(
        prepared_by="C10 full-original component replay; partial inventory; no FP1 or publication",
        files=origins,
    )
    return FrozenManifest(json.dumps(value))


@pytest.mark.parametrize("state", ["QLD", "VIC"])
def test_complete_adopted_originals(connection, prepared, frozen, state):
    from uuid import uuid4, NAMESPACE_URL, uuid5
    from psycopg.types.json import Jsonb
    from arsia_ingest.raw_load import RawLoader
    from arsia_ingest.readers import iter_native_rows
    from arsia_ingest.models import ResourceSpec, ParseStats
    from arsia_ingest.runner import RunContext, RunEvidence

    evidence = prepared[1] / ("official-" + state)
    evidence.mkdir()
    real = official_frozen(frozen, state, evidence)
    m = real.as_dict()
    batch = str(uuid4())
    RawLoader(
        connection, dataset_kind="official", sources=m["sources"], files=m["files"]
    ).register()
    loaded = {}
    for f in m["files"]:
        archive = next(
            p["archive_relpath"]
            for p in m["provenance"]["files"]
            if p["resource_id"] == f["resource_id"]
        )
        path = evidence / archive
        spec = ResourceSpec(
            **{
                k: f[k]
                for k in (
                    "source_id",
                    "resource_id",
                    "resource_role",
                    "entity_kind",
                    "format",
                    "encoding",
                    "sheet",
                    "header_row",
                )
            },
            path=path,
            header=tuple(f["header"]),
            expected_sha256=f["file_sha256"],
        )
        stats = ParseStats()
        with connection.cursor().copy(
            "COPY raw.record(raw_record_id,resource_id,source_id,file_sha256,parser_version,row_locator,payload) FROM STDIN"
        ) as copy:
            for row in iter_native_rows(path, spec, stats):
                rid = uuid5(
                    NAMESPACE_URL,
                    f["resource_id"] + ":" + f["file_sha256"] + ":" + row.row_locator,
                )
                copy.write_row(
                    (
                        rid,
                        f["resource_id"],
                        f["source_id"],
                        f["file_sha256"],
                        f["parser_version"],
                        row.row_locator,
                        Jsonb(row.payload),
                    )
                )
        assert stats.raw_count == f["raw_count"]
        loaded[f["resource_id"]] = stats.raw_count
        print("Loaded", f["resource_id"], stats.raw_count, flush=True)
    # Raw is a committed input fixture. Analyze it without granting loader ownership.
    connection.commit()
    import psycopg

    try:
        with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as admin:
            assert admin.execute(
                "SELECT current_setting('arsia.test_run',true)"
            ).fetchone() == (os.environ["AC_TEST_RUN"],)
            admin.execute("ANALYZE raw.record")
            admin.execute("ANALYZE meta.source")
            admin.execute("ANALYZE meta.resource")
        fp = hashlib.sha256(("C10 diagnostic batch " + batch).encode()).hexdigest()
        connection.execute(
            "INSERT INTO meta.batch(batch_id,dataset_kind,input_fingerprint,manifest) VALUES (%s,'official',%s,%s)",
            (batch, fp, Jsonb(m)),
        )
        context = RunContext(
            str(uuid4()),
            "official",
            batch,
            fp,
            None,
            real,
            RunEvidence(evidence / "callback"),
        )
        connection.execute("SET LOCAL jit=off")
        connection.execute("SET LOCAL cursor_tuple_fraction=1.0")
        connection.execute("SET LOCAL enable_nestloop=off")
        for stage in ("project", "vault", "canonical", "dw"):
            if stage == "vault":
                connection.execute("SET LOCAL enable_nestloop=on")
                connection.execute("SET LOCAL enable_seqscan=off")
            print(state, stage, call(connection, context, stage), flush=True)
        context = replace(context, evidence=context.evidence.for_stage("qa_c"))
        connection.execute("SET LOCAL enable_nestloop=off")
        connection.execute("SET LOCAL enable_seqscan=on")
        try:
            result = qa.runner_callback(ModuleConnection(connection), context)
        except IntakeError:
            print(json.dumps(results(connection, context), default=str, indent=2))
            raise
        rows = results(connection, context)
        assert all(r[2] != "block" for r in rows)
        assert sum(r[0] == "QA07_LOCATION" and r[1] != "batch" for r in rows) == 5
        assert connection.execute(
            "SELECT count(*) FROM canonical.crash WHERE map_eligible"
        ).fetchone() == (0,)
        if state == "VIC":
            assert connection.execute(
                "SELECT count(*) FROM canonical.unit WHERE count_eligible"
            ).fetchone() == (0,)
            person = next(r for r in rows if r[1] == "resource:official_vic_person")
            assert person[4]["metrics"]["nonblank_unmatched_count"] == 39
            assert person[4]["metrics"]["case_set_match"] is True
            semantics = next(
                r for r in rows if r[0] == "QA05_SEMANTICS" and r[1] != "batch"
            )
            observed = next(
                ref
                for ref in semantics[6]["references"]
                if "undefined_category_rows" in ref
            )
            assert observed["undefined_category_rows"] == {"full": 879, "analysis": 278}
            assert len(observed["publisher_unconfirmed_ids"]) == 10

        receipt = {
            "scope": "Complete original component replay, not B10 or publication",
            "manifest": m,
            "planner_settings": "jit=off; full scans: cursor_tuple_fraction=1,nestloop=off; indexed FK loading: seqscan=off,nestloop=on",
            "loaded": loaded,
            "result": result,
            "summaries": [r for r in rows if r[1] == "batch"],
        }
        connection.rollback()
        after = counts(connection)
        assert after["raw.record"] == sum(loaded.values())
        assert all(
            n == 0
            for table, n in after.items()
            if table not in ("raw.record", "meta.source", "meta.resource")
        )
        receipt["candidate_empty_after_rollback"] = True
        receipt["raw_baseline_unchanged_after_rollback"] = True
        receipt["setup"] = (
            "Pinned Raw committed as input; owner ANALYZE; candidate runs as loader and is rolled back."
        )
        (evidence / "receipt.json").write_text(
            json.dumps(receipt, indent=2, default=str) + "\n"
        )
    finally:
        connection.rollback()
        with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as admin:
            assert admin.execute(
                "SELECT current_setting('arsia.test_run',true)"
            ).fetchone() == (os.environ["AC_TEST_RUN"],)
            ids = [f["resource_id"] for f in m["files"]]
            admin.execute("DELETE FROM raw.record WHERE resource_id=ANY(%s)", (ids,))
            admin.execute("DELETE FROM meta.resource WHERE resource_id=ANY(%s)", (ids,))
            admin.execute(
                "DELETE FROM meta.source WHERE source_id=ANY(%s)",
                ([r["source_id"] for r in m["sources"]],),
            )
        assert not any(counts(connection).values())


if "C10_RAW_ROOT" not in os.environ:
    del test_complete_adopted_originals


def test_new_batch_keeps_previous_qa_rows(connection, prepared, frozen):
    first = chain(connection, prepared, frozen)
    qa.runner_callback(ModuleConnection(connection), first)
    before = results(connection, first)
    # B normally starts a new session; clear only its previous temporary projections.
    connection.execute("TRUNCATE pg_temp.arsia_i_crash,pg_temp.arsia_i_unit")
    second = chain(connection, prepared, frozen)
    qa.runner_callback(ModuleConnection(connection), second)
    assert results(connection, first) == before
    assert len(results(connection, second)) == 31
    connection.rollback()
    assert not any(counts(connection).values())


def test_partial_inventory_cannot_freeze_platform(connection, frozen):
    from arsia_ingest.manifest import freeze_manifest
    from cd_support import ROOT

    fragment = json.loads((ROOT / "config/c10-inventory.json").read_text())
    partial = {
        "components": fragment["components"],
        "schema_files": [e["path"] for e in frozen.as_dict()["rules"]["schema_files"]],
    }
    with pytest.raises(IntakeError):
        freeze_manifest(frozen.as_dict(), project_root=ROOT, inventory=partial)
    assert not any(counts(connection).values())
