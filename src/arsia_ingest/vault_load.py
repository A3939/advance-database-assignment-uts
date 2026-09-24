"""Load C's typed session projections into A's five Raw Vault tables."""
from __future__ import annotations

from dataclasses import dataclass
import json

from .models import IntakeError


CRASH_PROJECTION = "pg_temp.arsia_i_crash"
UNIT_PROJECTION = "pg_temp.arsia_i_unit"

CRASH_COLUMNS = (
    ("batch_id", "uuid", True),
    ("source_id", "text", True),
    ("release_scope", "text", True),
    ("crash_key", "text", True),
    ("raw_record_id", "uuid", True),
    ("occurrence_year", "integer", True),
    ("occurrence_month", "integer", False),
    ("occurrence_date", "date", False),
    ("date_precision", "text", True),
    ("severity_raw", "text", False),
    ("severity_code", "text", True),
    ("severity_definition_version", "text", True),
    ("is_fatal_crash", "boolean", False),
    ("fatality_count", "integer", False),
    ("casualty_count", "integer", False),
    ("fatal_crash_eligible", "boolean", True),
    ("fatality_eligible", "boolean", True),
    ("casualty_eligible", "boolean", True),
    ("latitude", "numeric(10,7)", False),
    ("longitude", "numeric(10,7)", False),
    ("location_crs", "text", False),
    ("map_eligible", "boolean", True),
    ("location_record_id", "uuid", False),
    ("quality_notes", "jsonb", True),
)

UNIT_COLUMNS = (
    ("batch_id", "uuid", True),
    ("source_id", "text", True),
    ("release_scope", "text", True),
    ("unit_key", "text", True),
    ("crash_key", "text", True),
    ("raw_record_id", "uuid", True),
    ("unit_type_raw", "text", False),
    ("unit_type_code", "text", False),
    ("statistical_scope", "text", True),
    ("count_eligible", "boolean", True),
    ("quality_notes", "jsonb", True),
)


@dataclass(frozen=True)
class VaultLoadResult:
    crash_count: int
    unit_count: int
    crash_hubs_inserted: int
    unit_hubs_inserted: int
    crash_satellites_inserted: int
    unit_satellites_inserted: int
    links_inserted: int


def _rows(connection, sql, parameters=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, parameters)
        return cursor.fetchall()


def _command(connection, sql, parameters=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, parameters)
        return cursor.rowcount


def _scalar(connection, sql, parameters=None):
    rows = _rows(connection, sql, parameters)
    if len(rows) != 1 or len(rows[0]) != 1:
        raise IntakeError("VAULT_QUERY", "Vault validation returned an unexpected shape")
    return rows[0][0]


def _validate_projection_table(connection, table, expected):
    relation = _rows(
        connection,
        """SELECT c.relpersistence, c.relkind, n.oid = pg_my_temp_schema()
           FROM pg_class AS c
           JOIN pg_namespace AS n ON n.oid = c.relnamespace
           WHERE c.oid = to_regclass(%s)""",
        (table,),
    )
    if relation != [("t", "r", True)]:
        raise IntakeError(
            "VAULT_PROJECTION",
            "C must provide the required session-local projection table",
            table=table,
        )
    actual = _rows(
        connection,
        """SELECT a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod), a.attnotnull
           FROM pg_attribute AS a
           WHERE a.attrelid = to_regclass(%s)
             AND a.attnum > 0
             AND NOT a.attisdropped
           ORDER BY a.attnum""",
        (table,),
    )
    if actual != list(expected):
        raise IntakeError(
            "VAULT_PROJECTION",
            "Projection columns, order, types and NULL rules must match the C-to-A contract",
            table=table,
            expected=[list(item) for item in expected],
            actual=[list(item) for item in actual],
        )


def _validate_scope(connection, context, table):
    manifest = context.manifest.as_dict()
    allowed = {(source["source_id"], source["release_scope"])
               for source in manifest["sources"]}
    scopes = _rows(
        connection,
        f"SELECT DISTINCT batch_id::text, source_id, release_scope FROM {table}",
    )
    invalid = [row for row in scopes
               if row[0] != str(context.batch_id) or (row[1], row[2]) not in allowed]
    if invalid:
        raise IntakeError(
            "VAULT_SCOPE",
            "Projection rows must belong to this batch and a frozen source release",
            table=table,
            invalid_scopes=[list(row) for row in invalid],
        )


def _validate_unique_keys(connection):
    checks = (
        (CRASH_PROJECTION, "batch_id, source_id, release_scope, crash_key"),
        (UNIT_PROJECTION, "batch_id, source_id, release_scope, unit_key"),
    )
    for table, columns in checks:
        duplicates = _scalar(
            connection,
            f"""SELECT count(*)
                FROM (SELECT 1 FROM {table}
                      GROUP BY {columns} HAVING count(*) > 1) AS duplicate_keys""",
        )
        if duplicates:
            raise IntakeError(
                "VAULT_DUPLICATE_KEY",
                "Projection contains duplicate complete business keys",
                table=table,
                duplicate_groups=duplicates,
            )


def _validate_parents(connection):
    orphans = _scalar(
        connection,
        f"""SELECT count(*)
            FROM {UNIT_PROJECTION} AS u
            LEFT JOIN {CRASH_PROJECTION} AS c
              ON c.batch_id = u.batch_id
             AND c.source_id = u.source_id
             AND c.release_scope = u.release_scope
             AND c.crash_key = u.crash_key
            WHERE c.crash_key IS NULL""",
    )
    if orphans:
        raise IntakeError(
            "VAULT_ORPHAN_UNIT",
            "Every projected real unit needs its complete parent crash in the same scope",
            orphan_count=orphans,
        )


def _validate_projection_values(connection):
    invalid_crashes = _scalar(
        connection,
        f"""SELECT count(*) FROM {CRASH_PROJECTION}
            WHERE occurrence_year NOT BETWEEN 1900 AND 2100
               OR date_precision NOT IN ('year', 'month', 'day')
               OR (date_precision = 'year' AND
                   (occurrence_month IS NOT NULL OR occurrence_date IS NOT NULL))
               OR (date_precision = 'month' AND (occurrence_month IS NULL
                    OR occurrence_month NOT BETWEEN 1 AND 12 OR occurrence_date IS NOT NULL))
               OR (date_precision = 'day' AND (occurrence_month IS NULL
                    OR occurrence_month NOT BETWEEN 1 AND 12
                    OR occurrence_date IS NULL
                    OR extract(year FROM occurrence_date) <> occurrence_year
                    OR extract(month FROM occurrence_date) <> occurrence_month))
               OR fatality_count < 0 OR casualty_count < 0
               OR (fatal_crash_eligible AND is_fatal_crash IS NULL)
               OR (fatality_eligible AND fatality_count IS NULL)
               OR (casualty_eligible AND casualty_count IS NULL)
               OR (map_eligible AND (latitude IS NULL OR longitude IS NULL
                    OR latitude NOT BETWEEN -90 AND 90
                    OR longitude NOT BETWEEN -180 AND 180
                    OR location_crs IS DISTINCT FROM 'EPSG:4326'
                    OR location_record_id IS NULL))
               OR (NOT map_eligible AND (latitude IS NOT NULL OR longitude IS NOT NULL
                    OR location_crs IS NOT NULL OR location_record_id IS NOT NULL))
               OR jsonb_typeof(quality_notes) <> 'object'""",
    )
    invalid_units = _scalar(
        connection,
        f"""SELECT count(*) FROM {UNIT_PROJECTION}
            WHERE btrim(statistical_scope) = ''
               OR (count_eligible AND
                    (unit_type_code IS NULL OR btrim(unit_type_code) = ''))
               OR jsonb_typeof(quality_notes) <> 'object'""",
    )
    if invalid_crashes or invalid_units:
        raise IntakeError(
            "VAULT_INVALID_PROJECTION",
            "Projection violates the agreed core type, NULL or eligibility rules",
            invalid_crash_count=invalid_crashes,
            invalid_unit_count=invalid_units,
        )


def _validate_lineage(connection, context):
    manifest = context.manifest.as_dict()

    def selected(kinds):
        return [
            {
                "source_id": item["source_id"],
                "resource_id": item["resource_id"],
                "file_sha256": item["file_sha256"],
                "parser_version": item["parser_version"],
            }
            for item in manifest["files"]
            if item["entity_kind"] in kinds
        ]

    checks = (
        (CRASH_PROJECTION, "raw_record_id", selected({"crash"})),
        (UNIT_PROJECTION, "raw_record_id", selected({"unit"})),
        (CRASH_PROJECTION, "location_record_id", selected({"crash", "node_raw"})),
    )
    for table, column, allowed in checks:
        nullable = column == "location_record_id"
        invalid = _scalar(
            connection,
            f"""WITH allowed AS (
                    SELECT source_id, resource_id, file_sha256, parser_version
                    FROM jsonb_to_recordset(%s::jsonb) AS selected(
                        source_id text, resource_id text,
                        file_sha256 text, parser_version text)
                )
                SELECT count(*)
                FROM {table} AS p
                LEFT JOIN raw.record AS r
                  ON r.raw_record_id = p.{column}
                 AND r.source_id = p.source_id
                LEFT JOIN allowed AS a
                  ON a.source_id = r.source_id
                 AND a.resource_id = r.resource_id
                 AND a.file_sha256 = r.file_sha256
                 AND a.parser_version = r.parser_version
                WHERE {'p.' + column + ' IS NOT NULL AND ' if nullable else ''}
                      (r.raw_record_id IS NULL OR a.resource_id IS NULL)""",
            (json.dumps(allowed),),
        )
        if invalid:
            raise IntakeError(
                "VAULT_LINEAGE",
                "Projection lineage must reference the selected Raw file "
                "and parser of the correct kind",
                table=table,
                column=column,
                invalid_count=invalid,
            )


def validate_projections(connection, context):
    """Validate C's two temporary projection tables without writing Vault rows."""
    _validate_projection_table(connection, CRASH_PROJECTION, CRASH_COLUMNS)
    _validate_projection_table(connection, UNIT_PROJECTION, UNIT_COLUMNS)
    _validate_scope(connection, context, CRASH_PROJECTION)
    _validate_scope(connection, context, UNIT_PROJECTION)
    _validate_unique_keys(connection)
    _validate_parents(connection)
    _validate_projection_values(connection)
    _validate_lineage(connection, context)


def load_vault(connection, context):
    """B10 vault callback: validate and append one batch without committing."""
    validate_projections(connection, context)
    crash_count = _scalar(connection, f"SELECT count(*) FROM {CRASH_PROJECTION}")
    unit_count = _scalar(connection, f"SELECT count(*) FROM {UNIT_PROJECTION}")

    crash_hubs = _command(
        connection,
        f"""INSERT INTO rv.hub_crash(source_id, release_scope, crash_key, first_seen_batch_id)
            SELECT source_id, release_scope, crash_key, batch_id
            FROM {CRASH_PROJECTION}
            ON CONFLICT (source_id, release_scope, crash_key) DO NOTHING""",
    )
    unit_hubs = _command(
        connection,
        f"""INSERT INTO rv.hub_unit(source_id, release_scope, unit_key, first_seen_batch_id)
            SELECT source_id, release_scope, unit_key, batch_id
            FROM {UNIT_PROJECTION}
            ON CONFLICT (source_id, release_scope, unit_key) DO NOTHING""",
    )
    crash_satellites = _command(
        connection,
        f"""INSERT INTO rv.sat_crash(
                batch_id, source_id, release_scope, crash_key, raw_record_id, attributes)
            SELECT batch_id, source_id, release_scope, crash_key, raw_record_id,
                   to_jsonb(p) - ARRAY['batch_id', 'source_id', 'release_scope',
                                             'crash_key', 'raw_record_id']
            FROM {CRASH_PROJECTION} AS p""",
    )
    unit_satellites = _command(
        connection,
        f"""INSERT INTO rv.sat_unit(
                batch_id, source_id, release_scope, unit_key, raw_record_id, attributes)
            SELECT batch_id, source_id, release_scope, unit_key, raw_record_id,
                   to_jsonb(p) - ARRAY['batch_id', 'source_id', 'release_scope',
                                             'unit_key', 'raw_record_id']
            FROM {UNIT_PROJECTION} AS p""",
    )
    links = _command(
        connection,
        f"""INSERT INTO rv.link_crash_unit(
                batch_id, source_id, release_scope, unit_key, crash_key)
            SELECT batch_id, source_id, release_scope, unit_key, crash_key
            FROM {UNIT_PROJECTION}""",
    )
    result = VaultLoadResult(
        crash_count, unit_count, crash_hubs, unit_hubs,
        crash_satellites, unit_satellites, links,
    )
    context.evidence.write_json("counts.json", result.__dict__)
    return result


def iter_satellites(connection, context, entity_kind, *, fetch_size=1000):
    """Yield this candidate's selected Satellites for C09 without reading Raw."""
    if entity_kind == "crash":
        sql = """SELECT batch_id, source_id, release_scope, crash_key,
                        raw_record_id, attributes
                 FROM rv.sat_crash
                 WHERE batch_id = %s::uuid
                 ORDER BY source_id, release_scope, crash_key"""
        names = ("batch_id", "source_id", "release_scope", "crash_key",
                 "raw_record_id", "attributes")
    elif entity_kind == "unit":
        sql = """SELECT s.batch_id, s.source_id, s.release_scope, s.unit_key,
                        l.crash_key, s.raw_record_id, s.attributes
                 FROM rv.sat_unit AS s
                 JOIN rv.link_crash_unit AS l
                   USING (batch_id, source_id, release_scope, unit_key)
                 WHERE s.batch_id = %s::uuid
                 ORDER BY s.source_id, s.release_scope, s.unit_key"""
        names = ("batch_id", "source_id", "release_scope", "unit_key",
                 "crash_key", "raw_record_id", "attributes")
    else:
        raise IntakeError("VAULT_ENTITY", "Satellite kind must be crash or unit")
    if not isinstance(fetch_size, int) or fetch_size < 1:
        raise IntakeError("VAULT_FETCH", "Satellite fetch size must be a positive integer")
    with connection.cursor() as cursor:
        cursor.execute(sql, (str(context.batch_id),))
        while rows := cursor.fetchmany(fetch_size):
            for row in rows:
                yield dict(zip(names, row, strict=True))
