from copy import deepcopy
import csv
import json
from pathlib import Path
from uuid import uuid4
from test_c03_nsw_projection import component_manifest
from test_c03_nsw_postgres import FakeContext
from arsia_ingest.raw_load import RawLoader
from arsia_ingest.runner import ModuleConnection

ROOT = Path(__file__).resolve().parents[1]


def state_manifest(state):
    value = component_manifest()
    sid = "syn_" + state.lower()
    value["sources"] = [s for s in value["sources"] if s["source_id"] == sid]
    value["files"] = [f for f in value["files"] if f["source_id"] == sid]
    ids = {f["resource_id"] for f in value["files"]}
    value["rules"]["contracts"] = [
        c for c in value["rules"]["contracts"] if c["id"] in ids
    ]
    value["rules"]["mappings"] = [
        m for m in value["rules"]["mappings"] if m["id"].startswith(sid)
    ]
    value["rules"]["severity"] = [
        s for s in value["rules"]["severity"] if s["source_id"] == sid
    ]
    return value


class Case:
    def __init__(self, connection, state):
        self.connection = connection
        self.manifest = state_manifest(state)
        self.rows = {
            f["resource_id"]: list(
                csv.DictReader(
                    (ROOT / "tests/fixtures/s0" / (f["resource_id"] + ".csv")).open(
                        encoding="utf-8-sig"
                    )
                )
            )
            for f in self.manifest["files"]
        }

    def payload(self, role, index=0):
        file = next(f for f in self.manifest["files"] if f["resource_role"] == role)
        return self.rows[file["resource_id"]][index]

    def load(self, *, sync_counts=True):
        for f in self.manifest["files"]:
            if sync_counts:
                f["raw_count"] = len(self.rows[f["resource_id"]])
            c = next(
                c
                for c in self.manifest["rules"]["contracts"]
                if c["id"] == f["resource_id"]
            )
            c["content"]["input"] = deepcopy(f)
        RawLoader(
            self.connection,
            sources=self.manifest["sources"],
            files=self.manifest["files"],
            dataset_kind="synthetic",
        ).register()
        for f in self.manifest["files"]:
            for n, row in enumerate(self.rows[f["resource_id"]], 2):
                self.connection.execute(
                    "INSERT INTO raw.record(raw_record_id,source_id,resource_id,file_sha256,parser_version,row_locator,payload) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)",
                    (
                        uuid4(),
                        f["source_id"],
                        f["resource_id"],
                        f["file_sha256"],
                        f["parser_version"],
                        f"csv:{n}",
                        json.dumps(row),
                    ),
                )
        self.context = FakeContext(self.manifest)
        self.connection.execute(
            "INSERT INTO meta.batch(batch_id,dataset_kind,input_fingerprint,manifest) VALUES (%s,'synthetic',%s,%s::jsonb)",
            (self.context.batch_id, "a" * 64, json.dumps(self.manifest)),
        )
        return self

    def run(self):
        from arsia_c.projections import vic, qld

        module = (
            vic if self.manifest["sources"][0]["jurisdiction_code"] == "VIC" else qld
        )
        module.project(ModuleConnection(self.connection), self.context)

    def crashes(self):
        return [
            r[0]
            for r in self.connection.execute(
                "SELECT to_jsonb(c) FROM pg_temp.arsia_i_crash c ORDER BY crash_key"
            )
        ]
