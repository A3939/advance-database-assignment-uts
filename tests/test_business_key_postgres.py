"""Opt-in PostgreSQL checks for the shared business-key encoder."""
from __future__ import annotations

import os
import json

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


@pytest.mark.parametrize(
    "components",
    [None, [], [None], [""], ["   "], ["\t"], ["\n"], [" \t\r\n\f\v"],
     ["0001", "\t\n"], ["\t", "001"], ["\u00a0\u2003\u3000"]],
)
def test_business_key_rejects_missing_or_blank_components(connection, components):
    import psycopg

    with pytest.raises(psycopg.errors.InvalidParameterValue):
        with connection.transaction():
            connection.execute(
                "SELECT rv.encode_business_key(VARIADIC %s::text[])",
                (components,),
            ).fetchone()


@pytest.mark.parametrize(
    "codepoint",
    [9, 10, 11, 12, 13, 28, 29, 30, 31, 32, 133, 160, 5760,
     *range(8192, 8203), 8232, 8233, 8239, 8287, 12288],
)
def test_business_key_rejects_each_whitespace_character(connection, codepoint):
    import psycopg

    with pytest.raises(psycopg.errors.InvalidParameterValue):
        with connection.transaction():
            connection.execute("SELECT rv.encode_business_key(%s)", (chr(codepoint),))


def test_business_key_keeps_valid_whitespace_quotes_and_unicode(connection):
    components = [" \tAbC001\n", 'a"b\\c', "\u00a0零01\u3000"]
    encoded = connection.execute(
        "SELECT rv.encode_business_key(VARIADIC %s::text[])", (components,)
    ).fetchone()[0]
    assert json.loads(encoded) == components


def test_business_key_execute_permission_is_loader_only(connection):
    privileges = connection.execute(
        "SELECT "
        "has_function_privilege('arsia_loader', "
        "'rv.encode_business_key(text[])', 'EXECUTE'), "
        "has_function_privilege('arsia_reader', "
        "'rv.encode_business_key(text[])', 'EXECUTE')"
    ).fetchone()

    assert privileges == (True, False)
