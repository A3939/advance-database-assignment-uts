"""C03 NSW projection integration tests on PostgreSQL 16.

All source rows are synthetic and every test transaction is rolled back.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from uuid import uuid4

import pytest

from arsia_c.projections.nsw import project


pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason=(
        "Set ARSIA_TEST_DSN to A's migrated "
        "PostgreSQL 16 test database"
    ),
)


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
            "raw.record",
        )

        for table in required_tables:
            exists = conn.execute(
                "SELECT to_regclass(%s)",
                (table,),
            ).fetchone()[0]

            assert exists, table

        business_key_function = conn.execute(
            """
            SELECT to_regprocedure(
                'rv.encode_business_key(text[])'
            )
            """
        ).fetchone()[0]

        assert business_key_function, (
            "rv.encode_business_key(text[]) is not installed"
        )

        conn.rollback()

        yield conn

    finally:
        conn.rollback()
        conn.close()


class FakeManifest:
    def __init__(self, value: dict):
        self._value = deepcopy(value)

    def as_dict(self) -> dict:
        return deepcopy(self._value)


class FakeEvidence:
    def __init__(self):
        self.files = {}

    def write_json(
        self,
        name: str,
        value,
    ):
        self.files[name] = deepcopy(value)

        return {
            "path": name,
            "sha256": "test",
            "row_count": 1,
        }


class FakeContext:
    def __init__(
        self,
        manifest: dict,
    ):
        self.batch_id = uuid4()
        self.manifest = FakeManifest(manifest)
        self.evidence = FakeEvidence()


class NSWCase:
    def __init__(self, connection):
        self.connection = connection

        self.source_id = (
            f"syn_c03_{uuid4().hex}"
        )

        self.crash_resource_id = (
            f"{self.source_id}_crash"
        )

        self.unit_resource_id = (
            f"{self.source_id}_traffic_unit"
        )

        self.crash_sha = "a" * 64
        self.unit_sha = "b" * 64

        self.parser_version = "xlsx-native-v1"
        self.release_scope = "nsw_test_2020_2024_v1"

        self._register_source()
        self._register_resources()

        self.context = FakeContext(
            self._manifest()
        )

    def _register_source(self):
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
                'C03 test',
                'ARSIA synthetic'
            )
            """,
            (self.source_id,),
        )

    def _register_resources(self):
        self.connection.execute(
            """
            INSERT INTO meta.resource (
                resource_id,
                source_id,
                resource_role,
                entity_kind
            )
            VALUES
                (
                    %s,
                    %s,
                    'crash',
                    'crash'
                ),
                (
                    %s,
                    %s,
                    'traffic_unit',
                    'unit'
                )
            """,
            (
                self.crash_resource_id,
                self.source_id,
                self.unit_resource_id,
                self.source_id,
            ),
        )

    def _manifest(self) -> dict:
        return {
            "rules": {
                "contracts": [
                    {
                        "id": "official_nsw_crash",
                        "mapping_ids": [
                            "nsw-crash-projection-v1"
                        ],
                        "content": {
                            "input": {
                                "source_id":
                                    self.source_id,
                                "resource_id":
                                    self.crash_resource_id,
                                "file_sha256":
                                    self.crash_sha,
                                "parser_version":
                                    self.parser_version,
                            },
                            "identity": {
                                "release_scope":
                                    self.release_scope,
                            },
                            "semantics": {
                                "severity_definition_version":
                                    "nsw-crash-severity-v1",
                            },
                        },
                    },
                    {
                        "id":
                            "official_nsw_traffic_unit",
                        "mapping_ids": [
                            "nsw-traffic-unit-projection-v1"
                        ],
                        "content": {
                            "input": {
                                "source_id":
                                    self.source_id,
                                "resource_id":
                                    self.unit_resource_id,
                                "file_sha256":
                                    self.unit_sha,
                                "parser_version":
                                    self.parser_version,
                            },
                            "identity": {
                                "release_scope":
                                    self.release_scope,
                            },
                        },
                    },
                ],
                "mappings": [
                    {
                        "id":
                            "nsw-crash-projection-v1",
                        "content": {},
                    },
                    {
                        "id":
                            "nsw-traffic-unit-projection-v1",
                        "content": {
                            "statistical_scope":
                                "NSW traffic units",
                        },
                    },
                ],
            }
        }

    def add_raw(
        self,
        *,
        resource_id: str,
        file_sha256: str,
        row_locator: str,
        payload: dict,
    ):
        raw_record_id = uuid4()

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
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s::jsonb
            )
            """,
            (
                raw_record_id,
                resource_id,
                self.source_id,
                file_sha256,
                self.parser_version,
                row_locator,
                json.dumps(payload),
            ),
        )

        return raw_record_id

    def crash(
        self,
        *,
        crash_id="000123",
        year="2020",
        month="January",
        severity="Fatal",
        killed="1",
        serious="0",
        moderate="0",
        minor="0",
        locator=None,
    ):
        locator = locator or (
            f"xlsx:crash:{uuid4().hex}"
        )

        return self.add_raw(
            resource_id=self.crash_resource_id,
            file_sha256=self.crash_sha,
            row_locator=locator,
            payload={
                "Crash ID":
                    crash_id,
                "Year of crash":
                    year,
                "Month of crash":
                    month,
                "Degree of crash - detailed":
                    severity,
                "No. killed":
                    killed,
                "No. seriously injured":
                    serious,
                "No. moderately injured":
                    moderate,
                "No. minor-other injured":
                    minor,
            },
        )

    def unit(
        self,
        *,
        crash_id="000123",
        unit_id="01",
        unit_type="Car/car derivative",
        locator=None,
    ):
        locator = locator or (
            f"xlsx:unit:{uuid4().hex}"
        )

        return self.add_raw(
            resource_id=self.unit_resource_id,
            file_sha256=self.unit_sha,
            row_locator=locator,
            payload={
                "Crash ID":
                    crash_id,
                "Traffic unit ID":
                    unit_id,
                "TU type group":
                    unit_type,
            },
        )

    def run(self):
        project(
            self.connection,
            self.context,
        )


@pytest.fixture
def nsw_case(connection):
    return NSWCase(connection)


def test_c03_projects_valid_nsw_rows(
    nsw_case,
):
    nsw_case.crash(
        crash_id="000123",
        year="2020",
        month="January",
        severity="Fatal",
        killed="1",
        serious="0",
        moderate="0",
        minor="0",
    )

    nsw_case.unit(
        crash_id="000123",
        unit_id="01",
        unit_type="Car/car derivative",
    )

    # Valid parent/child pair outside analytical scope.
    nsw_case.crash(
        crash_id="000099",
        year="2019",
        month="December",
        severity="Non-casualty (towaway)",
        killed="0",
        serious="0",
        moderate="0",
        minor="0",
    )

    nsw_case.unit(
        crash_id="000099",
        unit_id="01",
        unit_type="Pedestrian",
    )

    nsw_case.run()

    crash_rows = (
        nsw_case.connection.execute(
            """
            SELECT
                crash_key,
                occurrence_year,
                occurrence_month,
                date_precision,
                severity_code,
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
                location_record_id
            FROM pg_temp.arsia_i_crash
            ORDER BY crash_key
            """
        ).fetchall()
    )

    assert crash_rows == [
        (
            '["000123"]',
            2020,
            1,
            "month",
            "FATAL",
            True,
            1,
            1,
            True,
            True,
            True,
            None,
            None,
            None,
            False,
            None,
        )
    ]

    unit_rows = (
        nsw_case.connection.execute(
            """
            SELECT
                unit_key,
                crash_key,
                unit_type_raw,
                unit_type_code,
                statistical_scope,
                count_eligible
            FROM pg_temp.arsia_i_unit
            ORDER BY unit_key
            """
        ).fetchall()
    )

    assert unit_rows == [
        (
            '["000123", "01"]',
            '["000123"]',
            "Car/car derivative",
            None,
            "NSW traffic units",
            True,
        )
    ]

    evidence = (
        nsw_case.context.evidence.files[
            "c03-nsw-projection-counts.json"
        ]
    )

    assert (
        evidence["crash_projection_count"]
        == 1
    )

    assert (
        evidence["unit_projection_count"]
        == 1
    )

    assert (
        evidence["fatal_crash_count"]
        == 1
    )

    assert (
        evidence["fatality_count"]
        == 1
    )

    assert (
        evidence["casualty_count"]
        == 1
    )

    assert (
        evidence["map_eligible_count"]
        == 0
    )


def test_c03_preserves_leading_zeros_in_keys(
    nsw_case,
):
    nsw_case.crash(
        crash_id="000007",
    )

    nsw_case.unit(
        crash_id="000007",
        unit_id="0002",
    )

    nsw_case.run()

    crash_key = (
        nsw_case.connection.execute(
            """
            SELECT crash_key
            FROM pg_temp.arsia_i_crash
            """
        ).fetchone()[0]
    )

    unit_key = (
        nsw_case.connection.execute(
            """
            SELECT unit_key
            FROM pg_temp.arsia_i_unit
            """
        ).fetchone()[0]
    )

    assert crash_key == '["000007"]'

    assert (
        unit_key
        == '["000007", "0002"]'
    )


def test_c03_blocks_orphan_unit_before_year_filter(
    nsw_case,
):
    nsw_case.crash(
        crash_id="000123",
    )

    nsw_case.unit(
        crash_id="MISSING",
        unit_id="01",
    )

    with pytest.raises(
        ValueError,
        match="relationship validation failed",
    ):
        nsw_case.run()


def test_c03_blocks_unknown_month(
    nsw_case,
):
    nsw_case.crash(
        crash_id="000123",
        month="Jan",
    )

    nsw_case.unit(
        crash_id="000123",
    )

    with pytest.raises(
        ValueError,
        match="month validation failed",
    ):
        nsw_case.run()


def test_c03_blocks_unknown_severity(
    nsw_case,
):
    nsw_case.crash(
        crash_id="000123",
        severity="Mystery Injury",
    )

    nsw_case.unit(
        crash_id="000123",
    )

    with pytest.raises(
        ValueError,
        match="semantic validation failed",
    ):
        nsw_case.run()


def test_c03_missing_casualty_component_stays_null(
    nsw_case,
):
    nsw_case.crash(
        crash_id="000123",
        killed="0",
        serious=None,
        moderate="1",
        minor="0",
        severity="Moderate Injury",
    )

    nsw_case.unit(
        crash_id="000123",
    )

    nsw_case.run()

    row = (
        nsw_case.connection.execute(
            """
            SELECT
                fatality_count,
                casualty_count,
                fatality_eligible,
                casualty_eligible,
                quality_notes
            FROM pg_temp.arsia_i_crash
            """
        ).fetchone()
    )

    assert row[0] == 0
    assert row[1] is None
    assert row[2] is True
    assert row[3] is False

    assert (
        row[4]["casualty"]
        == "missing"
    )


def test_c03_missing_unit_type_is_not_count_eligible(
    nsw_case,
):
    nsw_case.crash(
        crash_id="000123",
    )

    nsw_case.unit(
        crash_id="000123",
        unit_type=None,
    )

    nsw_case.run()

    row = (
        nsw_case.connection.execute(
            """
            SELECT
                unit_type_raw,
                count_eligible,
                quality_notes
            FROM pg_temp.arsia_i_unit
            """
        ).fetchone()
    )

    assert row[0] is None
    assert row[1] is False

    assert (
        row[2]["count"]
        == "missing"
    )


def test_c03_blocks_unknown_nonempty_unit_type(
    nsw_case,
):
    nsw_case.crash(
        crash_id="000123",
    )

    nsw_case.unit(
        crash_id="000123",
        unit_type="Hoverboard",
    )

    with pytest.raises(
        ValueError,
        match="Traffic Unit validation failed",
    ):
        nsw_case.run()


def test_c03_zero_counts_remain_zero(
    nsw_case,
):
    nsw_case.crash(
        crash_id="000123",
        severity="Non-casualty (towaway)",
        killed="0",
        serious="0",
        moderate="0",
        minor="0",
    )

    nsw_case.unit(
        crash_id="000123",
    )

    nsw_case.run()

    row = (
        nsw_case.connection.execute(
            """
            SELECT
                fatality_count,
                casualty_count,
                fatality_eligible,
                casualty_eligible
            FROM pg_temp.arsia_i_crash
            """
        ).fetchone()
    )

    assert row == (
        0,
        0,
        True,
        True,
    )
    
