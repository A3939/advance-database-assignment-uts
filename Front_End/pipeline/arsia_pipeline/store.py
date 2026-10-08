"""Durable jobs and immutable source-combination releases in a dedicated DB."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from .config import read_config

LOCK = 731982701
ACTIVE = ("profiling", "processing", "validating", "publishing", "recovering", "cancel_requested")
FINAL = ("succeeded", "no_change", "failed", "cancelled", "needs_input")
SCHEMA = """
CREATE TABLE local_instance (singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), instance_id text NOT NULL);
CREATE TABLE jobs (
 id uuid PRIMARY KEY, request_id text UNIQUE, label text NOT NULL, status text NOT NULL,
 stage text NOT NULL, message text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(), options jsonb NOT NULL DEFAULT '{}',
 files jsonb NOT NULL DEFAULT '[]', events jsonb NOT NULL DEFAULT '[]', attempt integer NOT NULL DEFAULT 0,
 source_id text, profile_id text, batch_id uuid, release_id uuid, result jsonb, qa jsonb,
 questions jsonb, error jsonb
);
CREATE TABLE attempts (
 id uuid PRIMARY KEY, job_id uuid NOT NULL REFERENCES jobs(id), number integer NOT NULL,
 started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz, status text NOT NULL,
 work_dir text NOT NULL, error jsonb, UNIQUE(job_id,number)
);
CREATE TABLE batches (
 id uuid PRIMARY KEY, job_id uuid NOT NULL REFERENCES jobs(id), source_id text NOT NULL,
 fingerprint text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), result jsonb NOT NULL,
 UNIQUE(source_id,fingerprint)
);
CREATE TABLE canonical_crash (
 batch_id uuid NOT NULL REFERENCES batches(id), record_id text NOT NULL,
 year integer NOT NULL, month integer, severity text, fatalities integer, casualties integer,
 payload jsonb NOT NULL, PRIMARY KEY(batch_id,record_id),
 CHECK(month IS NULL OR month BETWEEN 1 AND 12),
 CHECK(fatalities IS NULL OR fatalities>=0), CHECK(casualties IS NULL OR casualties>=0)
);
CREATE TABLE canonical_unit (batch_id uuid NOT NULL REFERENCES batches(id), ordinal bigint NOT NULL,
 payload jsonb NOT NULL, PRIMARY KEY(batch_id,ordinal));
CREATE TABLE releases (id uuid PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now(), sources jsonb NOT NULL);
CREATE TABLE current_release (singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), release_id uuid NOT NULL REFERENCES releases(id));
CREATE TABLE worker_state (singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), owner text NOT NULL,
 heartbeat_at timestamptz NOT NULL DEFAULT now(), active_job_id uuid);
CREATE INDEX jobs_queue ON jobs(created_at) WHERE status='queued';
CREATE INDEX crashes_analysis ON canonical_crash(batch_id,year,month,severity);
"""


def event(stage, message, **details):
    return {"at": datetime.now(timezone.utc).isoformat(), "stage": stage, "message": message, **details}


def connect(config=None, *, verify=True):
    cfg = config or read_config()
    conn = psycopg.connect(cfg["dsn"], autocommit=True, row_factory=psycopg.rows.dict_row)
    try:
        name = conn.execute("SELECT current_database() AS name").fetchone()["name"]
        if name != cfg["database"] or not name.startswith("arsia_imports_"):
            raise RuntimeError("Refusing a database outside the isolated import laboratory")
        if verify:
            row = conn.execute("SELECT instance_id FROM local_instance WHERE singleton").fetchone()
            if not row or row["instance_id"] != cfg["instance_id"]:
                raise RuntimeError("Import database instance marker mismatch")
        return conn
    except BaseException:
        conn.close()
        raise


def initialize(config):
    with connect(config, verify=False) as conn:
        tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()
        if tables:
            if {r["tablename"] for r in tables} >= {"local_instance", "jobs", "batches", "releases"}:
                with connect(config) as verified:
                    from .migrations import migrate
                    migrate(verified)
                return
            raise RuntimeError("Refusing initialization of a nonempty or unknown database")
        with conn.transaction():
            conn.execute(SCHEMA)
            conn.execute("INSERT INTO local_instance(instance_id) VALUES (%s)", (config["instance_id"],))
        from .migrations import migrate
        migrate(conn)


def clean_job(row):
    if row is None:
        return None
    value = dict(row)
    value.pop("options", None)
    value.pop("request_id", None)
    value["files"] = [{k:v for k,v in f.items() if k != "path"} for f in value["files"]]
    value["events"] = value["events"][-80:]
    return json.loads(json.dumps(value, default=str))


def get_job(job_id, *, internal=False):
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=%s", (job_id,)).fetchone()
    return row if internal else clean_job(row)


def update_job(job_id, status, message, *, stage=None, **fields):
    allowed = {"result", "qa", "questions", "error", "source_id", "profile_id", "batch_id", "release_id"}
    if not set(fields) <= allowed:
        raise ValueError("Unsupported job update")
    stage = stage or status
    with connect() as conn:
        with conn.transaction():
            row = conn.execute("SELECT status FROM jobs WHERE id=%s FOR UPDATE", (job_id,)).fetchone()
            if row is None:
                return
            if row["status"] == "cancel_requested" and status not in ("cancelled", "failed"):
                from .errors import ImportCancelled
                raise ImportCancelled()
            assignments = ["status=%s", "stage=%s", "message=%s", "updated_at=now()", "events=events || %s::jsonb"]
            values = [status, stage, message, Jsonb([event(stage, message)])]
            for key, value in fields.items():
                assignments.append(key + "=%s")
                values.append(Jsonb(value) if key in {"result", "qa", "questions", "error"} else value)
            conn.execute("UPDATE jobs SET " + ",".join(assignments) + " WHERE id=%s", (*values, job_id))


def catalog():
    with connect() as conn:
        row = conn.execute("SELECT r.* FROM current_release c JOIN releases r ON r.id=c.release_id").fetchone()
        if not row:
            return {"release_id": None, "sources": [], "mode": "local-test"}
        sources = []
        for source, batch in row["sources"].items():
            data = conn.execute("SELECT job_id,result FROM batches WHERE id=%s", (batch,)).fetchone()
            sources.append({"source_id": source, "batch_id": batch, "job_id": str(data["job_id"]),
                            "summary": data["result"]["summary"], "limitations": data["result"].get("limitations", [])})
        return {"release_id": str(row["id"]), "sources": sources, "mode": "local-test"}
