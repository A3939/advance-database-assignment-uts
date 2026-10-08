"""Read-only database reconciliation; counts never change source semantics."""
from .errors import ValidationFailure


def verify_candidate(conn, batch, result):
    summary = result["summary"]
    source = result["source_id"]
    crash = conn.execute("""SELECT count(*) AS crash_count,
        count(*) FILTER (WHERE payload->>'is_fatal_crash'='true') AS fatal_crash_count,
        sum(fatalities) AS fatalities,sum(casualties) AS casualties,
        count(*) FILTER (WHERE payload->>'source_id' IS DISTINCT FROM %s) AS wrong_source_count
        FROM canonical_crash WHERE batch_id=%s""", (source, batch)).fetchone()
    generic = result["profile_id"].startswith("generic:")
    units = conn.execute("""SELECT count(*) AS canonical_unit_count,
        count(*) FILTER (WHERE %s OR payload->>'count_eligible'='true') AS eligible_unit_count,
        count(*) FILTER (WHERE nullif(payload->>'record_id','') IS NULL) AS missing_unit_id_count,
        count(*) FILTER (WHERE payload->>'source_id' IS DISTINCT FROM %s) AS wrong_source_count
        FROM canonical_unit WHERE batch_id=%s""", (generic, source, batch)).fetchone()
    duplicates = conn.execute("""SELECT count(*) AS n FROM (
        SELECT payload->>'record_id' FROM canonical_unit WHERE batch_id=%s
        GROUP BY payload->>'record_id' HAVING count(*)>1) d""", (batch,)).fetchone()["n"]
    orphans = conn.execute("""SELECT count(*) AS n FROM canonical_unit u
        LEFT JOIN canonical_crash c ON c.batch_id=u.batch_id
          AND c.record_id=coalesce(u.payload->>'crash_id',u.payload->>'crash_record_id')
        WHERE u.batch_id=%s AND c.record_id IS NULL""", (batch,)).fetchone()["n"]
    expected_units = summary.get("canonical_unit_count")
    if expected_units is None:
        expected_units = summary.get("unit_count") if generic else 0
    expected_units = expected_units or 0
    mismatch = []
    for key in ("crash_count", "fatal_crash_count", "fatalities", "casualties"):
        expected = summary.get(key)
        if expected is not None and int(crash[key] or 0) != expected:
            mismatch.append(key)
    if units["canonical_unit_count"] != expected_units:
        mismatch.append("canonical_unit_count")
    if summary.get("unit_count") is not None and units["eligible_unit_count"] != summary["unit_count"]:
        mismatch.append("eligible_unit_count")
    if result.get("units", {}).get("status") == "unavailable" and (units["eligible_unit_count"] or summary.get("unit_count") is not None):
        mismatch.append("unavailable_unit_policy")
    if crash["wrong_source_count"] or units["wrong_source_count"]:
        mismatch.append("source_identity")
    if duplicates or units["missing_unit_id_count"] or orphans:
        mismatch.append("unit_keys_or_relationships")
    if result.get("units", {}).get("status") == "available":
        categories = conn.execute("""SELECT payload->>'unit_type' AS unit_type,count(*) AS count
            FROM canonical_unit WHERE batch_id=%s AND (%s OR payload->>'count_eligible'='true')
            GROUP BY payload->>'unit_type'""", (batch, generic)).fetchall()
        actual = {r["unit_type"]: r["count"] for r in categories}
        expected = {r["unit_type"]: r["count"] for r in result["units"].get("rows", [])}
        if actual != expected:
            mismatch.append("unit_categories")
    metrics = {"status": "pass" if not mismatch else "block", "canonical_crash_count": crash["crash_count"],
               "canonical_unit_count": units["canonical_unit_count"], "eligible_unit_count": units["eligible_unit_count"],
               "unit_duplicate_key_count": duplicates, "unit_orphan_count": orphans,
               "wrong_source_count": crash["wrong_source_count"] + units["wrong_source_count"]}
    if mismatch:
        raise ValidationFailure("Database reconciliation failed", [{"code": "DB_RECONCILIATION", "status": "block",
            "message": "Stored candidate differs from validated results: " + ", ".join(mismatch), "metrics": metrics}])
    return metrics
