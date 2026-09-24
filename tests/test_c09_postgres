"""C09 Canonical PostgreSQL integration tests.

This test isolates the A06 -> C09 boundary:
temporary C projection rows -> A06 Vault -> selected Satellites -> C09 Canonical.

All rows are synthetic and the transaction is rolled back.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from uuid import uuid4

import pytest

from arsia_c.canonical import load_canonical
from arsia_ingest.vault_load import load_vault


pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason=(
        "Set ARSIA_TEST_DSN to A's migrated PostgreSQL 16 "
        "test database with migrations through 006_canonical.sql"
    ),
)


CRASH_TABLE_SQL = """
CREATE TEMP TABLE arsia_i_crash (
    batch_id uuid NOT NULL,
    source_id text NOT NULL,
    release_scope text NOT NULL,
    crash_key text NOT NULL,
    raw_record_id uuid NOT NULL,
    occurrence_year integer NOT NULL,
    occurrence_month integer,
    occurrence_date date,
    date_precision text NOT NULL,
    severity_raw text,
    severity_code text NOT NULL,
    severity_definition_version text NOT NULL,
    is_fatal_crash boolean,
    fatality_count integer,
    casualty_count integer,
    fatal_crash_eligible boolean NOT NULL,
    fatality_eligible boolean NOT NULL,
    casualty_eligible boolean NOT NULL,
    latitude numeric(10,7),
    longitude numeric(10,7),
    location_crs text,
    map_eligible boolean NOT NULL,
    location_record_id uuid,
    quality_notes jsonb NOT NULL
)
"""

UNIT_TABLE_SQL = """
CREATE TEMP TABLE arsia_i_unit (
    batch_id uuid NOT NULL,
    source_id text NOT NULL,
    release_scope text NOT NULL,
    unit_key text NOT NULL,
    crash_key text NOT NULL,
    raw_record_id uuid NOT NULL,
    unit_type_raw text,
    unit_type_code text,
    statistical_scope text NOT NULL,
    count_eligible boolean NOT NULL,
    quality_notes jsonb NOT NULL
)
"""


class FakeManifest:
    def __init__(self, value: dict):
        self._value = deepcopy(value)

    def as_dict(self) -> dict:
        return deepcopy(self._value)


class FakeEvidence:
    def __init__(self):
        self.files = {}

    def write_json(self, name: str, value):
        self.files[name] = deepcopy(value)
        return {
            "path": name,
            "sha256": "test",
            "row_count": 1,
        }


class FakeContext:
    def __init__(self, batch_id, manifest: dict):
        self.batch_id = batch_id
        self.manifest = FakeManifest(manifest)
        self.evidence = FakeEvidence()


@pytest.fixture
def connection():
    dsn = os.environ.get("ARSIA_TEST_DSN")

    if not dsn:
        pytest.fail(
            "ARSIA_TEST_DSN is set but empty",
            pytrace=False,
        )

    try:
        import psycopg
    except ImportError:
        pytest.fail(
            "ARSIA_TEST_DSN is set but psycopg is unavailable",
            pytrace=False,
        )

    try:
        conn = psycopg.connect(
            dsn,
            autocommit=False,
            connect_timeout=10,
        )
    except psycopg.Error as exc:
        pytest.fail(
            "Test database connection failed "
            f"({type(exc).__name__})",
            pytrace=False,
        )

    try:
        assert conn.info.server_version // 10000 == 16

        required_tables = (
            "meta.source",
            "meta.resource",
            "meta.batch",
            "raw.record",
            "rv.hub_crash",
            "rv.sat_crash",
            "rv.hub_unit",
            "rv.sat_unit",
            "rv.link_crash_unit",
            "canonical.crash",
            "canonical.unit",
        )

        for table in required_tables:
            exists = conn.execute(
                "SELECT to_regclass(%s)",
                (table,),
            ).fetchone()[0]

            assert exists, (
                f"{table} is not installed; apply the shared "
                "PostgreSQL migrations through 006_canonical.sql"
            )

        conn.rollback()
        yield conn

    finally:
        conn.rollback()
        conn.close()


class C09Case:
    def __init__(self, connection):
        self.connection = connection

        token = uuid4().hex
        self.source_id = f"syn_c09_{token}"
        self.release_scope = f"c09_test_{token}"

        self.crash_resource_id = (
            f"{self.source_id}_crash"
        )
        self.unit_resource_id = (
            f"{self.source_id}_unit"
        )

        self.crash_sha = "a" * 64
        self.unit_sha = "b" * 64
        self.parser_version = "json-test-v1"

        self.batch_id = uuid4()
        self.crash_raw_id = uuid4()
        self.unit_raw_id = uuid4()

        self.crash_key = '["000123"]'
        self.unit_key = '["000123", "01"]'

        self._register_meta()
        self._insert_raw_rows()
        self._create_projection_tables()
        self._insert_projection_rows()

        self.context = FakeContext(
            self.batch_id,
            self._manifest(),
        )

    def _register_meta(self):
        self.connection.execute(
            """
            INSERT INTO meta.source (
                source_id,
                jurisdiction_code,
                source_name,
                publisher
            )
            VALUES (
                %s,
                'NSW',
                'C09 synthetic integration test',
                'ARSIA synthetic'
            )
            """,
            (self.source_id,),
        )

        self.connection.execute(
            """
            INSERT INTO meta.resource (
                resource_id,
                source_id,
                resource_role,
                entity_kind
            )
            VALUES
                (%s, %s, 'crash', 'crash'),
                (%s, %s, 'traffic_unit', 'unit')
            """,
            (
                self.crash_resource_id,
                self.source_id,
                self.unit_resource_id,
                self.source_id,
            ),
        )

        self.connection.execute(
            """
            INSERT INTO meta.batch (
                batch_id,
                dataset_kind,
                input_fingerprint,
                manifest,
                status
            )
            VALUES (
                %s,
                'synthetic',
                %s,
                %s::jsonb,
                'running'
            )
            """,
            (
                self.batch_id,
                "c" * 64,
                json.dumps(
                    {
                        "test": "C09 A06-to-Canonical integration"
                    }
                ),
            ),
        )

    def _insert_raw_rows(self):
        self.connection.execute(
            """
            INSERT INTO raw.record (
                raw_record_id,
                resource_id,
                source_id,
                file_sha256,
                parser_version,
                row_locator,
                payload
            )
            VALUES
                (
                    %s, %s, %s, %s, %s,
                    'test:crash:1', %s::jsonb
                ),
                (
                    %s, %s, %s, %s, %s,
                    'test:unit:1', %s::jsonb
                )
            """,
            (
                self.crash_raw_id,
                self.crash_resource_id,
                self.source_id,
                self.crash_sha,
                self.parser_version,
                json.dumps({"Crash ID": "000123"}),
                self.unit_raw_id,
                self.unit_resource_id,
                self.source_id,
                self.unit_sha,
                self.parser_version,
                json.dumps(
                    {
                        "Crash ID": "000123",
                        "Traffic unit ID": "01",
                    }
                ),
            ),
        )

    def _create_projection_tables(self):
        self.connection.execute(CRASH_TABLE_SQL)
        self.connection.execute(UNIT_TABLE_SQL)

    def _insert_projection_rows(self):
        self.connection.execute(
            """
            INSERT INTO pg_temp.arsia_i_crash (
                batch_id,
                source_id,
                release_scope,
                crash_key,
                raw_record_id,
                occurrence_year,
                occurrence_month,
                occurrence_date,
                date_precision,
                severity_raw,
                severity_code,
                severity_definition_version,
                is_fatal_crash,
                fatality_count,
                casualty_count,
                fatal_crash_eligible,
                fatality_eligible,
                casualty_eligible,
                latitude,
                longitude,
                location_crs,
                map_eligible,
                location_record_id,
                quality_notes
            )
            VALUES (
                %s, %s, %s, %s, %s,
                2020, 1, NULL, 'month',
                'Fatal', 'FATAL',
                'nsw-crash-severity-v1',
                TRUE, 1, 1,
                TRUE, TRUE, TRUE,
                NULL, NULL, NULL,
                FALSE, NULL,
                %s::jsonb
            )
            """,
            (
                self.batch_id,
                self.source_id,
                self.release_scope,
                self.crash_key,
                self.crash_raw_id,
                json.dumps(
                    {
                        "location": "crs_unconfirmed"
                    }
                ),
            ),
        )

        self.connection.execute(
            """
            INSERT INTO pg_temp.arsia_i_unit (
                batch_id,
                source_id,
                release_scope,
                unit_key,
                crash_key,
                raw_record_id,
                unit_type_raw,
                unit_type_code,
                statistical_scope,
                count_eligible,
                quality_notes
            )
            VALUES (
                %s, %s, %s, %s, %s, %s,
                'Car/car derivative',
                'Car/car derivative',
                'NSW traffic units',
                TRUE,
                '{}'::jsonb
            )
            """,
            (
                self.batch_id,
                self.source_id,
                self.release_scope,
                self.unit_key,
                self.crash_key,
                self.unit_raw_id,
            ),
        )

    def _manifest(self):
        return {
            "sources": [
                {
                    "source_id": self.source_id,
                    "release_scope": self.release_scope,
                }
            ],
            "files": [
                {
                    "source_id": self.source_id,
                    "resource_id": self.crash_resource_id,
                    "file_sha256": self.crash_sha,
                    "parser_version": self.parser_version,
                    "entity_kind": "crash",
                },
                {
                    "source_id": self.source_id,
                    "resource_id": self.unit_resource_id,
                    "file_sha256": self.unit_sha,
                    "parser_version": self.parser_version,
                    "entity_kind": "unit",
                },
            ],
        }

    def load_vault_then_canonical(self):
        load_vault(
            self.connection,
            self.context,
        )

        load_canonical(
            self.connection,
            self.context,
        )


@pytest.fixture
def c09_case(connection):
    return C09Case(connection)


def test_c09_loads_selected_satellites_into_canonical(
    c09_case,
):
    c09_case.load_vault_then_canonical()

    crash = c09_case.connection.execute(
        """
        SELECT
            batch_id,
            source_id,
            release_scope,
            crash_key,
            raw_record_id,
            occurrence_year,
            occurrence_month,
            occurrence_date,
            date_precision,
            severity_raw,
            severity_code,
            severity_definition_version,
            is_fatal_crash,
            fatality_count,
            casualty_count,
            fatal_crash_eligible,
            fatality_eligible,
            casualty_eligible,
            latitude,
            longitude,
            location_crs,
            map_eligible,
            location_record_id,
            quality_notes
        FROM canonical.crash
        WHERE batch_id = %s
          AND source_id = %s
          AND release_scope = %s
        """,
        (
            c09_case.batch_id,
            c09_case.source_id,
            c09_case.release_scope,
        ),
    ).fetchone()

    assert crash is not None

    assert crash[:5] == (
        c09_case.batch_id,
        c09_case.source_id,
        c09_case.release_scope,
        c09_case.crash_key,
        c09_case.crash_raw_id,
    )

    assert crash[5:18] == (
        2020,
        1,
        None,
        "month",
        "Fatal",
        "FATAL",
        "nsw-crash-severity-v1",
        True,
        1,
        1,
        True,
        True,
        True,
    )

    assert crash[18:23] == (
        None,
        None,
        None,
        False,
        None,
    )

    assert crash[23] == {
        "location": "crs_unconfirmed"
    }

    unit = c09_case.connection.execute(
        """
        SELECT
            batch_id,
            source_id,
            release_scope,
            unit_key,
            crash_key,
            raw_record_id,
            unit_type_raw,
            unit_type_code,
            statistical_scope,
            count_eligible,
            quality_notes
        FROM canonical.unit
        WHERE batch_id = %s
          AND source_id = %s
          AND release_scope = %s
        """,
        (
            c09_case.batch_id,
            c09_case.source_id,
            c09_case.release_scope,
        ),
    ).fetchone()

    assert unit == (
        c09_case.batch_id,
        c09_case.source_id,
        c09_case.release_scope,
        c09_case.unit_key,
        c09_case.crash_key,
        c09_case.unit_raw_id,
        "Car/car derivative",
        "Car/car derivative",
        "NSW traffic units",
        True,
        {},
    )


def test_c09_preserves_vault_parent_and_lineage(
    c09_case,
):
    c09_case.load_vault_then_canonical()

    row = c09_case.connection.execute(
        """
        SELECT
            u.unit_key,
            u.crash_key,
            u.raw_record_id,
            c.raw_record_id
        FROM canonical.unit AS u
        JOIN canonical.crash AS c
          ON c.batch_id = u.batch_id
         AND c.source_id = u.source_id
         AND c.release_scope = u.release_scope
         AND c.crash_key = u.crash_key
        WHERE u.batch_id = %s
          AND u.source_id = %s
        """,
        (
            c09_case.batch_id,
            c09_case.source_id,
        ),
    ).fetchone()

    assert row == (
        c09_case.unit_key,
        c09_case.crash_key,
        c09_case.unit_raw_id,
        c09_case.crash_raw_id,
    )


def test_c09_records_canonical_evidence(
    c09_case,
):
    c09_case.load_vault_then_canonical()

    evidence = c09_case.context.evidence.files[
        "c09-canonical-counts.json"
    ]

    assert evidence["batch_id"] == str(
        c09_case.batch_id
    )

    assert evidence["crash_count"] == 1
    assert evidence["unit_count"] == 1
    assert evidence["raw_recomputed"] is False

    assert evidence["sources"][
        c09_case.source_id
    ] == {
        "crash_count": 1,
        "unit_count": 1,
    }
