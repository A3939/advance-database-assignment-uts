"""Regression checks against the CHECK constraints installed by A's migrations."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from test_raw_load_postgres import connection


pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="Requires PostgreSQL 16 with migrations 001-011 and ARSIA_TEST_DSN",
)


@pytest.fixture
def crash_checks(connection):
    # Copy the actual installed constraints; do not restate the CHECK expression.
    # Foreign keys are outside this test's scope and are not copied by LIKE.
    connection.execute(
        "CREATE TEMP TABLE crash_checks "
        "(LIKE canonical.crash INCLUDING DEFAULTS INCLUDING CONSTRAINTS)"
    )
    connection.execute(
        "INSERT INTO crash_checks "
        "(batch_id, source_id, release_scope, crash_key, raw_record_id, "
        "occurrence_year, date_precision, severity_code, severity_definition_version, "
        "latitude, longitude, location_crs, map_eligible, location_record_id) "
        "VALUES (%s, 'syn_check', 'test', '[\"0001\"]', %s, "
        "2024, 'year', 'UNKNOWN', 'test', -33.86, 151.21, NULL, false, %s)",
        (uuid4(), uuid4(), uuid4()),
    )
    return connection


def test_map_eligible_requires_nonnull_crs(crash_checks):
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation) as error:
        with crash_checks.transaction():
            crash_checks.execute("UPDATE crash_checks SET map_eligible = true")
    assert error.value.diag.constraint_name == "canonical_crash_map_eligibility_valid"


def test_map_eligible_accepts_confirmed_wgs84(crash_checks):
    crash_checks.execute(
        "UPDATE crash_checks SET location_crs = 'EPSG:4326', map_eligible = true"
    )
    assert crash_checks.execute(
        "SELECT map_eligible FROM crash_checks"
    ).fetchone() == (True,)


def test_map_eligible_rejects_wrong_crs(crash_checks):
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation) as error:
        with crash_checks.transaction():
            crash_checks.execute(
                "UPDATE crash_checks SET location_crs = 'EPSG:4283', map_eligible = true"
            )
    assert error.value.diag.constraint_name == "canonical_crash_map_eligibility_valid"


def test_unmapped_crash_can_keep_unknown_location(crash_checks):
    crash_checks.execute(
        "UPDATE crash_checks SET latitude = NULL, longitude = NULL, "
        "location_crs = NULL, location_record_id = NULL"
    )
    assert crash_checks.execute(
        "SELECT map_eligible FROM crash_checks"
    ).fetchone() == (False,)
