"""C09 boundary checks; Raw is read only to verify identity/lineage, not measures."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
from uuid import UUID

from arsia_ingest.models import IntakeError


def reject(message, **details):
    raise IntakeError("CANONICAL_CONTRACT", message, **details)


def validate_values(a, entity):
    """Reject implicit SQL coercion and preserve the typed C01/05 contract."""
    strings = (
        {
            "severity_raw",
            "severity_code",
            "severity_definition_version",
            "date_precision",
            "location_crs",
        }
        if entity == "crash"
        else {"crash_key", "unit_type_raw", "unit_type_code", "statistical_scope"}
    )
    optional = {"severity_raw", "location_crs", "unit_type_raw", "unit_type_code"}
    for name in strings:
        value = a[name]
        if value is None and name in optional:
            continue
        if not isinstance(value, str) or (name not in optional and not value.strip()):
            reject("Satellite text attribute has the wrong type", field=name)
    bools = (
        (
            "is_fatal_crash",
            "fatal_crash_eligible",
            "fatality_eligible",
            "casualty_eligible",
            "map_eligible",
        )
        if entity == "crash"
        else ("count_eligible",)
    )
    for name in bools:
        if a[name] is None and name == "is_fatal_crash":
            continue
        if type(a[name]) is not bool:
            reject("Satellite flag must be a JSON boolean", field=name)
    if entity == "crash":
        for name in (
            "occurrence_year",
            "occurrence_month",
            "fatality_count",
            "casualty_count",
        ):
            value = a[name]
            if value is None and name != "occurrence_year":
                continue
            if type(value) is not int or not -(2**31) <= value < 2**31:
                reject("Satellite integer must not be rounded or coerced", field=name)
        value = a["occurrence_date"]
        if value is not None:
            try:
                if (
                    type(value) is not str
                    or date.fromisoformat(value).isoformat() != value
                ):
                    reject("Satellite date must be ISO YYYY-MM-DD")
            except ValueError:
                reject("Satellite date must be ISO YYYY-MM-DD")
        for name in ("latitude", "longitude"):
            value = a[name]
            if value is not None:
                if type(value) not in (int, float, Decimal):
                    reject("Satellite coordinate must be a JSON number", field=name)
                number = Decimal(str(value))
                limit = 90 if name == "latitude" else 180
                if (
                    not number.is_finite()
                    or abs(number) > limit
                    or number != number.quantize(Decimal("0.0000001"))
                ):
                    reject("Satellite coordinate would change when loaded", field=name)
        if a["location_record_id"] is not None:
            try:
                UUID(a["location_record_id"])
            except (ValueError, TypeError, AttributeError):
                reject("Satellite location lineage must be a UUID string")
    validate_notes(a["quality_notes"])
    if entity == "crash":
        if not 1900 <= a["occurrence_year"] <= 2100:
            reject("Occurrence year is outside the fixed domain")
        month, day, precision = (
            a["occurrence_month"],
            a["occurrence_date"],
            a["date_precision"],
        )
        if precision not in {"year", "month", "day"} or (
            month is not None and not 1 <= month <= 12
        ):
            reject("Date precision or month is invalid")
        if (
            (precision == "year" and (month is not None or day is not None))
            or (precision == "month" and (month is None or day is not None))
            or (
                precision == "day"
                and (
                    month is None
                    or day is None
                    or date.fromisoformat(day).year != a["occurrence_year"]
                    or date.fromisoformat(day).month != month
                )
            )
        ):
            reject("Satellite date precision is inconsistent")
        for name in ("fatality_count", "casualty_count"):
            if a[name] is not None and a[name] < 0:
                reject("Counts cannot be negative", field=name)
        for flag, value in (
            ("fatal_crash_eligible", "is_fatal_crash"),
            ("fatality_eligible", "fatality_count"),
            ("casualty_eligible", "casualty_count"),
        ):
            if a[flag] and a[value] is None:
                reject("Eligible measure has no known value", field=flag)
        location = [
            a[k]
            for k in ("latitude", "longitude", "location_crs", "location_record_id")
        ]
        if a["map_eligible"]:
            if any(v is None for v in location) or a["location_crs"] != "EPSG:4326":
                reject("Eligible map location is incomplete")
        elif (
            any(v is not None for v in location) or "location" not in a["quality_notes"]
        ):
            reject("Ineligible location must be cleared with a structured reason")
    elif a["count_eligible"] and (
        a["unit_type_code"] is None or not a["unit_type_code"].strip()
    ):
        reject("Eligible unit requires a known type code")


def validate_notes(notes):
    if not isinstance(notes, dict):
        reject("quality_notes must be an object")
    if "fields" in notes:
        if not isinstance(notes["fields"], list):
            reject("quality_notes.fields must be an array")
        for item in notes["fields"]:
            required = {"field", "reason_code", "raw_token", "contract_version"}
            if not isinstance(item, dict) or not required <= item.keys():
                reject("quality_notes.fields requires structured reasons")
            if any(
                not isinstance(item[k], str) or not item[k].strip()
                for k in required - {"raw_token"}
            ):
                reject("Field reason metadata must be nonempty text")
    if "location" in notes:
        item = notes["location"]
        required = {
            "reason_code",
            "candidate_raw_record_ids",
            "resolution",
            "evidence_ref",
        }
        if not isinstance(item, dict) or not required <= item.keys():
            reject("quality_notes.location requires structured location evidence")
        if any(
            not isinstance(item[k], str) or not item[k].strip()
            for k in required - {"candidate_raw_record_ids"}
        ):
            reject("Location reason metadata must be nonempty text")
        if not isinstance(item["candidate_raw_record_ids"], list):
            reject("Location candidates must be an array")
        try:
            for value in item["candidate_raw_record_ids"]:
                UUID(value)
        except (ValueError, TypeError, AttributeError):
            reject("Location candidates must be UUID strings")
    if "references" in notes and not isinstance(notes["references"], list):
        reject("quality_notes.references must be an array")


def selected_contracts(manifest):
    """Resolve selected file identities and native key/parent fields from B09."""
    sources = {s["source_id"]: s for s in manifest["sources"]}
    if len(sources) != len(manifest["sources"]):
        reject("Each selected source must have exactly one release scope")
    contracts = manifest.get("rules", {}).get("contracts", [])
    selected, seen = [], set()
    for file in manifest["files"]:
        if file["entity_kind"] not in {"crash", "unit", "node_raw"}:
            continue
        identity = tuple(
            file[k]
            for k in ("source_id", "resource_id", "file_sha256", "parser_version")
        )
        if identity in seen:
            reject("Selected files contain a duplicate identity")
        seen.add(identity)
        matches = [
            c
            for c in contracts
            if c.get("content", {}).get("input", {}).get("resource_id")
            == file["resource_id"]
        ]
        if len(matches) != 1:
            reject(
                "Exactly one frozen contract is required per selected resource",
                resource_id=file["resource_id"],
            )
        contract = matches[0]
        native = contract["content"]["input"]
        spec = contract["content"]["identity"]
        if contract.get("status") not in {"confirmed", "synthetic_defined"} or any(
            native.get(k) != file[k]
            for k in (
                "source_id",
                "resource_id",
                "file_sha256",
                "parser_version",
                "entity_kind",
            )
        ):
            reject("Contract does not confirm the selected file identity")
        source = sources.get(file["source_id"])
        if source is None or spec.get("release_scope") != source["release_scope"]:
            reject("Contract release differs from the selected source")
        fields = spec.get("key", {}).get("fields")
        if (
            not isinstance(fields, list)
            or not fields
            or any(not isinstance(f, str) or not f for f in fields)
        ):
            reject("Contract must declare ordered native key fields")
        parent = spec.get("parent") or {}
        selected.append(
            {
                **{
                    k: file[k]
                    for k in (
                        "source_id",
                        "resource_id",
                        "file_sha256",
                        "parser_version",
                        "entity_kind",
                    )
                },
                "release_scope": source["release_scope"],
                "key_fields": fields,
                "parent_resource_id": parent.get("resource_id"),
                "parent_fields": parent.get("fields", []),
                "parent_crash_fields": parent.get("parent_fields", []),
            }
        )
    for item in selected:
        if item["entity_kind"] == "crash":
            continue
        parents = [
            p
            for p in selected
            if p["source_id"] == item["source_id"]
            and p["resource_id"] == item["parent_resource_id"]
            and p["entity_kind"] == "crash"
        ]
        fields, targets = item["parent_fields"], item["parent_crash_fields"]
        if (
            len(parents) != 1
            or not isinstance(fields, list)
            or not isinstance(targets, list)
            or not fields
            or len(fields) != len(targets)
            or any(not isinstance(f, str) or not f for f in fields + targets)
        ):
            reject("A unit/Node contract needs a selected same-source crash parent")
        if item["entity_kind"] == "unit" and targets != parents[0]["key_fields"]:
            reject("Unit parent fields must identify the complete crash key")
    return selected


SELECTED_CTE = """WITH selected AS (
 SELECT * FROM jsonb_to_recordset(%s::jsonb) AS f(
 source_id text, release_scope text, resource_id text, file_sha256 text,
 parser_version text, entity_kind text, key_fields text[],
 parent_resource_id text, parent_fields text[], parent_crash_fields text[]))
"""


def _scalar(connection, sql, parameters):
    with connection.cursor() as cursor:
        cursor.execute(sql, parameters)
        return cursor.fetchone()[0]


def validate_snapshot(connection, context):
    manifest = context.manifest.as_dict()
    files = selected_contracts(manifest)
    batch = str(context.batch_id)
    status = _scalar(
        connection,
        "SELECT count(*) FROM meta.batch WHERE batch_id=%s::uuid AND status='running'",
        (batch,),
    )
    if status != 1:
        reject("Canonical loading requires the current running candidate batch")
    for kind in ("crash", "unit"):
        existing = _scalar(
            connection,
            f"SELECT count(*) FROM canonical.{kind} WHERE batch_id=%s::uuid",
            (batch,),
        )
        if existing:
            reject("Candidate already contains Canonical rows; retry in a new batch")
        # SQL identifiers are fixed module constants, never manifest strings.
        parent_join = (
            """LEFT JOIN rv.link_crash_unit l ON l.batch_id=s.batch_id AND l.source_id=s.source_id
          AND l.release_scope=s.release_scope AND l.unit_key=s.unit_key
        LEFT JOIN rv.sat_crash p ON p.batch_id=s.batch_id AND p.source_id=s.source_id
          AND p.release_scope=s.release_scope AND p.crash_key=l.crash_key"""
            if kind == "unit"
            else ""
        )
        parent_check = (
            """OR l.crash_key IS NULL OR p.crash_key IS NULL
        OR s.attributes->>'crash_key' IS DISTINCT FROM l.crash_key
        OR rv.encode_business_key(VARIADIC ARRAY(SELECT r.payload->>k FROM unnest(f.parent_fields) WITH ORDINALITY AS x(k,n) ORDER BY n)) IS DISTINCT FROM l.crash_key"""
            if kind == "unit"
            else ""
        )
        invalid = _scalar(
            connection,
            SELECTED_CTE + f"""
        SELECT count(*) FROM rv.sat_{kind} s
        LEFT JOIN raw.record r ON r.raw_record_id=s.raw_record_id AND r.source_id=s.source_id
        LEFT JOIN selected f ON f.source_id=s.source_id AND f.release_scope=s.release_scope
          AND f.resource_id=r.resource_id AND f.file_sha256=r.file_sha256
          AND f.parser_version=r.parser_version AND f.entity_kind='{kind}'
        {parent_join}
        WHERE s.batch_id=%s::uuid AND (f.resource_id IS NULL
          OR rv.encode_business_key(VARIADIC ARRAY(SELECT r.payload->>k FROM unnest(f.key_fields) WITH ORDINALITY AS x(k,n) ORDER BY n)) IS DISTINCT FROM s.{kind}_key
          {parent_check})""",
            (json.dumps(files), batch),
        )
        if invalid:
            reject(
                "Satellite identity, selected Raw lineage or parent is invalid",
                entity_kind=kind,
                affected_count=invalid,
            )
    invalid = _scalar(
        connection,
        SELECTED_CTE + """
    SELECT count(*) FROM rv.sat_crash s
    JOIN raw.record r ON r.raw_record_id=s.raw_record_id
    LEFT JOIN raw.record loc ON loc.raw_record_id=(s.attributes->>'location_record_id')::uuid
      AND loc.source_id=s.source_id
    LEFT JOIN selected f ON f.source_id=s.source_id AND f.release_scope=s.release_scope
      AND f.resource_id=loc.resource_id AND f.file_sha256=loc.file_sha256 AND f.parser_version=loc.parser_version
    WHERE s.batch_id=%s::uuid AND s.attributes->>'location_record_id' IS NOT NULL
      AND (f.resource_id IS NULL OR NOT (
        (f.entity_kind='crash' AND loc.raw_record_id=r.raw_record_id)
        OR (f.entity_kind='node_raw' AND f.parent_resource_id=r.resource_id
          AND CASE WHEN EXISTS (
              SELECT 1 FROM unnest(f.parent_fields,f.parent_crash_fields) AS k(child,parent)
              WHERE loc.payload->>k.child IS NULL OR r.payload->>k.parent IS NULL)
            THEN false ELSE
              rv.encode_business_key(VARIADIC ARRAY(SELECT loc.payload->>k FROM unnest(f.parent_fields) WITH ORDINALITY AS x(k,n) ORDER BY n)) =
              rv.encode_business_key(VARIADIC ARRAY(SELECT r.payload->>k FROM unnest(f.parent_crash_fields) WITH ORDINALITY AS x(k,n) ORDER BY n)) END)
      ))""",
        (json.dumps(files), batch),
    )
    if invalid:
        reject(
            "Location lineage must reference the selected crash or its exact Node",
            affected_count=invalid,
        )


def reconcile(connection, context):
    """Compare all selected Satellite rows with actual persisted Canonical rows."""
    counts = {}
    for kind in ("crash", "unit"):
        excluded = f"ARRAY['batch_id','source_id','release_scope','{kind}_key','raw_record_id']"
        mismatch = _scalar(
            connection,
            f"""
        WITH satellite AS (SELECT * FROM rv.sat_{kind} WHERE batch_id=%s::uuid),
             loaded AS (SELECT * FROM canonical.{kind} WHERE batch_id=%s::uuid)
        SELECT count(*) FROM satellite s FULL JOIN loaded c
          USING (batch_id,source_id,release_scope,{kind}_key)
        WHERE s.raw_record_id IS NULL OR c.raw_record_id IS NULL
          OR s.raw_record_id IS DISTINCT FROM c.raw_record_id
          OR s.attributes IS DISTINCT FROM (to_jsonb(c)-{excluded})""",
            (str(context.batch_id), str(context.batch_id)),
        )
        if mismatch:
            reject(
                "Canonical rows differ from selected Satellite attributes/lineage",
                entity_kind=kind,
                affected_count=mismatch,
            )
        counts[kind] = _scalar(
            connection,
            f"SELECT count(*) FROM canonical.{kind} WHERE batch_id=%s::uuid",
            (str(context.batch_id),),
        )
    return counts
