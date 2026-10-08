"""Release-pinned source queries. Missing facts never become invented zeros."""
from collections import defaultdict
from datetime import date
from .date_bounds import MIN_YEAR, MAX_YEAR

import calendar

from . import store
from .coverage_policy import complete_intervals, covers, fill_complete_months
from .publication_policy import admission_level

METRICS = ("crash_count", "fatal_crash_count", "fatalities", "casualties")
OBSERVATION_METRICS = {"crash_count": "crashes", "fatal_crash_count": "fatal_crashes",
                       "fatalities": "fatalities", "casualties": "casualties"}
NAMES = {"official_nsw": ("NSW", "NSW road crashes", "Transport for NSW"),
         "official_vic": ("VIC", "Victorian road crashes", "Victorian Department of Transport"),
         "official_qld": ("QLD", "Queensland road crashes", "Queensland Government")}


def metric_support(result):
    """Read machine-validated mappings, never explanatory prose, for support.

    An absent mapping is unsupported. A mapped source value can still be
    unknown. Historical native releases predate contracts; their established
    non-null summary metrics retain their existing capabilities.
    """
    contract = result.get("source_contract", {})
    if contract.get("contract_version") != "canonical-v2":
        return {key: key == "crash_count" or result.get("summary", {}).get(key) is not None for key in METRICS}
    supported = dict.fromkeys(METRICS, False)
    for resource in contract.get("resources", []):
        mapping = resource.get("mapping", {})
        if resource.get("grain") == "crash":
            supported["crash_count"] = True
            supported["fatal_crash_count"] |= isinstance(mapping.get("severity"), dict)
            for key in ("fatalities", "casualties"):
                supported[key] |= isinstance(mapping.get(key), dict)
        elif resource.get("grain") == "observation":
            for key, alias in OBSERVATION_METRICS.items():
                supported[key] |= isinstance(mapping.get("metrics", {}).get(alias), dict)
    return supported


def query_result(base, result, availability, reason, *, aggregation_supported=True):
    support = metric_support(result)
    statuses = {}
    for key in METRICS:
        if availability != "available":
            statuses[key] = availability
        elif not aggregation_supported:
            statuses[key] = "unsupported"
        elif base["summary"][key] is not None:
            statuses[key] = "available"
        else:
            statuses[key] = "unknown" if support[key] else "unsupported"
    return {**base, "availability": availability, "reason": reason, "metric_availability": statuses}


def metadata(source_id, batch_id, row, conn=None):
    result = row["result"]
    level = admission_level(result)
    labels = {
        'official_admitted': 'Official source admitted with independent QA',
        'fixed_native': 'Fixed reviewed source snapshot',
        'manual_reviewed': 'Local research: official source identity unverified',
        'legacy_unclassified': 'Historical publication: admission not classified',
    }
    publication_status = {
        'admission_level': level, 'label': labels.get(level, labels['legacy_unclassified']),
        'official_registration': level == 'official_admitted' and bool(
            row.get('source_version_id') and row.get('adapter_version_id')),
        'scope': 'local_research',
    }
    contract = result.get("source_contract", {})
    source = result.get("source", contract.get("source", {}))
    default = NAMES.get(source_id, (source_id.upper(), source_id.replace("_", " "), "Source publisher"))
    jurisdiction = source.get("jurisdiction", result.get("jurisdiction", default[0]))
    if isinstance(jurisdiction, list):
        jurisdiction = jurisdiction[0] if len(jurisdiction) == 1 else jurisdiction
    summary = result["summary"]
    coverage = result.get("coverage", source.get("coverage"))
    if not coverage:
        start, end = summary.get("year_from"), summary.get("year_to")
        coverage = {"from": f"{start}-01-01", "to": f"{end}-12-31"} if start and end else None
    definitions = contract.get("definitions", result.get("definitions", {}))
    capabilities = result.get("capabilities", {})
    monthly = capabilities.get("monthly", bool(result.get("monthly_trend")))
    geography = capabilities.get("geography", capabilities.get("map_points", False))
    grain = source.get("grain", "crash")
    from .publication_summary import monthly as published_monthly
    recorded_monthly = published_monthly(result, batch_id)
    if recorded_monthly is not None:
        monthly = recorded_monthly
    elif conn is not None:
        table = "canonical_observation" if grain == "observation" else "canonical_crash"
        precision = conn.execute("SELECT count(*) AS n,count(month) AS months FROM " + table + " WHERE batch_id=%s", (batch_id,)).fetchone()
        monthly = bool(precision["n"] and precision["n"] == precision["months"])
    return {"source_id": source_id, "batch_id": str(batch_id), "job_id": str(row["job_id"]),
            "jurisdiction": jurisdiction, "source_name": source.get("title", source.get("source_name", default[1])),
            "publisher": source.get("publisher", default[2]), "coverage": coverage,
            "complete_intervals": complete_intervals(result), "coverage_kind": "observed_or_declared_extent",
            "source_version_id": row.get("source_version_id"), "adapter_version_id": row.get("adapter_version_id"),
            "version_scope": result.get('version_scope'),
            "grain": grain,
            "publication_status": publication_status,
            "definitions": {"crashes": definitions.get("crashes", "Source-defined crash records"),
                            "fatalCrashes": definitions.get("fatal_crashes", "Crashes with an evidenced fatal-crash classification"),
                            "livesLost": definitions.get("fatalities", "Deaths according to this source; unknown remains null"),
                            "casualties": definitions.get("casualties", "Casualties according to this source; sources are not automatically comparable")},
            "capabilities": {"monthly": monthly, "severity": capabilities.get("severity", bool(result.get("severity"))),
                             "geography": geography, "units": capabilities.get("units", result.get("units", {}).get("status") == "available")},
            "retained_resources": result.get("admission", {}).get("evidence", {}).get("retained_resources"),
            "row_preprocessing": result.get("admission", {}).get("evidence", {}).get("row_preprocessing"),
            "capability_limits": result.get("capability_limits", []),
            "capability_review": result.get("admission", {}).get("evidence", {}).get("capability_review"),
            "summary": summary, "licensing": result.get("licensing", {"version":"legacy-unassessed", "resources":[], "scope":"local_research_only", "redistribution":"not_assessed"}), "limitations": result.get("limitations", [])}


def release(conn, release_id=None):
    if release_id:
        return conn.execute("SELECT id,sources FROM releases WHERE id=%s", (release_id,)).fetchone()
    return conn.execute("SELECT r.id,r.sources FROM current_release c JOIN releases r ON r.id=c.release_id").fetchone()


def catalog(release_id=None):
    with store.connect() as conn:
        # A disconnected HTTP client must not leave a pathological read query
        # consuming the laboratory indefinitely. This is only the read session.
        conn.execute("SET statement_timeout='15s'")
        chosen = release(conn, release_id)
        if not chosen:
            if release_id:
                raise LookupError("Requested immutable release does not exist")
            return {"release_id": None, "sources": [], "mode": "local-test"}
        sources = []
        for source, batch in chosen["sources"].items():
            row = conn.execute("SELECT * FROM batches WHERE id=%s", (batch,)).fetchone()
            sources.append(metadata(source, batch, row, conn))
        return {"release_id": str(chosen["id"]), "sources": sources, "mode": "local-test"}


def aggregate_sql():
    return """count(*) AS crash_count,
        CASE WHEN count(*)=count(payload->>'is_fatal_crash')
             THEN count(*) FILTER (WHERE payload->>'is_fatal_crash'='true') ELSE NULL END AS fatal_crash_count,
        CASE WHEN count(*)=count(fatalities) THEN coalesce(sum(fatalities),0) ELSE NULL END AS fatalities,
        CASE WHEN count(*)=count(casualties) THEN coalesce(sum(casualties),0) ELSE NULL END AS casualties"""


def precision_supported(conn, table, batch, start, end):
    # A partial boundary year cannot consume annual observations. Interior
    # complete years remain eligible even if the endpoints use month precision.
    row = conn.execute("SELECT count(*) AS n FROM " + table + """ WHERE batch_id=%s AND month IS NULL
        AND ((year=%s AND %s<>1) OR (year=%s AND %s<>12))""",
        (batch, start.year, start.month, end.year, end.month)).fetchone()
    return not row["n"]


def query(source_id, release_id, date_from, date_to, *, include_units=True):
    start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    if start > end or start.year < MIN_YEAR or end.year > MAX_YEAR:
        raise ValueError("Date range must be ordered and within supported years")
    if start.day != 1 or end.day != calendar.monthrange(end.year, end.month)[1]:
        raise ValueError("Select complete calendar months for comparable source queries")
    with store.connect() as conn:
        conn.execute("SET statement_timeout='15s'")
        chosen = release(conn, release_id)
        if not chosen or source_id not in chosen["sources"]:
            raise LookupError("Source is not published in that immutable release")
        batch = chosen["sources"][source_id]
        row = conn.execute("SELECT * FROM batches WHERE id=%s", (batch,)).fetchone()
        result, meta = row["result"], metadata(source_id, batch, row, conn)
        coverage = meta["coverage"]
        intervals = complete_intervals(result)
        complete = covers(intervals, date_from, date_to)
        overlaps = bool(coverage and coverage["from"] <= date_to and coverage["to"] >= date_from)
        base = {"release_id": str(chosen["id"]), "batch_id": batch, "source_id": source_id,
                "coverage": {**(coverage or {"from": None, "to": None}), "complete": complete},
                "complete_intervals": intervals, "requested": {"from": date_from, "to": date_to},
                "summary": {k: None for k in METRICS}, "monthly": [], "yearly": [], "severity": [],
                "qa": result.get("qa", []), "limitations": result.get("limitations", []),
                "publication_status": meta['publication_status'],
                "row_preprocessing": meta['row_preprocessing'], "retained_resources": meta['retained_resources'],
                "capability_limits": meta['capability_limits'], "capability_review": meta['capability_review'],
                "units": {"status": "unavailable", "reason": "No queryable unit records in the selected interval"},
                "geography": {"status": "unsupported", "reason": "This source has no trusted queryable geography"}}
        if not include_units:
            base["units"] = {"status": "not_requested", "reason": "This read request did not request unit aggregates"}
        if not overlaps:
            return query_result(base, result, "no_results", "Requested interval is outside declared source coverage")
        table = "canonical_observation" if meta["grain"] == "observation" else "canonical_crash"
        if not precision_supported(conn, table, batch, start, end):
            return query_result(base, result, "unsupported", "Year-precision records cannot be assigned to a partial-year month filter")
        where = "batch_id=%s AND ((month IS NOT NULL AND year*12+month BETWEEN %s AND %s) OR (month IS NULL AND year BETWEEN %s AND %s))"
        params = (batch, start.year*12+start.month, end.year*12+end.month, start.year, end.year)
        if meta["grain"] == "observation":
            observations = conn.execute("SELECT year,month,payload FROM canonical_observation WHERE " + where + " ORDER BY year,month,record_id LIMIT 10001", params).fetchall()
            definitions = result.get("source_contract", {}).get("definitions", {})
            additive = definitions.get("observations_additive") is True
            if len(observations) > 10000:
                return query_result(base, result, "unsupported", "Observation query exceeds its bounded result size; select a smaller interval")
            aliases = {"crash_count": "crashes", "fatal_crash_count": "fatal_crashes", "fatalities": "fatalities", "casualties": "casualties"}
            def metrics(rows):
                values = [v["payload"].get("metrics", {}) for v in rows]
                return {key: sum(v[alias] for v in values) if values and all(v.get(alias) is not None for v in values) else None for key,alias in aliases.items()}
            base["observations"] = [{"year": v["year"], "month": v["month"], "metrics": v["payload"].get("metrics", {}), "dimensions": v["payload"].get("dimensions", {})} for v in observations]
            if additive or len(observations) == 1:
                base["summary"] = metrics(observations)
            if additive or len(observations) == 1:
                years, months = defaultdict(list), defaultdict(list)
                for item in observations:
                    years[item["year"]].append(item)
                    if item["month"] is not None:
                        months[(item["year"], item["month"])].append(item)
                base["yearly"] = [{"year": year, **metrics(items)} for year,items in sorted(years.items())]
                base["monthly"] = [{"year": year, "month": month, **metrics(items)} for (year,month),items in sorted(months.items())]
            return query_result(base, result, "available" if observations else "no_results",
                    "Published aggregate observations; no individual crash rows were synthesized" if additive else "Observation dimensions may overlap; multiple values are not added without an explicit additive source definition",
                    aggregation_supported=additive or len(observations) <= 1)
        base["summary"] = conn.execute("SELECT " + aggregate_sql() + " FROM canonical_crash WHERE " + where, params).fetchone()
        if base["summary"]["crash_count"] == 0:
            # An empty interval proves zero only for metrics which the declared
            # source actually measures and whose interval is fully covered.
            for key in METRICS:
                known = key == "crash_count" or result["summary"].get(key) is not None
                base["summary"][key] = 0 if complete and known else None
        base["yearly"] = conn.execute("SELECT year," + aggregate_sql() + " FROM canonical_crash WHERE " + where + " GROUP BY year ORDER BY year", params).fetchall()
        unknown_month = conn.execute("SELECT count(*) AS n FROM canonical_crash WHERE " + where + " AND month IS NULL", params).fetchone()["n"]
        if not unknown_month:
            base["monthly"] = conn.execute("SELECT year,month," + aggregate_sql() + " FROM canonical_crash WHERE " + where + " GROUP BY year,month ORDER BY year,month", params).fetchall()
            if meta['capabilities']['monthly']:
                base['monthly'] = fill_complete_months(base['monthly'], intervals, start, end,
                    {key: key == 'crash_count' or result['summary'].get(key) is not None for key in METRICS})
        definitions = {s["code"]: s for s in result.get("severity", [])}
        severity = conn.execute("SELECT severity AS code,count(*) AS count FROM canonical_crash WHERE " + where + " GROUP BY severity ORDER BY severity", params).fetchall()
        base["severity"] = [{"code": r["code"], "label": definitions.get(r["code"], {}).get("label", r["code"] or "Unknown"), "count": r["count"]} for r in severity]
        if include_units and result.get("units", {}).get("status") == "available":
            generic = result.get("profile_id", "").startswith(("generic:", "autonomous:"))
            if result.get("profile_id", "").startswith("autonomous:"):
                unit_sql = """WITH selected AS MATERIALIZED (SELECT payload->>'resource_role' AS role,payload->>'record_id' AS raw_key
                    FROM canonical_crash WHERE """ + where + """), units AS MATERIALIZED (
                    SELECT ordinal,payload->>'unit_type' AS unit_type,payload->>'crash_id' AS crash_key,
                        payload->'relations' AS relations FROM canonical_unit
                    WHERE batch_id=%s AND (%s OR payload->>'count_eligible'='true'))
                    SELECT u.unit_type,count(*) AS count FROM units u
                    WHERE EXISTS (SELECT 1 FROM selected c
                        WHERE c.raw_key=u.crash_key AND u.relations->>c.role=c.raw_key)
                    GROUP BY u.unit_type ORDER BY u.unit_type"""
            else:
                unit_sql = """WITH selected AS (SELECT record_id FROM canonical_crash WHERE """ + where + """)
                    SELECT u.payload->>'unit_type' AS unit_type,count(*) AS count FROM canonical_unit u
                    JOIN selected c ON c.record_id=coalesce(u.payload->>'crash_id',u.payload->>'crash_record_id')
                    WHERE u.batch_id=%s AND (%s OR u.payload->>'count_eligible'='true')
                    GROUP BY 1 ORDER BY 1"""
            unit_rows = conn.execute(unit_sql, (*params, batch, generic)).fetchall()
            base["units"] = {"status": "available", "scope": result["units"].get("scope"), "rows": unit_rows}
        if meta["capabilities"]["geography"]:
            geography = conn.execute("""SELECT payload->>'region' AS region,payload->>'region_type' AS region_type,count(*) AS crash_count
                FROM canonical_crash WHERE """ + where + """ AND payload->>'geography_status'='available'
                GROUP BY 1,2 ORDER BY 3 DESC LIMIT 500""", params).fetchall()
            known = [r for r in geography if r["region"]]
            cells = conn.execute("""WITH cells AS (SELECT round((payload->'coordinates'->>0)::numeric,1) AS longitude,
                round((payload->'coordinates'->>1)::numeric,1) AS latitude,count(*) AS crash_count
                FROM canonical_crash WHERE """ + where + """ AND payload->>'geography_status'='available'
                AND jsonb_typeof(payload->'coordinates')='array' GROUP BY 1,2)
                SELECT *,count(*) OVER () AS total_cells,sum(crash_count) OVER () AS located_crash_count
                FROM cells ORDER BY crash_count DESC,longitude,latitude LIMIT 2000""", params).fetchall()
            if known or cells:
                located = int(cells[0]["located_crash_count"]) if cells else 0
                total_cells = int(cells[0]["total_cells"]) if cells else 0
                base["geography"] = {"status": "available", "regions": known,
                    "cells": [{"longitude": float(r["longitude"]), "latitude": float(r["latitude"]), "crash_count": r["crash_count"]} for r in cells],
                    "total_cells": total_cells, "returned_cells": len(cells), "truncated": total_cells > len(cells),
                    "located_crash_count": located, "unlocated_crash_count": (base["summary"]["crash_count"] or 0) - located,
                    "precision_degrees": 0.1, "reason": "Source-defined regions and rounded public crash locations; no implied ABS boundary crosswalk"}
        return query_result(base, result, "available" if base["summary"]["crash_count"] or complete else "no_results",
                None if complete else "Only the declared overlapping coverage is available")
