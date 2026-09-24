"""Shared PostgreSQL 16 fixture for Role D fault-injection acceptance."""

from contextlib import contextmanager
import os

import pytest


@pytest.fixture
def connection():
    """Use one owner session while application calls run as arsia_loader."""

    dsn = os.environ.get("ARSIA_TEST_ADMIN_DSN")
    if not dsn:
        pytest.fail(
            "D acceptance requires an isolated ARSIA_TEST_ADMIN_DSN",
            pytrace=False,
        )
    try:
        import psycopg
    except ImportError as exc:
        pytest.fail(
            f"Cannot import the PostgreSQL driver ({type(exc).__name__})",
            pytrace=False,
        )
    try:
        conn = psycopg.connect(dsn, autocommit=False, connect_timeout=10)
    except psycopg.Error as exc:
        pytest.fail(
            f"Cannot open the D acceptance database ({type(exc).__name__})",
            pytrace=False,
        )
    try:
        assert conn.info.server_version // 10000 == 16
        conn.execute("SET ROLE arsia_loader")
        identity = conn.execute(
            "SELECT current_user,session_user,current_setting('TimeZone')"
        ).fetchone()
        assert identity == ("arsia_loader", "arsia_owner", "UTC")
        assert conn.execute(
            "SELECT has_table_privilege(current_user,'dw.fact_crash','UPDATE')"
        ).fetchone() == (False,)
        yield conn
    finally:
        conn.rollback()
        conn.close()


@contextmanager
def fault_injection(connection):
    """Temporarily use the test owner without changing application privileges."""

    connection.execute("RESET ROLE")
    assert connection.execute(
        "SELECT current_user=session_user"
    ).fetchone() == (True,)
    try:
        yield connection
    finally:
        connection.execute("SET ROLE arsia_loader")
