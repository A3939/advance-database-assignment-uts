"""C03: project the selected NSW snapshot in B's transaction.

The caller supplies B09 manifest data; no commit, rollback, connection ownership,
FP1 calculation or publication is performed here.
"""

from __future__ import annotations

import json
from importlib.resources import files

SQL_DIR = files("arsia_c.projections").joinpath("sql")
COUNT_FIELDS = (
    "No. killed",
    "No. seriously injured",
    "No. moderately injured",
    "No. minor-other injured",
)


def _contract_by_id(manifest: dict, resource_id: str) -> dict:
    matches = [c for c in manifest["rules"]["contracts"] if c["id"] == resource_id]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one contract for {resource_id}, found {len(matches)}"
        )
    return matches[0]


def _mapping_by_id(manifest: dict, mapping_id: str) -> dict:
    matches = [m for m in manifest["rules"]["mappings"] if m["id"] == mapping_id]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one mapping for {mapping_id}, found {len(matches)}"
        )
    return matches[0]


def _mapping(manifest, contract):
    ids = contract["mapping_ids"]
    if len(ids) != 1:
        raise ValueError("NSW contracts must reference exactly one projection mapping")
    mapping = _mapping_by_id(manifest, ids[0])
    if not mapping.get("version"):
        raise ValueError("NSW projection mapping needs a version")
    return mapping


def _parameters(manifest, batch_id):
    """Resolve roles and frozen definitions; resource IDs are never hardcoded."""
    kind = manifest.get("dataset_kind")
    if kind not in ("synthetic", "official"):
        raise ValueError("NSW needs explicit synthetic/official dataset_kind")
    years = manifest["analysis"]
    lo, hi = years["year_from"], years["year_to"]
    if type(lo) is not int or type(hi) is not int or not 1 <= lo <= hi <= 9999:
        raise ValueError("NSW needs an inclusive calendar-year interval")
    sources = [s for s in manifest["sources"] if s["jurisdiction_code"] == "NSW"]
    if len(sources) != 1:
        raise ValueError("NSW module requires exactly one selected NSW source")
    source = sources[0]
    sid = source["source_id"]
    prefix = "syn_" if kind == "synthetic" else "official_"
    if not sid.startswith(prefix):
        raise ValueError("NSW source namespace disagrees with dataset_kind")
    files = [f for f in manifest["files"] if f["source_id"] == sid]
    contracts = []
    for role, entity in (("crash", "crash"), ("traffic_unit", "unit")):
        matches = [
            f
            for f in files
            if f["resource_role"] == role and f["entity_kind"] == entity
        ]
        if len(matches) != 1:
            raise ValueError(f"NSW needs exactly one {role} input")
        selected = matches[0]
        contract = _contract_by_id(manifest, selected["resource_id"])
        expected_status = "synthetic_defined" if kind == "synthetic" else "confirmed"
        if contract.get("status") != expected_status:
            raise ValueError(
                "NSW requires synthetic_defined/confirmed contracts; drafts cannot execute"
            )
        content = contract["content"]
        if (
            not contract.get("version")
            or content["input"] != selected
            or content["identity"]["release_scope"] != source["release_scope"]
        ):
            raise ValueError(
                "NSW contract input/release differs from selected manifest"
            )
        if (
            not selected["resource_id"].startswith(prefix)
            or type(selected.get("raw_count")) is not int
            or selected["raw_count"] < 0
        ):
            raise ValueError("NSW requires namespaced inputs and declared Raw counts")
        contracts.append(contract)
    crash, unit = contracts
    crash_input, unit_input = (c["content"]["input"] for c in contracts)
    ci, ui = (c["content"]["identity"] for c in contracts)
    if (
        ci["key"]["fields"] != ["Crash ID"]
        or ci["parent"] is not None
        or ui["key"]["fields"] != ["Crash ID", "Traffic unit ID"]
        or ui["parent"]
        != {
            "resource_id": crash_input["resource_id"],
            "fields": ["Crash ID"],
            "parent_fields": ["Crash ID"],
        }
    ):
        raise ValueError("NSW key/parent contract is unsupported")
    cm, um = (_mapping(manifest, c) for c in contracts)
    crash_map, unit_map = cm["content"], um["content"]
    year_mapping = crash_map.get("occurrence_year")
    month_mapping = crash_map.get("occurrence_month")
    if isinstance(month_mapping, dict):
        month_mapping = month_mapping.get("field")
    if (
        year_mapping != "Year of crash"
        or month_mapping != "Month of crash"
        or crash_map.get("severity_raw") != "Degree of crash - detailed"
        or crash_map.get("fatality_count") != COUNT_FIELDS[0]
        or crash_map.get("casualty_components") != list(COUNT_FIELDS)
        or unit_map.get("unit_type_raw") != "TU type group"
    ):
        raise ValueError(
            "Unsupported NSW field mapping; a changed operation needs an adapter"
        )
    version = crash["content"]["semantics"]["severity_definition_version"]
    definitions = [s for s in manifest["rules"]["severity"] if s["source_id"] == sid]
    codes = {s["severity_code"]: s for s in definitions}
    if (
        not definitions
        or len(codes) != len(definitions)
        or any(s["definition_version"] != version for s in definitions)
        or "__MISSING__" not in codes
        or codes["__MISSING__"]["is_fatal_crash"] is not None
        or any(
            type(s["is_fatal_crash"]) is not bool
            for c, s in codes.items()
            if c != "__MISSING__"
        )
    ):
        raise ValueError("NSW severity definitions are incomplete/inconsistent")
    native_codes = crash_map.get("native_severity_codes")
    if native_codes is None:
        if kind == "synthetic":
            # B07 S0/S8 explicitly defines direct fictional codes.
            if crash_map.get("severity_code", {}).get("mapping") != version:
                raise ValueError(
                    "Synthetic severity needs its declared direct-code mapping"
                )
            native_codes = {c: c for c in codes if c != "__MISSING__"}
        elif cm["id"] == "nsw-crash-projection-v1":
            # A04 v1 declares its exact English labels as the native NSW values.
            native_codes = {
                s["severity_label"]: c for c, s in codes.items() if c != "__MISSING__"
            }
        else:
            raise ValueError("Official NSW needs explicit native_severity_codes")
    if (
        not isinstance(native_codes, dict)
        or not native_codes
        or any(
            not isinstance(k, str)
            or not k.strip()
            or v not in codes
            or v == "__MISSING__"
            for k, v in native_codes.items()
        )
    ):
        raise ValueError("NSW native severity mapping is invalid")
    severity = {
        k: {"code": v, "fatal": codes[v]["is_fatal_crash"]}
        for k, v in native_codes.items()
    }
    missing_severity = None
    missing_rule = None
    if {"missing_severity_code", "missing_severity_reason"} & crash_map.keys():
        code = crash_map.get("missing_severity_code")
        reason = crash_map.get("missing_severity_reason")
        if (kind != "synthetic" or not isinstance(code, str)
                or code not in codes or code == "__MISSING__"
                or not isinstance(reason, str) or not reason.strip()):
            raise ValueError("NSW missing severity override needs a synthetic code and reason")
        missing_severity = {"code": code, "fatal": codes[code]["is_fatal_crash"]}
        missing_rule = {"code": code, "reason": reason, "mapping_version": cm["version"]}
    unit_types = unit_map.get("unit_types")
    if unit_types is None and kind == "official":
        # Preserve source-specific native group names as codes, without pooling.
        groups = unit["content"]["semantics"].get("unit_type_groups", [])
        unit_types = {g: g for g in groups}
    if (
        not isinstance(unit_types, dict)
        or not unit_types
        or any(
            not isinstance(k, str)
            or not k.strip()
            or not isinstance(v, str)
            or not v.strip()
            for k, v in unit_types.items()
        )
    ):
        raise ValueError("NSW needs a nonempty frozen unit type mapping")
    scope = unit_map.get("statistical_scope")
    if not isinstance(scope, str) or not scope.strip():
        raise ValueError("NSW needs a declared statistical_scope")
    location = crash_map.get("location", {})
    if kind == "synthetic" and location.get("crs") not in (None, "EPSG:4326"):
        raise ValueError("Synthetic NSW location requires an implemented CRS operation")
    if location and (
        location.get("latitude") != "Latitude"
        or location.get("longitude") != "Longitude"
    ):
        raise ValueError("Unsupported NSW location field mapping")
    map_enabled = kind == "synthetic" and location.get("crs") == "EPSG:4326"
    if map_enabled and not location.get("basis"):
        raise ValueError("Synthetic NSW CRS requires its declared basis")
    params = {
        "batch_id": batch_id,
        "source_id": sid,
        "release_scope": source["release_scope"],
        "year_from": lo,
        "year_to": hi,
        "dataset_kind": kind,
        "severity_version": version,
        "severity_map": json.dumps(severity),
        "missing_severity": json.dumps(missing_severity) if missing_severity else None,
        "missing_severity_rule": json.dumps(missing_rule) if missing_rule else None,
        "unit_types": json.dumps(unit_types),
        "statistical_scope": scope,
        "crash_contract_version": crash["version"],
        "unit_contract_version": unit["version"],
        "empty_is_missing": kind == "synthetic",
        "map_enabled": map_enabled,
        "location_evidence": location.get("basis", cm["id"] + ":" + cm["version"]),
    }
    for name, item in (("crash", crash_input), ("unit", unit_input)):
        for field in ("resource_id", "file_sha256", "parser_version", "raw_count"):
            params[name + "_" + field] = item[field]
    return params


def _load_sql(name):
    return (SQL_DIR / name).read_text(encoding="utf-8")


def _validate_relationship_counts(counts):
    if counts is None:
        raise ValueError("NSW relationship check returned no result")
    names = (
        "crash_blank_key_count",
        "crash_duplicate_key_count",
        "unit_blank_key_count",
        "unit_duplicate_key_count",
        "orphan_unit_count",
    )
    failures = {n: v for n, v in zip(names, counts, strict=True) if v != 0}
    if failures:
        raise ValueError(f"NSW relationship validation failed: {failures}")


def _check(cursor, filename, params, label):
    cursor.execute(_load_sql(filename), params)
    result = cursor.fetchone()
    if result is None or any(result):
        raise ValueError(f"NSW {label} validation failed: {result}")


def _stage_native(cursor, p):
    """Keep full frozen files and collect stats on loader-owned temporary rows."""
    for name in ("crash", "unit"):
        table = "c03_nsw_" + name
        cursor.execute(f"DROP TABLE IF EXISTS pg_temp.{table}")
        cursor.execute(
            f"CREATE TEMP TABLE {table} ON COMMIT DROP AS SELECT * FROM raw.record "
            "WHERE source_id=%s AND resource_id=%s AND file_sha256=%s AND parser_version=%s",
            (p["source_id"], p[name + "_resource_id"], p[name + "_file_sha256"],
             p[name + "_parser_version"]),
        )
        actual = cursor.rowcount
        if actual != p[name + "_raw_count"]:
            raise ValueError(
                f"NSW incomplete Raw {name}: expected {p[name + '_raw_count']}, found {actual}"
            )
        keys = "(payload->>'Crash ID')"
        if name == "unit":
            keys += ", (payload->>'Traffic unit ID')"
        # Non-unique indexes preserve invalid keys for the checks below.
        cursor.execute(f"CREATE INDEX ON pg_temp.{table} ({keys})")
        cursor.execute(f"ANALYZE pg_temp.{table}")


def project(connection, context) -> None:
    manifest = context.manifest.as_dict()
    p = _parameters(manifest, context.batch_id)
    if getattr(context, "dataset_kind", p["dataset_kind"]) != p["dataset_kind"]:
        raise ValueError("NSW context and manifest dataset_kind differ")
    with connection.cursor() as cursor:
        # Full-snapshot completeness and relationships precede all year filtering.
        _stage_native(cursor, p)
        cursor.execute(_load_sql("c03_nsw_relationship_check.sql"), p)
        _validate_relationship_counts(cursor.fetchone())
        for filename, label in (
            ("c03_nsw_year_check.sql", "year"),
            ("c03_nsw_month_check.sql", "month"),
            ("c03_nsw_semantic_check.sql", "semantic"),
            ("c03_nsw_unit_check.sql", "Traffic Unit"),
        ):
            _check(cursor, filename, p, label)
        cursor.execute(_load_sql("c03_projection_tables.sql"))
        # Preserve other modules' rows. Repeating this source within the transaction
        # replaces only this exact batch/source/release projection.
        for table in ("arsia_i_unit", "arsia_i_crash"):
            cursor.execute(
                f"DELETE FROM pg_temp.{table} WHERE batch_id=%s AND source_id=%s AND release_scope=%s",
                (p["batch_id"], p["source_id"], p["release_scope"]),
            )
        cursor.execute(_load_sql("c03_nsw_crash_insert.sql"), p)
        crash_count = cursor.rowcount
        cursor.execute(_load_sql("c03_nsw_unit_insert.sql"), p)
        unit_count = cursor.rowcount
        for table in ("arsia_i_crash", "arsia_i_unit"):
            cursor.execute(f"ANALYZE pg_temp.{table}")
        cursor.execute(_load_sql("c03_nsw_projection_check.sql"), p)
        row = cursor.fetchone()
        names = (
            "crash_projection_count",
            "unit_projection_count",
            "duplicate_crash_key_count",
            "duplicate_unit_key_count",
            "orphan_projected_unit_count",
            "fatal_crash_count",
            "fatality_count",
            "casualty_count",
            "map_eligible_count",
            "missing_unit_type_count",
            "invalid_unit_eligibility_count",
        )
        if row is None:
            raise ValueError("NSW projection reconciliation returned no result")
        counts = dict(zip(names, row, strict=True))
        if (
            row[0:2] != (crash_count, unit_count)
            or min(crash_count, unit_count) < 0
            or any(row[2:5])
            or row[10]
            or (not p["map_enabled"] and row[8])
        ):
            raise ValueError(f"NSW projection reconciliation failed: {counts}")
    counts.update(
        {
            k: p[k]
            for k in (
                "source_id",
                "release_scope",
                "dataset_kind",
                "year_from",
                "year_to",
            )
        }
    )
    counts.update(
        {
            "raw_crash_count": p["crash_raw_count"],
            "raw_unit_count": p["unit_raw_count"],
            "excluded_crash_count": p["crash_raw_count"] - crash_count,
            "excluded_unit_count": p["unit_raw_count"] - unit_count,
        }
    )
    context.evidence.write_json("c03-nsw-projection-counts.json", counts)
