"""C03 NSW projection checks on PostgreSQL 16.

All test rows are synthetic and rolled back.
"""

from __future__ import annotations

import os

import pytest


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

        required_objects = (
            "meta.source",
            "meta.resource",
            "raw.record",
        )

        for table in required_objects:
            assert conn.execute(
                "SELECT to_regclass(%s)",
                (table,),
            ).fetchone()[0], table

        # C03 reuses A05's shared business-key encoder.
        function_exists = conn.execute(
            """
            SELECT to_regprocedure(
                'rv.encode_business_key(text[])'
            )
            """
        ).fetchone()[0]

        assert function_exists, (
            "rv.encode_business_key(text[]) is not installed"
        )

        conn.rollback()

        yield conn

    finally:
        conn.rollback()
        conn.close()
