"""Proposed FP1 jsonb-to-text adapter; E must register the real SQL interface."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from .models import IntakeError


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}\Z")
_VERSION = re.compile(r"[A-Za-z0-9._-]+\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class FP1Operation:
    """E's declared binding, not a database deployment/version certificate."""

    schema: str
    name: str
    implementation_version: str
    postgres_version_num: int
    code_path: str
    protocol: str = "FP1"


def _check_binding(operation):
    if not isinstance(operation, FP1Operation):
        raise IntakeError("FP1_BINDING", "Expected an explicit FP1Operation from E")
    for value in (operation.schema, operation.name):
        if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
            raise IntakeError("FP1_BINDING", "Invalid SQL schema or function name")
    if (operation.protocol != "FP1" or not isinstance(operation.implementation_version, str)
            or not _VERSION.fullmatch(operation.implementation_version)):
        raise IntakeError("FP1_BINDING", "FP1 protocol and implementation version are required")
    if (type(operation.postgres_version_num) is not int
            or not 160000 <= operation.postgres_version_num < 170000):
        raise IntakeError("FP1_BINDING", "Pin the agreed PostgreSQL 16 server_version_num")
    path = operation.code_path
    if (not isinstance(path, str) or not path or "\\" in path or "\x00" in path
            or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts
            or str(PurePosixPath(path)) != path):
        raise IntakeError("FP1_BINDING", "code_path must be a relative project path")


def _check_code(operation, manifest, project_root):
    files = manifest.get("rules", {}).get("code_files", [])
    matches = [item for item in files if item.get("path") == operation.code_path]
    if len(matches) != 1 or not _SHA256.fullmatch(str(matches[0].get("sha256", ""))):
        raise IntakeError("FP1_CODE", "FP1 SQL must appear once in frozen rules.code_files")
    try:
        root = Path(project_root).resolve(strict=True)
        path = (root / operation.code_path).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise IntakeError("FP1_CODE", "FP1 SQL must be a file inside the project")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError as exc:
        raise IntakeError("FP1_CODE", "Cannot read the frozen FP1 SQL file") from exc
    if actual != matches[0]["sha256"]:
        raise IntakeError("FP1_CODE", "FP1 SQL bytes differ from the frozen manifest")


def _one_row(cursor, code, message):
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise IntakeError(code, message)
    return rows[0]


def fingerprint(connection, frozen_manifest, operation=None, *, project_root):
    """Call E's registered SQL using the supplied transaction; never commit.

    The proposed signature accepts normalized FP1 input as jsonb and returns text.
    It still needs E's confirmation and real PostgreSQL verification. The local
    code check binds the declared SQL file; it does not attest installed SQL bytes.
    """
    if operation is None:
        raise IntakeError("FP1_UNAVAILABLE", "E's FP1 SQL operation has not been registered")
    _check_binding(operation)
    if getattr(connection, "autocommit", None) is not False:
        raise IntakeError("FP1_AUTOCOMMIT", "FP1 requires the caller's transaction with autocommit disabled")
    manifest = frozen_manifest.as_dict()
    _check_code(operation, manifest, project_root)
    payload = json.dumps(frozen_manifest.fingerprint_input(), ensure_ascii=False, allow_nan=False)
    with connection.cursor() as cursor:
        cursor.execute("""SELECT current_setting('server_version_num'),
            current_setting('server_encoding'), current_setting('client_encoding'),
            current_setting('TimeZone')""")
        row = _one_row(cursor, "FP1_ENVIRONMENT", "Cannot verify the FP1 database environment")
        if (len(row) != 4 or str(row[0]) != str(operation.postgres_version_num)
                or tuple(row[1:]) != ("UTF8", "UTF8", "UTC")):
            raise IntakeError("FP1_ENVIRONMENT", "FP1 needs the pinned PostgreSQL 16 version, UTF8 and UTC")
        cursor.execute("""SELECT p.prorettype = 'pg_catalog.text'::pg_catalog.regtype
                AND NOT p.proretset AND p.prokind = 'f'
                AND pg_catalog.has_function_privilege(p.oid, 'EXECUTE')
            FROM pg_catalog.pg_proc AS p
            JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
            WHERE n.nspname = %s AND p.proname = %s AND p.pronargs = 1
                AND p.proargtypes[0] = 'pg_catalog.jsonb'::pg_catalog.regtype""",
                       (operation.schema, operation.name))
        row = _one_row(cursor, "FP1_UNAVAILABLE", "The registered FP1(jsonb) function is unavailable")
        if len(row) != 1 or row[0] is not True:
            raise IntakeError("FP1_UNAVAILABLE", "FP1 must be an executable jsonb-to-text scalar function")
        qualified_name = f'"{operation.schema}"."{operation.name}"'
        cursor.execute(f"SELECT {qualified_name}(%s::jsonb)", (payload,))
        row = _one_row(cursor, "FP1_RESULT", "FP1 must return one fingerprint")
        if len(row) != 1 or not isinstance(row[0], str) or not _SHA256.fullmatch(row[0]):
            raise IntakeError("FP1_RESULT", "FP1 must return 64 lowercase hexadecimal characters")
        return row[0]
