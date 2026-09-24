"""Opt-in full pinned native projection/Vault/Canonical check; always rolls back.

Requires a dedicated EMPTY PostgreSQL 16 database migrated through A02/011,
ARSIA_TEST_DSN for arsia_loader, and the five separately retained native CSVs.
COPY below is test setup, not B08 acceptance. B08 is exercised by the S0 test.
"""

from argparse import ArgumentParser
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
from time import perf_counter
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from arsia_c.projections import vic, qld
from arsia_c.projections.source_contracts import vic_definitions, qld_definitions
from arsia_ingest.raw_load import RawLoader
from arsia_ingest.runner import ModuleConnection
from arsia_ingest.vault_load import load_vault
from arsia_c.canonical import load_canonical


class Manifest:
    def __init__(self, value):
        self.value = value

    def as_dict(self):
        return json.loads(json.dumps(self.value))


class Evidence:
    def __init__(self):
        self.files = {}

    def write_json(self, name, value):
        self.files[name] = value
        return {"path": name}


class Context:
    def __init__(self, value):
        self.manifest = Manifest(value)
        self.batch_id = uuid4()
        self.evidence = Evidence()
        self.dataset_kind = "official"


def run(state, native_dir):
    import psycopg
    from psycopg.types.json import Jsonb

    started = perf_counter()
    d = vic_definitions() if state == "VIC" else qld_definitions()
    m = {
        "dataset_kind": "official",
        "analysis": d["analysis"],
        "sources": d["sources"],
        "files": [c["content"]["input"] for c in d["contracts"]],
        "rules": {
            **{k: d[k] for k in ("contracts", "mappings", "severity")},
            "qa_contract": {
                "version": "team-v1.1-vic-r1" if state == "VIC" else "team-v1.1"
            },
        },
    }
    ctx = Context(m)
    files = []
    expected = {
        "crashes": 0,
        "fatal_crashes": 0,
        "fatalities": 0,
        "casualties": 0,
        "units": 0,
    }
    selected_keys = set()
    with psycopg.connect(os.environ["ARSIA_TEST_DSN"], autocommit=False) as conn:
        try:
            assert conn.info.server_version // 10000 == 16
            assert conn.execute(
                "SELECT current_user,rolsuper FROM pg_roles WHERE rolname=current_user"
            ).fetchone() == ("arsia_loader", False)
            assert (
                conn.execute(
                    "SELECT (SELECT count(*) FROM raw.record)+(SELECT count(*) FROM meta.batch)"
                ).fetchone()[0]
                == 0
            ), "Use an empty dedicated database"
            loader = RawLoader(
                conn, sources=m["sources"], files=m["files"], dataset_kind="official"
            )
            loader.register()
            for f in m["files"]:
                name = {
                    "official_vic_accident": "vic_accident.csv",
                    "official_vic_vehicle": "vic_vehicle.csv",
                    "official_vic_person": "vic_person.csv",
                    "official_vic_node": "vic_node.csv",
                    "official_qld_crash": "qld_crash_locations.csv",
                }[f["resource_id"]]
                path = native_dir / name
                with path.open("rb") as handle:
                    digest = hashlib.file_digest(handle, "sha256").hexdigest()
                assert digest == f["file_sha256"], name + " digest mismatch"
                count = 0
                with (
                    path.open(encoding="utf-8-sig", newline="") as handle,
                    conn.cursor() as cur,
                ):
                    reader = csv.DictReader(handle)
                    assert reader.fieldnames == f["header"]
                    with cur.copy(
                        "COPY raw.record(raw_record_id,source_id,resource_id,file_sha256,parser_version,row_locator,payload) FROM STDIN"
                    ) as copy:
                        for row in reader:
                            count += 1
                            copy.write_row(
                                (
                                    uuid4(),
                                    f["source_id"],
                                    f["resource_id"],
                                    digest,
                                    f["parser_version"],
                                    f"csv:{count}",
                                    Jsonb(row),
                                )
                            )
                            if f["resource_role"] == "crash":
                                year = int(
                                    row["ACCIDENT_DATE"][:4]
                                    if state == "VIC"
                                    else row["Crash_Year"]
                                )
                                if 2020 <= year <= 2024:
                                    selected_keys.add(
                                        row["ACCIDENT_NO"]
                                        if state == "VIC"
                                        else row["Crash_Ref_Number"]
                                    )
                                    expected["crashes"] += 1
                                    expected["fatal_crashes"] += row[
                                        (
                                            "SEVERITY"
                                            if state == "VIC"
                                            else "Crash_Severity"
                                        )
                                    ] == ("1" if state == "VIC" else "Fatal")
                                    expected["fatalities"] += int(
                                        row[
                                            (
                                                "NO_PERSONS_KILLED"
                                                if state == "VIC"
                                                else "Count_Casualty_Fatality"
                                            )
                                        ]
                                    )
                                    expected["casualties"] += (
                                        sum(
                                            int(row[k])
                                            for k in (
                                                "NO_PERSONS_KILLED",
                                                "NO_PERSONS_INJ_2",
                                                "NO_PERSONS_INJ_3",
                                            )
                                        )
                                        if state == "VIC"
                                        else int(row["Count_Casualty_Total"])
                                    )
                            elif f["resource_role"] == "vehicle":
                                expected["units"] += row["ACCIDENT_NO"] in selected_keys
                assert count == f["raw_count"], name + " row count mismatch"
                files.append(
                    {"resource_id": f["resource_id"], "sha256": digest, "rows": count}
                )
                print(state, name, count, "native rows loaded", flush=True)
            conn.execute(
                "INSERT INTO meta.batch(batch_id,dataset_kind,input_fingerprint,manifest) VALUES (%s,'official',%s,%s::jsonb)",
                (ctx.batch_id, "c" * 64, json.dumps(m)),
            )
            shared = ModuleConnection(conn)
            project_start = perf_counter()
            (vic if state == "VIC" else qld).project(shared, ctx)
            print(
                state,
                "projection completed",
                round(perf_counter() - project_start, 2),
                "seconds",
                flush=True,
            )
            stats = conn.execute(
                "SELECT count(*),count(*) FILTER(WHERE is_fatal_crash),sum(fatality_count),sum(casualty_count),count(*) FILTER(WHERE map_eligible) FROM pg_temp.arsia_i_crash"
            ).fetchone()
            assert stats == (
                expected["crashes"],
                expected["fatal_crashes"],
                expected["fatalities"],
                expected["casualties"],
                0,
            ), (stats, expected)
            assert (
                conn.execute("SELECT count(*) FROM pg_temp.arsia_i_unit").fetchone()[0]
                == expected["units"]
            )
            assert (
                conn.execute(
                    "SELECT count(*) FROM pg_temp.arsia_i_unit WHERE count_eligible"
                ).fetchone()[0]
                == 0
            )
            load_vault(shared, ctx)
            load_canonical(shared, ctx)
            assert (
                conn.execute("SELECT count(*) FROM canonical.crash").fetchone()[0]
                == expected["crashes"]
            )
            assert (
                conn.execute("SELECT count(*) FROM canonical.unit").fetchone()[0]
                == expected["units"]
            )
            print(state, "A06 and C09 completed", flush=True)
            for kind in ("crash", "unit"):
                assert (
                    conn.execute(
                        f"SELECT count(*) FROM ((SELECT * FROM canonical.{kind} EXCEPT SELECT * FROM pg_temp.arsia_i_{kind}) UNION ALL (SELECT * FROM pg_temp.arsia_i_{kind} EXCEPT SELECT * FROM canonical.{kind})) d"
                    ).fetchone()[0]
                    == 0
                )
            return {
                "state": state,
                "files": files,
                "independent_native_totals": expected,
                "projection_aggregates": list(stats),
                "elapsed_seconds": round(perf_counter() - started, 2),
                "real_fp1_executed": False,
                "persisted_qa_executed": False,
                "publication_executed": False,
                "raw_setup": "Verified native CSVs copied directly into Raw for this test; not a full B08/B10 build.",
                "checks": ctx.evidence.files,
                "result": "pass",
            }
        finally:
            conn.rollback()
            assert (
                conn.execute(
                    "SELECT (SELECT count(*) FROM raw.record)+(SELECT count(*) FROM meta.batch)+(SELECT count(*) FROM canonical.crash)"
                ).fetchone()[0]
                == 0
            )
            conn.rollback()


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--state", choices=["VIC", "QLD", "both"], default="both")
    parser.add_argument("--native-dir", type=Path, default=ROOT / "raw_datasource")
    parser.add_argument("--evidence-out", type=Path, required=True)
    args = parser.parse_args()
    results = []
    for state in (["VIC", "QLD"] if args.state == "both" else [args.state]):
        results.append(run(state, args.native_dir))
        args.evidence_out.write_text(
            json.dumps(
                {
                    "scope": "Full native component verification; not project acceptance",
                    "results": results,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
