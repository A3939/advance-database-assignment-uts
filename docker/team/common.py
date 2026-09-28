"""Install and check the team database without clearing existing work."""

from __future__ import annotations

import hashlib
import importlib
from importlib.resources import files
import json
import os
from pathlib import Path
import sys

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = "docker/team/vendor/a/config/schema-v1.1.json"
SOURCES_PATH = "docker/team/sources.json"
STAMP_VERSION = "arsia-team-database-v1"
ROLES = {"owner": "arsia_owner", "loader": "arsia_loader", "reader": "arsia_reader"}
PASSWORDS = {"owner": "ARSIA_DB_PASSWORD", "loader": "ARSIA_LOADER_PASSWORD",
             "reader": "ARSIA_READER_PASSWORD"}
SCHEMAS = ("meta", "raw", "rv", "canonical", "dw", "qa")
LOCK_KEY = (32113, 2)


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False,
                                    allow_nan=False) + "\n", encoding="utf-8")


def _json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _password(role):
    value = os.environ.get(PASSWORDS[role])
    if not value or value.startswith("REPLACE_") or "\x00" in value:
        raise ValueError(f"Set a nonempty {PASSWORDS[role]} locally")
    return value


def dsn(role="owner"):
    if role not in ROLES:
        raise ValueError("Expected owner, loader or reader")
    return make_conninfo(host=os.environ.get("ARSIA_DB_HOST", "db"),
                         port=5432, dbname="arsia", user=ROLES[role],
                         password=_password(role), connect_timeout=10)


def connect(role="owner"):
    """Return a dedicated session; the build runner owns its transactions."""
    return psycopg.connect(dsn(role))


def _file_record(record):
    path = (ROOT / record["path"]).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        raise ValueError("Missing or unsafe locked file: " + record["path"])
    if _hash(path) != record["sha256"]:
        raise ValueError("Locked file changed: " + record["path"])


def check_installation():
    """Check source inputs and installed wheel bytes before using the database."""
    from docker.team.provenance import verify_installed
    provenance = verify_installed(ROOT, os.environ.get('ARSIA_IMAGE_REVISION', ''))
    if sys.version_info[:2] != (3, 12):
        raise ValueError("The team runtime requires Python 3.12")
    lock = _json(SOURCES_PATH)
    for group in ("files", "overlays"):
        for record in lock[group]:
            _file_record(record)
    checked = {}
    for name in ("build", "d09"):
        inventory = _json(f"config/{name}-inventory.json")
        for group in ("code_files", "schema_files"):
            for record in inventory.get(group, []):
                _file_record(record)
                checked[record["path"]] = record["sha256"]
    migrations = sorted((ROOT / "sql/migrations").glob("*.sql"))
    if [p.name[:3] for p in migrations] != [f"{n:03}" for n in range(1, 12)]:
        raise ValueError("Expected exactly A migrations 001-011")
    schema_paths = {r["path"] for r in _json("config/build-inventory.json")["schema_files"]}
    if schema_paths != {p.relative_to(ROOT).as_posix() for p in migrations}:
        raise ValueError("The schema inventory must contain all eleven migrations")
    packages = {}
    installed = []
    for source in sorted((ROOT / "src").rglob("*")):
        if source.suffix not in {".py", ".sql", ".json", ".html", ".css"}:
            continue
        relative = source.relative_to(ROOT / "src")
        name = relative.parts[0]
        if name not in packages:
            package = importlib.import_module(name)
            location = Path(package.__file__).resolve().parent
            if location.is_relative_to(ROOT.resolve()) or not location.is_relative_to(Path(sys.prefix).resolve()):
                raise ValueError("Use the installed wheel, not imports from the source checkout")
            packages[name] = location
        target = packages[name].joinpath(*relative.parts[1:])
        if not target.is_file() or _hash(target) != _hash(source):
            raise ValueError("Installed package differs: " + relative.as_posix())
        installed.append(relative.as_posix())
    return {"status": "passed", "locked_files": len(lock["files"]) + len(lock["overlays"]),
            "inventory_files": len(checked), "installed_files": installed,
            "git_provenance": provenance,
            "sources_sha256": _hash(ROOT / SOURCES_PATH)}


def _environment(connection, role="owner"):
    actual = connection.execute("""SELECT current_setting('server_version_num'),
        current_setting('server_encoding'), current_setting('client_encoding'),
        current_setting('TimeZone'), current_database(), current_user, session_user""").fetchone()
    expected = ("160015", "UTF8", "UTF8", "UTC", "arsia", ROLES[role], ROLES[role])
    if actual != expected:
        raise ValueError("Expected PostgreSQL 16.15, UTF8, UTC and the selected real role login")
    return {"server_version_num": 160015, "encoding": "UTF8", "timezone": "UTC",
            "database": "arsia", "user": ROLES[role]}


def _catalog(connection):
    rows = connection.execute("""SELECT n.nspname||'.'||c.relname,
        (SELECT jsonb_agg(jsonb_build_array(a.attname,pg_catalog.format_type(a.atttypid,a.atttypmod),
                                   NOT a.attnotnull) ORDER BY a.attnum)
         FROM pg_attribute a WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped),
        pg_get_userbyid(c.relowner),ARRAY(SELECT x::text FROM unnest(c.relacl) x ORDER BY x::text)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=ANY(%s) AND c.relkind IN ('r','p')
        ORDER BY 1""", (list(SCHEMAS),)).fetchall()
    constraints = connection.execute("""SELECT n.nspname||'.'||r.relname,c.conname,
        c.contype,pg_get_constraintdef(c.oid),c.convalidated
        FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace
        JOIN pg_class r ON r.oid=c.conrelid
        WHERE n.nspname=ANY(%s) ORDER BY 1,2""", (list(SCHEMAS),)).fetchall()
    names = {"c": "check", "f": "foreign_key", "p": "primary_key", "u": "unique"}
    counts = {name: sum(row[2] == kind for row in constraints) for kind, name in names.items()}
    owners = dict(connection.execute("""SELECT nspname,pg_get_userbyid(nspowner)
        FROM pg_namespace WHERE nspname=ANY(%s) ORDER BY nspname""",
        ([*SCHEMAS, "published"],)).fetchall())
    schema_acls = connection.execute("""SELECT nspname,ARRAY(SELECT x::text FROM unnest(nspacl) x ORDER BY x::text) FROM pg_namespace
        WHERE nspname=ANY(%s) ORDER BY nspname""", ([*SCHEMAS, "published", "e"],)).fetchall()
    column_acls = connection.execute("""SELECT n.nspname||'.'||c.relname,a.attname,
        ARRAY(SELECT x::text FROM unnest(a.attacl) x ORDER BY x::text)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_attribute a ON a.attrelid=c.oid
        WHERE n.nspname=ANY(%s) AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY 1,a.attnum""", (list(SCHEMAS),)).fetchall()
    functions = connection.execute("""SELECT p.oid::regprocedure::text,
        pg_get_userbyid(p.proowner),pg_get_functiondef(p.oid),
        ARRAY(SELECT x::text FROM unnest(p.proacl) x ORDER BY x::text)
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname IN ('rv','published','e') ORDER BY 1""").fetchall()
    views = connection.execute("""SELECT c.relname,pg_get_userbyid(c.relowner),
        ARRAY(SELECT x::text FROM unnest(c.relacl) x ORDER BY x::text),
        pg_get_viewdef(c.oid),c.reloptions
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='published' AND c.relkind='v' ORDER BY c.relname""").fetchall()
    defaults = connection.execute("""SELECT pg_get_userbyid(d.defaclrole),n.nspname,
        d.defaclobjtype,ARRAY(SELECT x::text FROM unnest(d.defaclacl) x ORDER BY x::text) FROM pg_default_acl d
        LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace
        WHERE d.defaclrole=(SELECT oid FROM pg_roles WHERE rolname='arsia_migrator')
        ORDER BY 1,2,3""").fetchall()
    return {"tables": {r[0]: r[1] for r in rows}, "table_owners": {r[0]: r[2] for r in rows},
            "constraint_counts": counts, "constraints": [list(r) for r in constraints],
            "schema_owners": owners, "functions": [list(r) for r in functions],
            "table_acls": {r[0]: r[3] for r in rows},
            "schema_acls": [list(r) for r in schema_acls],
            "column_acls": [list(r) for r in column_acls],
            "published_views": [list(r) for r in views],
            "default_acls": [list(r) for r in defaults]}


def _verify_catalog(actual):
    contract = _json(SCHEMA_PATH)
    if actual["tables"] != contract["tables"]:
        raise ValueError("Actual columns, order, types or NULL rules differ from A's schema")
    if actual["constraint_counts"] != contract["constraint_counts"]:
        raise ValueError("Actual constraints differ from A's schema")
    if any(not row[4] for row in actual["constraints"]):
        raise ValueError("An application constraint is not validated")
    if set(actual["table_owners"].values()) != {"arsia_migrator"}:
        raise ValueError("Application tables must remain owned by arsia_migrator")
    expected_owners = {name: "arsia_migrator" for name in [*SCHEMAS, "published"]}
    if actual["schema_owners"] != expected_owners:
        raise ValueError("Schema owners differ from A03")


def _catalog_hash(actual):
    return hashlib.sha256(json.dumps(actual, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _expected_stamp():
    return {"version": STAMP_VERSION,
            "build_inventory_sha256": _hash(ROOT / "config/build-inventory.json"),
            "dashboard_inventory_sha256": _hash(ROOT / "config/d09-inventory.json"),
            "schema_contract_sha256": _hash(ROOT / SCHEMA_PATH),
            "a03_audit_sha256": _hash(ROOT / "sql/tests/a03_database_roles.sql")}


def _stamp(connection):
    value = connection.execute("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()").fetchone()[0]
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Database has an unrecognized installation comment") from exc


def _require_stamp(stamp, expected, actual):
    if not isinstance(stamp, dict) or any(stamp.get(k) != v for k, v in expected.items()):
        raise ValueError("Database installation differs; use its matching image or a new project")
    if stamp.get("catalog_sha256") != _catalog_hash(actual) or stamp.get("a03_initial_audit") != "passed":
        raise ValueError("Database schema or installed SQL changed after initialization")


def _strip_psql(text):
    lines = []
    for line in text.splitlines():
        if line.strip() == r"\set ON_ERROR_STOP on":
            continue
        if line.lstrip().startswith("\\"):
            raise ValueError("Unsupported psql command in the A03 audit")
        lines.append(line)
    return "\n".join(lines) + "\n"


def _original_audit(connection):
    connection.execute(_strip_psql((ROOT / "sql/tests/a03_database_roles.sql").read_text(encoding="utf-8")))


def _deploy(connection):
    from arsia_ingest.build import fp1_sql
    from arsia_d05 import install_sql as trend
    from arsia_d06 import install_sql as severity
    from arsia_d07 import install_sql as maps
    from arsia_d08 import install_sql as units
    with connection.transaction():
        connection.execute(fp1_sql())
        connection.execute("SET LOCAL ROLE arsia_migrator")
        for installer in (trend, severity, maps, units):
            connection.execute(installer())
        connection.execute(files("arsia_d09").joinpath("sql/d09_context.sql").read_text(encoding="utf-8"))


def _fresh_database(connection):
    # Role names are cluster-wide; a foreign installation must not be adopted.
    schemas = connection.execute("""SELECT nspname FROM pg_namespace
        WHERE nspname NOT IN ('pg_catalog','information_schema','public')
          AND nspname NOT LIKE 'pg_toast%%' AND nspname NOT LIKE 'pg_temp%%'""").fetchall()
    objects = connection.execute("""SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S','f')""").fetchall()
    functions = connection.execute("""SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public'""").fetchall()
    roles = connection.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('arsia_loader','arsia_reader','arsia_migrator')").fetchall()
    if schemas or objects or functions or roles:
        raise ValueError("Refusing an unmarked or partially initialized database")


def initialize():
    installed = check_installation()
    expected = _expected_stamp()
    for role in ("owner", "loader", "reader"):
        _password(role)
    with connect("owner") as owner:
        owner.autocommit = True
        environment = _environment(owner)
        if not owner.execute("SELECT pg_try_advisory_lock(%s,%s)", LOCK_KEY).fetchone()[0]:
            raise ValueError("A build or initialization is running; try again later")
        stamp = _stamp(owner)
        if stamp is None:
            _fresh_database(owner)
            for path in sorted((ROOT / "sql/migrations").glob("*.sql")):
                owner.execute(path.read_text(encoding="utf-8"))
            for role in ("loader", "reader"):
                owner.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(ROLES[role]), sql.Literal(_password(role))))
            _original_audit(owner)
            _deploy(owner)
            actual = _catalog(owner)
            _verify_catalog(actual)
            stamp = {**expected, "catalog_sha256": _catalog_hash(actual), "a03_initial_audit": "passed"}
            owner.execute(sql.SQL("COMMENT ON DATABASE arsia IS {}").format(sql.Literal(json.dumps(stamp, sort_keys=True))))
            result = "initialized"
        else:
            actual = _catalog(owner)
            _verify_catalog(actual)
            _require_stamp(stamp, expected, actual)
            result = "already_initialized"
    return {"status": result, "environment": environment, "installation": installed,
            "stamp": stamp, "audit": audit()}


def table_counts():
    tables = sorted(_json(SCHEMA_PATH)["tables"])
    with connect("owner") as owner:
        _environment(owner)
        return {name: owner.execute(sql.SQL("SELECT count(*) FROM {}").format(
            sql.Identifier(*name.split(".")))).fetchone()[0] for name in tables}


def audit():
    """Recheck live privileges; only replay A03 inserts on an empty database."""
    with connect("owner") as owner:
        owner.autocommit = True
        _environment(owner)
        actual = _catalog(owner)
        _verify_catalog(actual)
        _require_stamp(_stamp(owner), _expected_stamp(), actual)
        roles = owner.execute("""SELECT rolname,rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls
            FROM pg_roles WHERE rolname IN ('arsia_loader','arsia_reader','arsia_migrator') ORDER BY rolname""").fetchall()
        expected = [(name, name != "arsia_migrator", False, False, False, False, False)
                    for name in sorted(("arsia_loader", "arsia_reader", "arsia_migrator"))]
        if roles != expected:
            raise ValueError("A03 role attributes changed")
        if owner.execute("SELECT pg_has_role('arsia_loader','arsia_migrator','MEMBER'),pg_has_role('arsia_reader','arsia_migrator','MEMBER')").fetchone() != (False, False):
            raise ValueError("Runtime roles must not inherit migration privileges")
        grants = owner.execute("""SELECT count(*) FILTER (WHERE has_table_privilege('arsia_loader',c.oid,'DELETE')),
            count(*) FILTER (WHERE has_table_privilege('arsia_reader',c.oid,'SELECT'))
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=ANY(%s) AND c.relkind IN ('r','p')""", (list(SCHEMAS),)).fetchone()
        if grants != (0, 0):
            raise ValueError("Runtime roles gained forbidden table access")
        counts = table_counts()
        original = "initialization record retained; current database contains application rows"
        if not any(counts.values()):
            if not owner.execute("SELECT pg_try_advisory_lock(%s,%s)", LOCK_KEY).fetchone()[0]:
                raise ValueError("A build is running; retry the empty-database audit later")
            # Recheck after taking the build lock before the fixed A03 test inserts.
            if any(table_counts().values()):
                raise ValueError("Database changed during audit; retry")
            _original_audit(owner)
            original = "passed on empty database; all test changes rolled back"
    sessions = {}
    for role in ("loader", "reader"):
        with connect(role) as connection:
            sessions[role] = _environment(connection, role)
            if role == "reader":
                connection.execute("SELECT * FROM published.current_release LIMIT 0")
                denied = "SELECT * FROM meta.batch LIMIT 0"
            else:
                connection.execute("SELECT * FROM meta.batch LIMIT 0")
                denied = "DELETE FROM meta.source WHERE false"
            try:
                with connection.transaction():
                    connection.execute(denied)
            except psycopg.errors.InsufficientPrivilege:
                pass
            else:
                raise ValueError(f"The {role} permission boundary was relaxed")
    return {"status": "passed", "tables": len(actual["tables"]),
            "columns": sum(map(len, actual["tables"].values())),
            "constraint_counts": actual["constraint_counts"], "roles": sessions,
            "original_a03": original, "a03_sha256": _expected_stamp()["a03_audit_sha256"]}
