"""B's AT15 adapter for the fictional S8 crash file; no official SA support."""

import hashlib
import json

from .source_contracts import _one, check, clear_projection, sql

HEADER = ["CRASH_ID", "YEAR", "MONTH", "SEVERITY", "FATALITIES", "CASUALTIES",
          "LATITUDE", "LONGITUDE"]
# The generated s8-native-v1 semantics in tests/fixtures/s8/contract.json.
SEMANTICS_SHA256 = "6ed45e751fa1bab67af873bef572badfc7ca6612f48b12f409d9c4018fbfd461"
COVERAGE = {
    "year_from": 2020, "year_to": 2024, "months": list(range(1, 13)),
    "basis": "S8 defines all months in 2020-2024 as covered, matching the fictional "
             "S0 analysis window. This is not official SA coverage.",
}
MAPPING = {
    "occurrence_year": "YEAR", "occurrence_month": "MONTH", "occurrence_date": None,
    "date_precision": "month", "severity_raw": "SEVERITY", "severity_definition": "syn-1",
    "severity_code": {"mapping": "syn-1", "native_missing": "__MISSING__"},
    "fatality_count": "FATALITIES", "casualty_count": "CASUALTIES",
    "unit_details": "Not supplied. Do not create unit records or infer a declared unit count of zero.",
}


def parameters(manifest, batch_id):
    """Check the supported S8 contract before touching Raw."""
    if manifest.get("dataset_kind") != "synthetic":
        raise ValueError("SA adapter supports synthetic S8 only")
    lo, hi = (manifest["analysis"][k] for k in ("year_from", "year_to"))
    if type(lo) is not int or type(hi) is not int or not 1 <= lo <= hi <= 9999:
        raise ValueError("Invalid S8 analysis calendar-year interval")
    source = _one([s for s in manifest["sources"] if s["jurisdiction_code"] == "SA"], "SA source")
    if (source["source_id"] != "syn_sa" or source["release_scope"] != "s0"
            or source["release_label"] != "Synthetic S8 v1"
            or source["resource_ids"] != ["syn_sa_crash"]):
        raise ValueError("Unsupported S8 source/release")
    selected = _one([f for f in manifest["files"] if f["source_id"] == "syn_sa"], "S8 file")
    expected = {"resource_id": "syn_sa_crash", "resource_role": "crash", "entity_kind": "crash",
                "parser_version": "csv-native-v1", "locator_version": "csv-logical-v1",
                "format": "csv", "encoding": "utf-8", "sheet": None,
                "header_row": 1, "header": HEADER}
    if (any(selected.get(k) != v for k, v in expected.items())
            or type(selected.get("raw_count")) is not int or selected["raw_count"] < 0):
        raise ValueError("Unsupported S8 native input")
    contract = _one([c for c in manifest["rules"]["contracts"] if c["id"] == "syn_sa_crash"], "S8 contract")
    content = contract["content"]
    identity = content["identity"]
    if (contract["version"] != "s8-native-v1" or contract["status"] != "synthetic_defined"
            or contract["mapping_ids"] != ["syn_sa_crash_mapping"]
            or content["input"] != selected
            or any(identity[k] != source[k] for k in ("release_scope", "release_label", "resource_ids"))
            or identity["key"] != {"fields": ["CRASH_ID"], "unique": True}
            or identity["parent"] is not None):
        raise ValueError("Unsupported S8 contract identity/input")
    coverage = identity.get("coverage")
    # JSON comparison also rejects booleans/floats that Python treats as equal integers.
    if (not isinstance(coverage, dict)
            or json.dumps(coverage, sort_keys=True) != json.dumps(COVERAGE, sort_keys=True)):
        raise ValueError("S8 coverage differs from s8-native-v1")
    semantics = json.dumps(content["semantics"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(semantics).hexdigest() != SEMANTICS_SHA256:
        raise ValueError("S8 semantics differ from s8-native-v1")
    mapping = _one([m for m in manifest["rules"]["mappings"] if m["id"] == "syn_sa_crash_mapping"], "S8 mapping")
    fields = mapping["content"]
    if mapping["version"] != "syn-1" or {k: v for k, v in fields.items() if k != "location"} != MAPPING:
        raise ValueError("Unsupported S8 mapping operation")
    loc = fields.get("location", {})
    if (set(loc) != {"latitude", "longitude", "crs", "basis"}
            or loc["latitude"] != "LATITUDE" or loc["longitude"] != "LONGITUDE"
            or loc["crs"] not in (None, "EPSG:4326")
            or not isinstance(loc["basis"], str) or not loc["basis"].strip()):
        raise ValueError("Unsupported or unevidenced S8 location mapping")
    severity = [s for s in manifest["rules"]["severity"] if s["source_id"] == "syn_sa"]
    expected_severity = {"F": ("Fatal", True), "I": ("Injury", False),
                         "N": ("Non-injury", False), "__MISSING__": ("Unknown", None)}
    if (len(severity) != 4 or {s["severity_code"] for s in severity} != set(expected_severity)
            or any(s["definition_version"] != "syn-1"
                   or s["severity_label"] != expected_severity[s["severity_code"]][0]
                   or s["is_fatal_crash"] is not expected_severity[s["severity_code"]][1]
                   for s in severity)):
        raise ValueError("S8 severity definitions differ from syn-1")
    return {"batch_id": batch_id, "dataset_kind": "synthetic", "source_id": "syn_sa",
            "release_scope": "s0", "year_from": lo, "year_to": hi,
            "severity_version": "syn-1", "contract_version": contract["version"],
            "severity_map": json.dumps({k: {"code": k, "fatal": v[1]}
                                        for k, v in expected_severity.items() if k != "__MISSING__"}),
            "map_enabled": loc["crs"] == "EPSG:4326", "location_evidence": loc["basis"],
            "selected": {"crash": selected}}


def project(connection, context):
    """Use the caller's transaction and retain the native crash as location lineage."""
    if connection.autocommit is not False:
        raise ValueError("S8 projection requires a caller-owned transaction")
    p = parameters(context.manifest.as_dict(), context.batch_id)
    if getattr(context, "dataset_kind", "synthetic") != "synthetic":
        raise ValueError("S8 context/manifest dataset_kind mismatch")
    selected = p["selected"]["crash"]
    with connection.cursor() as cur:
        cur.execute("SELECT source_id,resource_role,entity_kind FROM meta.resource WHERE resource_id=%s",
                    (selected["resource_id"],))
        if cur.fetchone() != ("syn_sa", "crash", "crash"):
            raise ValueError("S8 resource registration mismatch")
        cur.execute("DROP TABLE IF EXISTS pg_temp.s8_crash")
        cur.execute("CREATE TEMP TABLE s8_crash ON COMMIT DROP AS "
                    "SELECT raw_record_id,payload FROM raw.record WHERE source_id=%s AND resource_id=%s "
                    "AND file_sha256=%s AND parser_version=%s",
                    ("syn_sa", selected["resource_id"], selected["file_sha256"], selected["parser_version"]))
        cur.execute("SELECT count(*) FROM pg_temp.s8_crash")
        if cur.fetchone()[0] != selected["raw_count"]:
            raise ValueError("Incomplete selected S8 Raw")
        check(cur, "SELECT count(*) FROM pg_temp.s8_crash WHERE NOT payload ?& %s::text[] "
              "OR EXISTS(SELECT 1 FROM jsonb_each(payload) e WHERE jsonb_typeof(e.value) NOT IN ('string','null'))",
              (HEADER,), "S8 Raw native fields/types")
        check(cur, sql("s8_sa_check.sql"), p, "S8 keys/dates/categories/counts")
        cur.execute(sql("c03_projection_tables.sql"))
        clear_projection(cur, p)
        cur.execute(sql("s8_sa_insert.sql"), p)
        count = cur.rowcount
    context.evidence.write_json("s8-sa-projection-counts.json", {
        "source_id": "syn_sa", "raw_crash_count": selected["raw_count"], "crash_count": count,
        "excluded_crash_count": selected["raw_count"] - count, "unit_count": 0,
        "scope": "Synthetic S8 projection only; no official SA or publication claim",
    })
