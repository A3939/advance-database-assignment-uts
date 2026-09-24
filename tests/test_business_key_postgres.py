"""Opt-in PostgreSQL checks for the shared business-key encoder."""
from __future__ import annotations

import os

import pytest

from test_raw_load_postgres import connection


pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="Real PostgreSQL tests require A's migrated database and ARSIA_TEST_DSN",
)


def test_business_key_examples_preserve_text_and_order(connection):
    row = connection.execute(
        "SELECT rv.encode_business_key(%s) AS crash_key, "
        "rv.encode_business_key(%s, %s) AS unit_key, "
        "rv.encode_business_key(%s, %s) AS reversed_key, "
        "rv.encode_business_key(%s, %s) AS case_variant",
        ("0001", "AbC", "001", "001", "AbC", "abc", "001"),
    ).fetchone()

    assert row == (
        '["0001"]',
        '["AbC", "001"]',
        '["001", "AbC"]',
        '["abc", "001"]',
    )
    assert row[1] != row[2]
    assert row[1] != row[3]


@pytest.mark.parametrize("components", [[], [None], [""], ["   "]])
def test_business_key_rejects_missing_or_blank_components(connection, components):
    import psycopg

    with pytest.raises(psycopg.errors.InvalidParameterValue):
        with connection.transaction():
            connection.execute(
                "SELECT rv.encode_business_key(VARIADIC %s::text[])",
                (components,),
            ).fetchone()


def test_business_key_execute_permission_is_loader_only(connection):
    privileges = connection.execute(
        "SELECT "
        "has_function_privilege('arsia_loader', "
        "'rv.encode_business_key(text[])', 'EXECUTE'), "
        "has_function_privilege('arsia_reader', "
        "'rv.encode_business_key(text[])', 'EXECUTE')"
    ).fetchone()

    assert privileges == (True, False)
