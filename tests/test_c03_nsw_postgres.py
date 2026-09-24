"""C03 NSW projection integration tests on PostgreSQL 16.

All source rows are synthetic and every test transaction is rolled back.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from uuid import uuid4
from pathlib import Path
from test_c03_nsw_projection import component_manifest

import pytest

from arsia_c.projections.nsw import project

pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason=("Set ARSIA_TEST_DSN to A's migrated " "PostgreSQL 16 test database"),
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
            "Test database connection failed " f"({type(exc).__name__})",
            pytrace=False,
        )

    try:
        assert conn.info.server_version // 10000 == 16
        assert conn.execute(
            "SELECT current_user, rolsuper FROM pg_roles WHERE rolname=current_user"
        ).fetchone() == ("arsia_loader", False)

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

        business_key_function = conn.execute("""
            SELECT to_regprocedure(
                'rv.encode_business_key(text[])'
            )
            """).fetchone()[0]

        assert business_key_function, "rv.encode_business_key(text[]) is not installed"

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
    def __init__(self, connection, dataset_kind="synthetic"):
        self.connection = connection
        self.dataset_kind = dataset_kind

        self.source_id = (
            f"{'syn' if dataset_kind == 'synthetic' else 'official'}_c03_{uuid4().hex}"
        )

        self.crash_resource_id = f"{self.source_id}_crash"

        self.unit_resource_id = f"{self.source_id}_traffic_unit"

        self.crash_sha = "a" * 64
        self.unit_sha = "b" * 64

        self.parser_version = "xlsx-native-v1"
        self.release_scope = "nsw_test_2020_2024_v1"

        self._register_source()
        self._register_resources()

        self.context = FakeContext(self._manifest())

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
        value = component_manifest()
        value["dataset_kind"] = self.dataset_kind
        value = json.loads(json.dumps(value).replace("syn_nsw", self.source_id))
        value["sources"] = [
            x for x in value["sources"] if x["source_id"] == self.source_id
        ]
        value["sources"][0]["release_scope"] = self.release_scope
        value["files"] = [f for f in value["files"] if f["source_id"] == self.source_id]
        value["rules"]["contracts"] = [
            c
            for c in value["rules"]["contracts"]
            if c["content"]["input"]["source_id"] == self.source_id
        ]
        value["rules"]["mappings"] = [
            m for m in value["rules"]["mappings"] if m["id"].startswith(self.source_id)
        ]
        categories = [
            ("FATAL", "Fatal", True),
            ("MODERATE_INJURY", "Moderate Injury", False),
            ("NON_CASUALTY_TOWAWAY", "Non-casualty (towaway)", False),
        ]
        value["rules"]["severity"] = [
            {
                "source_id": self.source_id,
                "definition_version": "test-nsw-1",
                "severity_code": code,
                "severity_label": label,
                "is_fatal_crash": fatal,
                "definition_text": "Test fixture only",
            }
            for code, label, fatal in categories + [("__MISSING__", "Unknown", None)]
        ]
        for file in value["files"]:
            file.update(
                raw_count=0,
                file_sha256=(
                    self.crash_sha if file["entity_kind"] == "crash" else self.unit_sha
                ),
            )
        for contract in value["rules"]["contracts"]:
            contract["status"] = (
                "synthetic_defined" if self.dataset_kind == "synthetic" else "confirmed"
            )
            contract["content"]["input"] = deepcopy(
                next(f for f in value["files"] if f["resource_id"] == contract["id"])
            )
            contract["content"]["identity"]["release_scope"] = self.release_scope
            contract["content"]["semantics"][
                "severity_definition_version"
            ] = "test-nsw-1"
        cm, um = value["rules"]["mappings"]
        cm["content"]["native_severity_codes"] = {
            label: code for code, label, _ in categories
        }
        cm["content"]["location"]["crs"] = None
        um["content"]["unit_types"] = {
            "Car/car derivative": "CAR",
            "Pedestrian": "PEDESTRIAN",
        }
        um["content"]["statistical_scope"] = "NSW traffic units"
        return value

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

        # This micro-fixture declares each inserted synthetic row as expected input.
        value = self.context.manifest._value
        for file in value["files"]:
            if file["resource_id"] == resource_id:
                file["raw_count"] += 1
        for contract in value["rules"]["contracts"]:
            if contract["id"] == resource_id:
                contract["content"]["input"]["raw_count"] += 1
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
        latitude=None,
        longitude=None,
        locator=None,
    ):
        locator = locator or (f"xlsx:crash:{uuid4().hex}")

        return self.add_raw(
            resource_id=self.crash_resource_id,
            file_sha256=self.crash_sha,
            row_locator=locator,
            payload={
                "Crash ID": crash_id,
                "Latitude": latitude,
                "Longitude": longitude,
                "Year of crash": year,
                "Month of crash": month,
                "Degree of crash - detailed": severity,
                "No. killed": killed,
                "No. seriously injured": serious,
                "No. moderately injured": moderate,
                "No. minor-other injured": minor,
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
        locator = locator or (f"xlsx:unit:{uuid4().hex}")

        return self.add_raw(
            resource_id=self.unit_resource_id,
            file_sha256=self.unit_sha,
            row_locator=locator,
            payload={
                "Crash ID": crash_id,
                "Traffic unit ID": unit_id,
                "TU type group": unit_type,
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

    crash_rows = nsw_case.connection.execute("""
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
            """).fetchall()

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

    unit_rows = nsw_case.connection.execute("""
            SELECT
                unit_key,
                crash_key,
                unit_type_raw,
                unit_type_code,
                statistical_scope,
                count_eligible
            FROM pg_temp.arsia_i_unit
            ORDER BY unit_key
            """).fetchall()

    assert unit_rows == [
        (
            '["000123", "01"]',
            '["000123"]',
            "Car/car derivative",
            "CAR",
            "NSW traffic units",
            True,
        )
    ]

    evidence = nsw_case.context.evidence.files["c03-nsw-projection-counts.json"]

    assert evidence["crash_projection_count"] == 1

    assert evidence["unit_projection_count"] == 1

    assert evidence["fatal_crash_count"] == 1

    assert evidence["fatality_count"] == 1

    assert evidence["casualty_count"] == 1

    assert evidence["map_eligible_count"] == 0


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

    crash_key = nsw_case.connection.execute("""
            SELECT crash_key
            FROM pg_temp.arsia_i_crash
            """).fetchone()[0]

    unit_key = nsw_case.connection.execute("""
            SELECT unit_key
            FROM pg_temp.arsia_i_unit
            """).fetchone()[0]

    assert crash_key == '["000007"]'

    assert unit_key == '["000007", "0002"]'


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

    row = nsw_case.connection.execute("""
            SELECT
                fatality_count,
                casualty_count,
                fatality_eligible,
                casualty_eligible,
                quality_notes
            FROM pg_temp.arsia_i_crash
            """).fetchone()

    assert row[0] == 0
    assert row[1] is None
    assert row[2] is True
    assert row[3] is False

    assert (
        next(x for x in row[4]["fields"] if x["field"] == "casualty_count")[
            "reason_code"
        ]
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

    row = nsw_case.connection.execute("""
            SELECT
                unit_type_raw,
                count_eligible,
                quality_notes
            FROM pg_temp.arsia_i_unit
            """).fetchone()

    assert row[0] is None
    assert row[1] is False

    assert row[2]["fields"][0]["reason_code"] == "missing"


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

    row = nsw_case.connection.execute("""
            SELECT
                fatality_count,
                casualty_count,
                fatality_eligible,
                casualty_eligible
            FROM pg_temp.arsia_i_crash
            """).fetchone()

    assert row == (
        0,
        0,
        True,
        True,
    )


def assert_canonical_constraints(connection):
    """Use A02/011 actual CHECK constraints, without pretending to run A06/C09."""
    for entity in ("crash", "unit"):
        connection.execute(
            f"CREATE TEMP TABLE c03_contract_{entity} (LIKE canonical.{entity} INCLUDING CONSTRAINTS) ON COMMIT DROP"
        )
        connection.execute(
            f"INSERT INTO c03_contract_{entity} SELECT * FROM pg_temp.arsia_i_{entity}"
        )


def test_units_satisfy_actual_a02_constraints(nsw_case):
    nsw_case.crash()
    nsw_case.unit()
    nsw_case.run()
    assert_canonical_constraints(nsw_case.connection)


@pytest.mark.parametrize(
    "year_from,year_to,expected", [(2019, 2019, 1), (2021, 2022, 2), (2025, 2026, 0)]
)
def test_manifest_years_control_both_crash_and_unit_scope(
    nsw_case, year_from, year_to, expected
):
    for year in (2019, 2020, 2021, 2022, 2024):
        nsw_case.crash(crash_id=str(year), year=str(year))
        nsw_case.unit(crash_id=str(year))
    nsw_case.context.manifest._value["analysis"] = {
        "year_from": year_from,
        "year_to": year_to,
    }
    nsw_case.run()
    counts = nsw_case.context.evidence.files["c03-nsw-projection-counts.json"]
    assert (counts["crash_projection_count"], counts["unit_projection_count"]) == (
        expected,
        expected,
    )
    assert counts["excluded_crash_count"] == 5 - expected
    assert counts["excluded_unit_count"] == 5 - expected
    assert (
        nsw_case.connection.execute(
            "SELECT count(*) FROM raw.record WHERE source_id=%s", (nsw_case.source_id,)
        ).fetchone()[0]
        == 10
    )
    if expected == 0:
        assert counts["fatality_count"] is None and counts["casualty_count"] is None


@pytest.mark.parametrize(
    "which,key",
    [("crash", "\t"), ("crash", "\u00a0\u2003"), ("unit", "\n\r"), ("unit", "")],
)
def test_blank_keys_block_even_outside_analysis(nsw_case, which, key):
    nsw_case.crash(crash_id=key if which == "crash" else "outside", year="2019")
    if which == "unit":
        nsw_case.unit(crash_id="outside", unit_id=key)
    with pytest.raises(ValueError, match="relationship validation failed"):
        nsw_case.run()


@pytest.mark.parametrize("which", ["crash", "unit"])
def test_duplicate_native_keys_block_before_year_filter(nsw_case, which):
    nsw_case.crash(year="2019")
    if which == "crash":
        nsw_case.crash(year="2019")
    else:
        nsw_case.unit()
        nsw_case.unit()
    with pytest.raises(ValueError, match="relationship validation failed"):
        nsw_case.run()


@pytest.mark.parametrize("bad", ["-1", "1.2", "Unknown", "2147483648"])
def test_invalid_people_counts_block(nsw_case, bad):
    nsw_case.crash(killed=bad)
    with pytest.raises(ValueError, match="semantic validation failed"):
        nsw_case.run()


def test_unknown_total_remains_null_when_known_components_are_large(nsw_case):
    nsw_case.crash(killed="2147483647", serious="1", moderate=None)
    nsw_case.run()
    assert nsw_case.connection.execute(
        "SELECT casualty_count,casualty_eligible FROM pg_temp.arsia_i_crash"
    ).fetchone() == (None, False)


@pytest.mark.parametrize("bad", [None, "unknown", "1899", "2101"])
def test_invalid_occurrence_year_blocks(nsw_case, bad):
    nsw_case.crash(year=bad)
    with pytest.raises(ValueError, match="year validation failed"):
        nsw_case.run()


def test_native_empty_synthetic_values_keep_unknowns_and_structured_reasons(nsw_case):
    nsw_case.crash(month="", severity="", killed="", serious="", moderate="", minor="")
    nsw_case.unit(unit_type="")
    nsw_case.run()
    row = nsw_case.connection.execute(
        "SELECT occurrence_month,date_precision,severity_code,is_fatal_crash,fatality_count,casualty_count,quality_notes FROM pg_temp.arsia_i_crash"
    ).fetchone()
    assert row[:6] == (None, "year", "__MISSING__", None, None, None)
    assert len(row[6]["fields"]) == 3
    for note in row[6]["fields"]:
        assert set(note) == {"field", "reason_code", "raw_token", "contract_version"}
        assert note["reason_code"] == "missing"
    counts = nsw_case.context.evidence.files["c03-nsw-projection-counts.json"]
    assert counts["fatality_count"] is None and counts["casualty_count"] is None
    assert_canonical_constraints(nsw_case.connection)


@pytest.mark.parametrize(
    "latitude,longitude,eligible,reason",
    [
        ("-33.86", "151.2", True, None),
        ("90", "180", True, None),
        ("90.00000001", "180", False, "invalid_coordinate"),
        ("-33", "180.00000001", False, "invalid_coordinate"),
        ("NaN", "151", False, "invalid_coordinate"),
        ("-33", "Infinity", False, "invalid_coordinate"),
        ("1e999999999", "151", False, "invalid_coordinate"),
        (None, "151", False, "missing"),
    ],
)
def test_synthetic_coordinates_validate_before_rounding(
    nsw_case, latitude, longitude, eligible, reason
):
    nsw_case.context.manifest._value["rules"]["mappings"][0]["content"]["location"][
        "crs"
    ] = "EPSG:4326"
    raw_id = nsw_case.crash(latitude=latitude, longitude=longitude)
    nsw_case.run()
    row = nsw_case.connection.execute(
        "SELECT latitude,longitude,location_crs,map_eligible,location_record_id,quality_notes FROM pg_temp.arsia_i_crash"
    ).fetchone()
    assert row[3] is eligible
    if eligible:
        assert row[2] == "EPSG:4326" and row[4] == raw_id
    else:
        assert row[:3] == (None, None, None) and row[4] is None
        assert row[5]["location"]["reason_code"] == reason
        assert row[5]["location"]["candidate_raw_record_ids"] == [str(raw_id)]
    assert_canonical_constraints(nsw_case.connection)


def test_official_profile_keeps_maps_disabled(connection):
    # Artificial rows/confirmation for isolated policy testing only; not publisher approval.
    case = NSWCase(connection, dataset_kind="official")
    case.context.manifest._value["rules"]["mappings"][0]["content"]["location"][
        "crs"
    ] = "EPSG:4326"
    case.crash(latitude="-33.86", longitude="151.2")
    case.unit()
    case.run()
    row = connection.execute(
        "SELECT latitude,longitude,location_crs,map_eligible,location_record_id,quality_notes FROM pg_temp.arsia_i_crash"
    ).fetchone()
    assert row[:5] == (None, None, None, False, None)
    assert row[5]["location"]["reason_code"] == "crs_unconfirmed"
    assert_canonical_constraints(connection)


def test_incomplete_raw_snapshot_blocks(nsw_case):
    nsw_case.crash()
    for item in nsw_case.context.manifest._value["files"]:
        if item["entity_kind"] == "crash":
            item["raw_count"] += 1
    nsw_case.context.manifest._value["rules"]["contracts"][0]["content"]["input"][
        "raw_count"
    ] += 1
    with pytest.raises(ValueError, match="incomplete Raw"):
        nsw_case.run()


def test_repeat_projection_preserves_other_sources(nsw_case):
    nsw_case.crash()
    nsw_case.unit()
    nsw_case.run()
    for entity in ("crash", "unit"):
        columns = [
            d.name
            for d in nsw_case.connection.execute(
                f"SELECT * FROM pg_temp.arsia_i_{entity} LIMIT 0"
            ).description
        ]
        select = ",".join("'syn_other'" if x == "source_id" else x for x in columns)
        nsw_case.connection.execute(
            f"INSERT INTO pg_temp.arsia_i_{entity} SELECT {select} FROM pg_temp.arsia_i_{entity}"
        )
    nsw_case.run()
    for entity in ("crash", "unit"):
        assert nsw_case.connection.execute(
            f"SELECT source_id,count(*) FROM pg_temp.arsia_i_{entity} GROUP BY source_id ORDER BY source_id"
        ).fetchall() == [(nsw_case.source_id, 1), ("syn_other", 1)]


def test_frozen_unit_code_is_used(nsw_case):
    nsw_case.context.manifest._value["rules"]["mappings"][1]["content"]["unit_types"][
        "Car/car derivative"
    ] = "PASSENGER_CAR"
    nsw_case.crash()
    nsw_case.unit()
    nsw_case.run()
    assert nsw_case.connection.execute(
        "SELECT unit_type_code,count_eligible FROM pg_temp.arsia_i_unit"
    ).fetchone() == ("PASSENGER_CAR", True)


def test_real_b08_s0_and_b09_definitions_on_b10_connection(connection, tmp_path):
    from decimal import Decimal
    from arsia_ingest.pipeline import prepare
    from arsia_ingest.raw_load import load_prepared
    from arsia_ingest.runner import ModuleConnection, RunEvidence

    root = Path(__file__).resolve().parents[1]
    value = component_manifest()
    prepared = prepare(root / "tests/fixtures/s0/config.json", tmp_path / "intake")
    assert prepared["status"] == "prepared"
    loaded = load_prepared(connection, prepared["run_dir"], value["sources"])
    assert loaded.raw_count == 19
    before = connection.execute(
        "SELECT raw_record_id,payload FROM raw.record ORDER BY raw_record_id"
    ).fetchall()
    context = FakeContext(
        value
    )  # Explicit component snapshot; no fake FP1/full inventory.
    context.evidence = RunEvidence(tmp_path / "evidence")
    shared = ModuleConnection(connection)
    assert not hasattr(shared, "commit") and not hasattr(shared, "rollback")
    project(shared, context)
    crashes = connection.execute(
        "SELECT crash_key,occurrence_year,occurrence_month,date_precision,severity_code,fatality_count,casualty_count,map_eligible,latitude,longitude,raw_record_id,location_record_id FROM pg_temp.arsia_i_crash ORDER BY crash_key"
    ).fetchall()
    assert crashes[0][:10] == (
        '["0001"]',
        2020,
        1,
        "month",
        "F",
        2,
        3,
        True,
        Decimal("-33.8600000"),
        Decimal("151.2000000"),
    )
    assert crashes[0][10] == crashes[0][11]
    assert crashes[1][:10] == (
        '["0002"]',
        2020,
        None,
        "year",
        "__MISSING__",
        None,
        None,
        False,
        None,
        None,
    )
    assert connection.execute(
        "SELECT unit_key,unit_type_code,statistical_scope,count_eligible FROM pg_temp.arsia_i_unit ORDER BY unit_key"
    ).fetchall() == [
        ('["0001", "01"]', "CAR", "synthetic_traffic_unit", True),
        ('["0001", "02"]', "CAR", "synthetic_traffic_unit", True),
        ('["0002", "01"]', "CAR", "synthetic_traffic_unit", True),
    ]
    assert_canonical_constraints(connection)
    assert (
        connection.execute(
            "SELECT raw_record_id,payload FROM raw.record ORDER BY raw_record_id"
        ).fetchall()
        == before
    )
    evidence = json.loads(
        (tmp_path / "evidence/c03-nsw-projection-counts.json").read_text(
            encoding="utf-8"
        )
    )
    assert (
        evidence["crash_projection_count"],
        evidence["unit_projection_count"],
        evidence["map_eligible_count"],
    ) == (2, 3, 1)
    connection.rollback()
    # Proves the callback did not commit B's uncommitted Raw or registry changes.
    assert (
        connection.execute(
            "SELECT count(*) FROM meta.source WHERE source_id='syn_nsw'"
        ).fetchone()[0]
        == 0
    )
