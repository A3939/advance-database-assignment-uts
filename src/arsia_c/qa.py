"""C10 object checks on B's transaction, with immutable evidence and QA rows."""

from collections import Counter, defaultdict
from datetime import datetime, timezone
from importlib.resources import files
import json
from uuid import uuid4

from arsia_ingest.manifest import FrozenManifest
from arsia_ingest.models import IntakeError
from arsia_ingest.qa_input import QAReport, write_results
from .qa_expectations import Source, coordinate, different, reference, missing_reasons
from .person_checks import review_manifest
from .restricted_person import restricted_inputs

PRODUCER_VERSION = "c10-b-s8-v1"
RULES = ("QA03_PROJECTED", "QA04_AUXILIARY", "QA05_SEMANTICS", "QA07_LOCATION")


def _sql(name):
    return files("arsia_c").joinpath("sql", name).read_text(encoding="utf-8")


def _fetch(connection, name, params):
    with connection.cursor() as cur:
        cur.execute(_sql(name), params)
        return cur.fetchall()


def _json(value):
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


class Findings:
    def __init__(self):
        self.rows = {}

    def add(self, identity, reason, **detail):
        row = self.rows.setdefault(
            str(identity), {"object": str(identity), "reason_codes": []}
        )
        if reason not in row["reason_codes"]:
            row["reason_codes"].append(reason)
        row.update(_json(detail))

    def raw(self, row, file, reason, **detail):
        self.add(row["raw_record_id"], reason, reference=reference(row, file), **detail)

    def __len__(self):
        return len(self.rows)


def _row(
    rule,
    obj,
    metrics,
    expected,
    evaluated,
    expected_count,
    findings,
    refs,
    *,
    limited=0,
    details=(),
):
    for name, wanted in expected.items():
        if wanted is not None and metrics.get(name) != wanted and not len(findings):
            findings.add(
                obj,
                "metric_mismatch",
                metric=name,
                actual=metrics.get(name),
                expected=wanted,
            )
    if evaluated != expected_count and not len(findings):
        findings.add(
            obj, "evaluation_coverage", actual=evaluated, expected=expected_count
        )
    blocked = bool(len(findings))
    result = "block" if blocked else "limited" if limited else "pass"
    return {
        "rule_id": rule,
        "object_key": obj,
        "result": result,
        "affected_count": len(findings) if blocked else limited,
        "actual": {
            "evaluated_count": evaluated,
            "violation_count": len(findings),
            "metrics": metrics,
        },
        "expected": {
            "evaluated_count": expected_count,
            "violation_count": 0,
            "metrics": expected,
        },
        "evidence": {
            "reason_codes": sorted(
                {r for f in findings.rows.values() for r in f["reason_codes"]}
            )
            or (["location_isolated"] if limited else []),
            "resolution": "See located differences; do not publish."
            if blocked
            else "Unmapped crashes are retained with individual reasons."
            if limited
            else "Checked against selected Raw and frozen rules.",
            "references": refs,
            "producer_version": PRODUCER_VERSION,
        },
        "raw_record_id": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "_details": list(findings.rows.values()) + list(details),
    }


def _refs(source):
    return [
        {k: f[k] for k in ("source_id", "resource_id", "file_sha256", "parser_version")}
        for f in source.files
    ]


def _coverage(source, findings):
    for rid in source.coverage:
        f = next(f for f in source.files if f["resource_id"] == rid)
        findings.add(
            "file:" + rid,
            "incomplete_raw",
            resource_id=rid,
            expected=f["raw_count"],
            actual=len(source.raw[rid]),
        )


def _compare(source, file, actual, expected, findings, *, semantics=False):
    by_id = defaultdict(list)
    for row in actual:
        by_id[str(row["raw_record_id"])].append(row)
    for wanted in expected:
        original = wanted["_raw"]
        rid = original["raw_record_id"]
        matches = by_id.pop(rid, [])
        if len(matches) != 1:
            findings.raw(
                original, file, "projection_membership", actual=len(matches), expected=1
            )
        fields = [
            k
            for k in wanted
            if not k.startswith("_")
            and k
            not in (
                "latitude",
                "longitude",
                "location_crs",
                "location_record_id",
                "map_eligible",
            )
        ]
        for row in matches:
            mismatches = different(row, wanted, fields)
            reasons = missing_reasons(row, wanted) if semantics else []
            if mismatches or reasons:
                findings.raw(
                    original,
                    file,
                    "semantic_values" if semantics else "invalid_projection",
                    mismatched_fields=mismatches,
                    missing_reason_fields=reasons,
                )
    for rid, rows in by_id.items():
        findings.add(rid, "unexpected_projection", actual=rows)


def qa03(source, file, projected):
    wanted = source.projected[file["resource_id"]]
    actual = [
        r
        for kind, r in projected
        if kind == file["entity_kind"] and r["source_id"] == source.sid
    ]
    findings = Findings()
    _coverage(source, findings)
    _compare(source, file, actual, wanted, findings)
    raw = source.raw[file["resource_id"]]
    for r in raw:
        for reason in source.errors.get(r["raw_record_id"], ()):
            findings.raw(r, file, reason)
    field = "crash_key" if file["entity_kind"] == "crash" else "unit_key"
    duplicate = sum(n > 1 for n in Counter(r[field] for r in actual).values())
    orphans = sum(
        "orphan_or_ambiguous_parent" in source.errors.get(r["raw_record_id"], ())
        for r in raw
    )
    # Only a valid parent occurrence outside the interval proves an exclusion.
    excluded = 0
    for r in raw:
        parents = source.crashes.get(r["payload"].get(source.field_key()), [])
        if len(parents) == 1 and not source.in_scope(parents[0]["occurrence_year"]):
            excluded += 1
    count = file["raw_count"] - excluded
    if len(actual) != count:
        findings.add(
            "resource:" + file["resource_id"],
            "projection_count",
            actual=len(actual),
            expected=count,
        )
    metrics = {
        "input_count": len(raw),
        "excluded_count": excluded,
        "projected_count": len(actual),
        "duplicate_key_count": duplicate,
        "orphan_count": orphans,
        "invalid_value_count": sum(
            bool(source.errors.get(r["raw_record_id"], ())) for r in raw
        )
        + sum(
            "invalid_projection" in v["reason_codes"] for v in findings.rows.values()
        ),
    }
    expected = {
        **metrics,
        "input_count": file["raw_count"],
        "projected_count": count,
        "duplicate_key_count": 0,
        "orphan_count": 0,
        "invalid_value_count": 0,
    }
    return _row(
        RULES[0],
        "resource:" + file["resource_id"],
        metrics,
        expected,
        len(actual),
        count,
        findings,
        _refs(source),
    )


def _restrictions(source, crashes, units, facts):
    findings = Findings()
    if not source.official_vic:
        return findings
    for row in units:
        if row["source_id"] == source.sid and (
            row["count_eligible"] is not False
            or not any(
                n.get("field") == "count_eligible"
                and n.get("reason_code") == "definition_unconfirmed"
                for n in row["quality_notes"].get("fields", [])
            )
        ):
            findings.add(row["raw_record_id"], "restricted_unit_eligibility")
    for row in crashes:
        if row["source_id"] == source.sid and (
            row["map_eligible"] is not False
            or any(
                row[k] is not None
                for k in ("latitude", "longitude", "location_crs", "location_record_id")
            )
        ):
            findings.add(row["raw_record_id"], "restricted_location")
    raw_by_key = {(r["source_id"], r["crash_key"]): r["raw_record_id"] for r in crashes}
    for row in facts:
        if row["source_id"] == source.sid and (
            row["map_eligible"] is not False
            or row["latitude"] is not None
            or row["longitude"] is not None
        ):
            findings.add(
                raw_by_key.get((row["source_id"], row["crash_key"]), row["crash_key"]),
                "restricted_fact_location",
            )
    return findings


def qa04(source, file, person, restriction):
    raw = source.raw[file["resource_id"]]
    findings = Findings()
    _coverage(source, findings)
    kind = file["entity_kind"]
    details = []
    for r in raw:
        for reason in source.errors.get(r["raw_record_id"], ()):
            findings.raw(r, file, reason)
    fields = (
        ["ACCIDENT_NO", "NODE_ID"]
        if kind == "node_raw"
        else ["ACCIDENT_NO", "PERSON_ID"]
        if kind == "person_raw"
        else [
            source.field_key(),
            "Traffic unit ID" if source.state == "NSW" else "VEHICLE_ID",
        ]
    )
    groups = defaultdict(list)
    for r in raw:
        groups[tuple(r["payload"].get(f) for f in fields)].append(r)
    metrics = {
        "orphan_count": sum(
            "orphan_or_ambiguous_parent" in source.errors.get(r["raw_record_id"], ())
            for r in raw
        ),
        "nonblank_unmatched_count": None,
        "declared_count_delta": None,
        "duplicate_group_count": sum(len(g) > 1 for g in groups.values()),
        "coordinate_conflict_group_count": None,
    }
    expected = {**metrics, "orphan_count": 0, "duplicate_group_count": 0}
    if kind == "person_raw":
        if person is None:
            findings.add("resource:" + file["resource_id"], "person_checks_missing")
        elif source.official_vic:
            metrics.update(person["qa04_person_contribution"]["actual_metrics"])
            expected.update(person["qa04_person_contribution"]["expected_metrics"])
        else:
            unmatched = person["vehicle_reference_counts"].get("unmatched", 0)
            metrics.update(
                nonblank_unmatched_count=unmatched,
                declared_count_delta=person["declared_count_absolute_delta"],
            )
            expected.update(nonblank_unmatched_count=0, declared_count_delta=0)
            if person["person_count_comparisons"] != len(source.rows("crash")):
                findings.add(
                    file["resource_id"],
                    "person_count_comparison_coverage",
                    actual=person["person_count_comparisons"],
                    expected=len(source.rows("crash")),
                )
        if person:
            details = person["diagnostics"]
            if person["status"] != "pass":
                for detail in details:
                    if detail.get("issues"):
                        findings.add(
                            detail.get("raw_record_id", detail.get("row_locator")),
                            "person_check",
                            detail=detail,
                        )
                if not len(findings) or person.get("summary_violation_count"):
                    findings.add(
                        "resource:" + file["resource_id"],
                        "person_coverage_or_case_set",
                        reason_counts=person["reason_counts"],
                    )
    if kind == "unit" and source.state == "NSW":
        crash_contract = next(
            c
            for c in source.manifest["rules"]["contracts"]
            if c["id"] == source.by_role["crash"]["resource_id"]
        )
        mapping = next(
            m["content"]
            for m in source.manifest["rules"]["mappings"]
            if m["id"] in crash_contract["mapping_ids"]
        )
        declared_rule = mapping.get("declared_unit_count")
        if declared_rule:
            if declared_rule != {
                "field": "No. of traffic units involved",
                "resource_id": file["resource_id"],
            }:
                raise ValueError("Unsupported NSW declared-unit comparison")
            from .qa_expectations import number

            observed = Counter(r["payload"].get("Crash ID") for r in raw)
            deltas = []
            for parent in source.all_crashes:
                r = parent["_raw"]
                try:
                    count = number(
                        r["payload"].get(declared_rule["field"]),
                        empty=source.manifest["dataset_kind"] == "synthetic",
                    )
                except ValueError:
                    findings.raw(
                        r, source.by_role["crash"], "invalid_declared_unit_count"
                    )
                    continue
                if count is not None:
                    delta = abs(count - observed[r["payload"]["Crash ID"]])
                    deltas.append(delta)
                    if delta:
                        findings.raw(
                            r,
                            source.by_role["crash"],
                            "declared_unit_count",
                            declared=count,
                            observed=observed[r["payload"]["Crash ID"]],
                        )
            if len(deltas) != len(source.rows("crash")):
                findings.add(
                    file["resource_id"],
                    "declared_count_comparison_coverage",
                    actual=len(deltas),
                    expected=len(source.rows("crash")),
                )
            metrics["declared_count_delta"] = sum(deltas)
            expected["declared_count_delta"] = 0
    if kind == "unit" and source.state == "VIC":
        by_parent = defaultdict(list)
        for r in raw:
            by_parent[r["payload"].get("ACCIDENT_NO")].append(r)
        differences = []
        invalid = []
        deltas = []
        for c in source.all_crashes:
            r = c["_raw"]
            token = r["payload"].get("NO_OF_VEHICLES")
            from .qa_expectations import number

            try:
                declared = number(token)
            except ValueError:
                invalid.append(r)
                continue
            observed = len(by_parent[r["payload"].get("ACCIDENT_NO")])
            if declared is not None:
                deltas.append(abs(declared - observed))
            if declared is not None and declared != observed:
                differences.append(
                    (
                        r["payload"]["ACCIDENT_NO"],
                        r["payload"]["ACCIDENT_DATE"],
                        r["row_locator"],
                        declared,
                        observed,
                        sorted(
                            x["row_locator"]
                            for x in by_parent[r["payload"]["ACCIDENT_NO"]]
                        ),
                    )
                )
        for r in invalid:
            findings.raw(r, source.by_role["crash"], "invalid_declared_vehicle_count")
        if source.official_vic:
            _, policy = restricted_inputs()
            registered = sorted(
                (
                    r["accident_no"],
                    r["occurrence_date"],
                    r["accident"]["row_locator"],
                    r["declared"],
                    r["observed"],
                    sorted(x["row_locator"] for x in r["vehicle_refs"]),
                )
                for r in policy["cases"]["declared_count_differences"]
                if r["entity"] == "vehicle"
            )
            match = sorted(differences) == registered
            metrics.update(
                case_set_match=match,
                full_count_difference_count=len(differences),
                analysis_count_difference_count=sum(
                    source.in_scope(int(r[1][:4])) for r in differences
                ),
            )
            expected.update(
                policy["qa_expectations"][RULES[1]]["expected_metrics_by_resource"][
                    file["resource_id"]
                ]
            )
            if not match:
                findings.add(
                    file["resource_id"],
                    "vehicle_case_set",
                    actual=differences,
                    expected=registered,
                )
        else:
            if len(deltas) != len(source.rows("crash")):
                findings.add(
                    file["resource_id"],
                    "declared_count_comparison_coverage",
                    actual=len(deltas),
                    expected=len(source.rows("crash")),
                )
            metrics["declared_count_delta"] = sum(deltas)
            expected["declared_count_delta"] = 0
            for row in differences:
                findings.add(row[2], "declared_vehicle_count", actual=row)
    if kind == "node_raw":
        metrics["coordinate_conflict_group_count"] = sum(
            len(
                {
                    coordinate(
                        r["payload"].get("LATITUDE"), r["payload"].get("LONGITUDE")
                    )
                    for r in g
                }
                - {None}
            )
            > 1
            for g in groups.values()
        )
        expected.update(
            duplicate_group_count=None, coordinate_conflict_group_count=None
        )
        if source.official_vic:
            _, policy = restricted_inputs()
            missing = sorted(
                (
                    r["_raw"]["payload"]["ACCIDENT_NO"],
                    r["_raw"]["payload"].get("NODE_ID"),
                    r["_raw"]["payload"]["ACCIDENT_DATE"],
                    r["_raw"]["row_locator"],
                )
                for r in source.all_crashes
                if not source.nodes[
                    (
                        r["_raw"]["payload"]["ACCIDENT_NO"],
                        r["_raw"]["payload"].get("NODE_ID"),
                    )
                ]
            )
            registered = sorted(
                (
                    r["accident_no"],
                    r["node_id"],
                    r["occurrence_date"],
                    r["accident"]["row_locator"],
                )
                for r in policy["cases"]["missing_node_matches"]
            )
            metrics.update(
                case_set_match=missing == registered,
                full_count_difference_count=None,
                analysis_count_difference_count=None,
            )
            expected.update(
                policy["qa_expectations"][RULES[1]]["expected_metrics_by_resource"][
                    file["resource_id"]
                ]
            )
            if missing != registered:
                findings.add(
                    file["resource_id"],
                    "node_case_set",
                    actual=missing,
                    expected=registered,
                )
    if source.official_vic:
        metrics["restriction_violation_count"] = len(restriction)
        expected["restriction_violation_count"] = 0
        findings.rows.update(restriction.rows)
    nulls = {
        k: "Not a confirmed comparable count; native observations are retained."
        for k, v in expected.items()
        if v is None
    }
    refs = _refs(source) + [{"null_metric_reasons": nulls}]
    return _row(
        RULES[1],
        "resource:" + file["resource_id"],
        metrics,
        expected,
        len(raw),
        file["raw_count"],
        findings,
        refs,
        details=details,
    )


def qa05(source, projected, crashes, units, restriction):
    details = []
    profile_evidence = {}
    findings = Findings()
    _coverage(source, findings)
    for f in source.files:
        for row in source.raw[f["resource_id"]]:
            for reason in source.semantic_errors.get(row["raw_record_id"], ()):
                findings.raw(row, f, reason)
    for f in source.files:
        if f["entity_kind"] not in ("crash", "unit"):
            continue
        actual = [
            r
            for kind, r in projected
            if kind == f["entity_kind"] and r["source_id"] == source.sid
        ]
        stored = [
            r
            for r in (crashes if f["entity_kind"] == "crash" else units)
            if r["source_id"] == source.sid
        ]
        _compare(
            source,
            f,
            actual,
            source.projected[f["resource_id"]],
            findings,
            semantics=True,
        )
        _compare(
            source,
            f,
            stored,
            source.projected[f["resource_id"]],
            findings,
            semantics=True,
        )
    metrics = {
        "undefined_category_count": sum(
            bool(v) for v in source.semantic_errors.values()
        ),
        "unconfirmed_definition_count": 0,
        "eligibility_error_count": len(findings),
    }
    expected = dict.fromkeys(metrics, 0)
    if source.official_vic:
        _, policy = restricted_inputs()
        categories = policy["category_observations"]
        vc = Counter(r["payload"].get("VEHICLE_TYPE") for r in source.rows("vehicle"))
        pc = Counter(r["payload"].get("ROAD_USER_TYPE") for r in source.rows("person"))
        for role, field, token in [
            ("vehicle", "VEHICLE_TYPE", "21"),
            ("person", "ROAD_USER_TYPE", "16"),
        ]:
            for row in source.rows(role):
                if row["payload"].get(field) != token:
                    continue
                parents = source.crashes.get(row["payload"].get("ACCIDENT_NO"), [])
                in_scope = len(parents) == 1 and source.in_scope(
                    parents[0]["occurrence_year"]
                )
                details.append(
                    {
                        "reference": reference(row, source.by_role[role]),
                        "field": field,
                        "raw_token": token,
                        "in_scope": in_scope,
                        "reason_code": "definition_unconfirmed",
                    }
                )
        analysis_count = sum(row["in_scope"] for row in details)
        profile_evidence = {
            "undefined_category_rows": {
                "full": len(details),
                "analysis": analysis_count,
            },
            "publisher_unconfirmed_ids": [
                d["id"]
                for d in policy["unresolved_definitions"]
                if not d["publisher_confirmed"]
            ],
        }
        match = (
            vc == categories["vehicle_type_full_counts"]
            and pc == categories["person_road_user_full_counts"]
            and analysis_count == categories["analysis_undefined_category_rows"]
        )
        metrics.update(
            undefined_category_count=vc["21"] + pc["16"],
            unconfirmed_definition_count=sum(
                not d["publisher_confirmed"] for d in policy["unresolved_definitions"]
            ),
            disposition_match=match and not len(restriction),
            restriction_violation_count=len(restriction),
        )
        expected = policy["qa_expectations"][RULES[2]].copy()
        if not match:
            findings.add(
                source.sid,
                "restricted_category_membership",
                vehicle=dict(vc),
                person=dict(pc),
            )
        findings.rows.update(restriction.rows)
    refs = _refs(source) + [
        {
            "definition_version": source.p["severity_version"],
            "coverage": source.manifest["analysis"],
            "restricted_profile": source.official_vic,
            **profile_evidence,
        }
    ]
    return _row(
        RULES[2],
        "source:" + source.sid,
        metrics,
        expected,
        sum(map(len, source.raw.values())),
        sum(f["raw_count"] for f in source.files),
        findings,
        refs,
        details=details,
    )


def qa07(source, year, crashes, facts, invalid_raw=()):
    wanted = [
        r
        for r in source.projected[source.by_role["crash"]["resource_id"]]
        if r["occurrence_year"] == year
    ]
    actual = [
        r
        for r in facts
        if r["source_id"] == source.sid and r["occurrence_year"] == year
    ]
    stored = [
        r
        for r in crashes
        if r["source_id"] == source.sid and r["occurrence_year"] == year
    ]
    findings = Findings()
    _coverage(source, findings)
    detail = []
    invalid = set()
    by_key = {r["crash_key"]: r for r in wanted}
    for label, rows in [("fact", actual), ("canonical", stored)]:
        grouped = defaultdict(list)
        for r in rows:
            grouped[r["crash_key"]].append(r)
        for crash_key, w in by_key.items():
            matches = grouped.pop(crash_key, [])
            if len(matches) != 1:
                findings.raw(
                    w["_raw"],
                    source.by_role["crash"],
                    label + "_membership",
                    actual=len(matches),
                )
            for row in matches:
                fields = [
                    "source_id",
                    "release_scope",
                    "crash_key",
                    "occurrence_year",
                    "map_eligible",
                    "latitude",
                    "longitude",
                ]
                if label == "canonical":
                    fields += ["location_crs", "raw_record_id", "location_record_id"]
                diffs = different(row, w, fields)
                if diffs:
                    findings.raw(
                        w["_raw"],
                        source.by_role["crash"],
                        label + "_location",
                        fields=diffs,
                    )
                    if row.get("map_eligible"):
                        invalid.add(crash_key)
                if label == "canonical" and not w["map_eligible"]:
                    note = row["quality_notes"].get("location", {})
                    if (
                        note.get("reason_code") != w["_location_reason"]
                        or not note.get("resolution")
                        or not note.get("evidence_ref")
                    ):
                        findings.raw(
                            w["_raw"],
                            source.by_role["crash"],
                            "location_reason",
                            actual=note,
                            expected=w["_location_reason"],
                        )
        for crash_key, extra in grouped.items():
            reason = "unexpected_crash" if source.in_scope(year) else "outside_analysis_year"
            findings.add(label + ":" + crash_key, reason, actual=extra,
                         analysis=source.manifest["analysis"])
    for w in wanted:
        if not w["map_eligible"]:
            detail.append(
                {
                    "reference": reference(w["_raw"], source.by_role["crash"]),
                    "reason_code": w["_location_reason"],
                    "location_references": [
                        reference(
                            r, source.by_role.get("node", source.by_role["crash"])
                        )
                        for r in w["_location_refs"]
                    ],
                }
            )
    for row in invalid_raw:
        findings.raw(row, source.by_role["crash"], "invalid_raw_crash",
                     reasons=sorted(source.errors[row["raw_record_id"]]))
    mapped = sum(r["map_eligible"] is True for r in actual)
    expected_maps = sum(r["map_eligible"] for r in wanted)
    metrics = {
        "crash_count": len(actual),
        "map_count": mapped,
        "unmapped_count": len(actual) - mapped,
        "invalid_eligible_count": len(invalid),
    }
    expected = {
        "crash_count": len(wanted),
        "map_count": expected_maps,
        "unmapped_count": len(wanted) - expected_maps,
        "invalid_eligible_count": 0,
    }
    if metrics != expected:
        findings.add(
            f"{source.sid}:{year}", "location_counts", actual=metrics, expected=expected
        )
    refs = _refs(source) + [
        {
            "coverage": None if not wanted else expected_maps / len(wanted),
            "basis": "Selected Raw coordinates and exact Node observations, before reading D03 facts.",
        }
    ]
    return _row(
        RULES[3],
        f"source_year:{source.sid}:{year}",
        metrics,
        expected,
        len(actual),
        len(wanted),
        findings,
        refs,
        limited=len(wanted) - expected_maps,
        details=detail,
    )


def qa07_unknown_year(source, invalid_raw):
    findings = Findings()
    for row in invalid_raw:
        findings.raw(row, source.by_role["crash"], "invalid_raw_crash",
                     reasons=sorted(source.errors[row["raw_record_id"]]))
        findings.raw(row, source.by_role["crash"], "unknown_occurrence_year")
    return _row(
        RULES[3], "unknown_year:" + source.sid,
        {"unassigned_raw_count": len(invalid_raw)}, {"unassigned_raw_count": 0},
        len(invalid_raw), 0, findings, _refs(source),
    )


def _summaries(rows):
    result = []
    for rule in RULES:
        group = [r for r in rows if r["rule_id"] == rule]
        counts = Counter(r["result"] for r in group)
        metrics = {
            "object_count": len(group),
            "pass_count": counts["pass"],
            "limited_count": counts["limited"],
            "block_count": counts["block"],
            "missing_count": 0,
        }
        expected = {
            **metrics,
            "pass_count": counts["pass"] + counts["block"],
            "block_count": 0,
        }
        affected = sum(r["affected_count"] for r in group)
        state = (
            "block" if counts["block"] else "limited" if counts["limited"] else "pass"
        )
        result.append(
            {
                "rule_id": rule,
                "object_key": "batch",
                "result": state,
                "affected_count": affected,
                "actual": {
                    "evaluated_count": len(group),
                    "violation_count": counts["block"],
                    "metrics": metrics,
                },
                "expected": {
                    "evaluated_count": len(group),
                    "violation_count": 0,
                    "metrics": expected,
                },
                "evidence": {
                    "reason_codes": ["object_blocked"]
                    if counts["block"]
                    else ["location_isolated"]
                    if counts["limited"]
                    else [],
                    "resolution": "Aggregate of the concrete objects; no double-counting."
                    if group
                    else "No applicable objects in the frozen manifest.",
                    "references": [],
                    "producer_version": PRODUCER_VERSION,
                },
                "raw_record_id": None,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return result


def evaluate(connection, manifest, batch_id):
    raw = defaultdict(list)
    selected = {f["resource_id"]: f for f in manifest["files"]}
    headers = {rid: set(f["header"]) for rid, f in selected.items()}
    # Validate complete native shapes, then keep only fields used by these checks.
    used = {
        "Crash ID",
        "Traffic unit ID",
        "Year of crash",
        "Month of crash",
        "Degree of crash - detailed",
        "No. killed",
        "No. seriously injured",
        "No. moderately injured",
        "No. minor-other injured",
        "No. of traffic units involved",
        "Latitude",
        "Longitude",
        "TU type group",
        "ACCIDENT_NO",
        "ACCIDENT_DATE",
        "SEVERITY",
        "NO_PERSONS_KILLED",
        "NO_PERSONS_INJ_2",
        "NO_PERSONS_INJ_3",
        "NO_OF_VEHICLES",
        "NO_PERSONS",
        "NODE_ID",
        "VEHICLE_ID",
        "VEHICLE_TYPE",
        "PERSON_ID",
        "ROAD_USER_TYPE",
        "LATITUDE",
        "LONGITUDE",
        "Crash_Ref_Number",
        "Crash_Year",
        "Crash_Month",
        "Crash_Severity",
        "Crash_Latitude",
        "Crash_Longitude",
        "Count_Casualty_Fatality",
        "Count_Casualty_Hospitalised",
        "Count_Casualty_MedicallyTreated",
        "Count_Casualty_MinorInjury",
        "Count_Casualty_Total",
        "CRASH_ID",
        "YEAR",
        "MONTH",
        "FATALITIES",
        "CASUALTIES",
    }
    with connection.cursor(name="c10_raw_" + uuid4().hex) as cur:
        cur.execute(_sql("c10_qa03_expectation.sql"), (json.dumps(manifest["files"]),))
        for rid, resource, locator, payload in cur:
            valid = set(payload) == headers[resource] and all(
                v is None or isinstance(v, str) for v in payload.values()
            )
            raw[resource].append(
                {
                    "raw_record_id": rid,
                    "resource_id": resource,
                    "row_locator": locator,
                    "_native_valid": valid,
                    "payload": {k: v for k, v in payload.items() if k in used},
                }
            )
    projected = _fetch(
        connection, "c10_qa03_projected.sql", (str(batch_id), str(batch_id))
    )
    units = [
        r[0] for r in _fetch(connection, "c10_qa04_auxiliary.sql", (str(batch_id),))
    ]
    crashes = [
        r[0] for r in _fetch(connection, "c10_qa05_semantics.sql", (str(batch_id),))
    ]
    facts = [
        r[0] for r in _fetch(connection, "c10_qa07_location.sql", (str(batch_id),))
    ]
    sources = [Source(manifest, s, raw, batch_id) for s in manifest["sources"]]
    persons = {}
    if any(f["entity_kind"] == "person_raw" for f in manifest["files"]):
        for report in review_manifest(connection, FrozenManifest(json.dumps(manifest))):
            rid = next(
                f["resource_id"]
                for f in report["selected_files"]
                if f["entity_kind"] == "person_raw"
            )
            persons[rid] = report
    rows = []
    for source in sources:
        restriction = _restrictions(source, crashes, units, facts)
        for file in source.files:
            if file["entity_kind"] in ("crash", "unit"):
                rows.append(qa03(source, file, projected))
            if file["entity_kind"] in ("unit", "person_raw", "node_raw"):
                rows.append(
                    qa04(source, file, persons.get(file["resource_id"]), restriction)
                )
        rows.append(qa05(source, projected, crashes, units, restriction))
        invalid_by_year = defaultdict(list)
        for row in source.rows("crash"):
            if source.errors.get(row["raw_record_id"]):
                invalid_by_year[source.raw_year(row["payload"])].append(row)
        years = set(range(
            manifest["analysis"]["year_from"], manifest["analysis"]["year_to"] + 1
        ))
        # Inspect actual years too; out-of-scope stored rows must not disappear.
        years.update(r["occurrence_year"] for records in (crashes, facts) for r in records
                     if r["source_id"] == source.sid)
        years.update(year for year in invalid_by_year if year is not None)
        for year in sorted(years):
            rows.append(qa07(source, year, crashes, facts, invalid_by_year[year]))
        if invalid_by_year[None]:
            rows.append(qa07_unknown_year(source, invalid_by_year[None]))
    selected = {s.sid for s in sources}
    unexpected = [
        r
        for r in [*(r for _, r in projected), *crashes, *units, *facts]
        if r["source_id"] not in selected
    ]
    if unexpected:
        f = Findings()
        for r in unexpected:
            f.add(r.get("raw_record_id", r["crash_key"]), "unselected_source", actual=r)
        rows.append(
            _row(
                RULES[2],
                "unexpected:source",
                {"unexpected_count": len(unexpected)},
                {"unexpected_count": 0},
                len(unexpected),
                0,
                f,
                [],
            )
        )
    return rows


def runner_callback(connection, context):
    if (
        not isinstance(context.manifest, FrozenManifest)
        or connection.autocommit is not False
    ):
        raise IntakeError(
            "C10_INPUT", "C10 requires a real FrozenManifest and caller transaction"
        )
    manifest = context.manifest.as_dict()
    if context.dataset_kind != manifest["dataset_kind"]:
        raise IntakeError("C10_INPUT", "Context/manifest dataset kind mismatch")
    with connection.cursor() as cur:
        cur.execute(
            "SELECT status,dataset_kind,manifest FROM meta.batch WHERE batch_id=%s::uuid",
            (str(context.batch_id),),
        )
        if cur.fetchone() != ("running", context.dataset_kind, manifest):
            raise IntakeError(
                "C10_INPUT", "Batch is not running or its frozen manifest differs"
            )
        cur.execute(
            "SELECT count(*) FROM qa.check_result WHERE batch_id=%s::uuid AND rule_id=ANY(%s)",
            (str(context.batch_id), list(RULES)),
        )
        if cur.fetchone()[0]:
            raise IntakeError(
                "C10_EXISTS", "C10 results already exist; use a new batch"
            )
    try:
        rows = evaluate(connection, manifest, context.batch_id)
    except (ValueError, KeyError, TypeError, IntakeError) as exc:
        ref = context.evidence.write_json(
            "c10-input-error.json",
            {
                "batch_id": str(context.batch_id),
                "producer_version": PRODUCER_VERSION,
                "exception": type(exc).__name__,
                "message": str(exc),
            },
        )
        raise IntakeError(
            "C10_INPUT", "C10 could not evaluate the frozen inputs", evidence_ref=ref
        ) from exc
    for index, row in enumerate(rows):
        details = row.pop("_details")
        if details:
            ref = context.evidence.write_json(
                f"c10-detail-{index:03}.json",
                {
                    "rule_id": row["rule_id"],
                    "object_key": row["object_key"],
                    "row_count": len(details),
                    "rows": details,
                },
            )
            row["evidence"]["references"].append(
                {**ref, "detail_row_count": len(details)}
            )
    summaries = _summaries(rows)
    ref = context.evidence.write_json(
        "c10-results.json",
        {
            "batch_id": str(context.batch_id),
            "producer_version": PRODUCER_VERSION,
            "rows": rows,
            "summaries": summaries,
        },
    )
    for row in summaries:
        row["evidence"]["references"] = [ref]
    write_results(connection, context.batch_id, QAReport(tuple(rows + summaries)))
    if any(r["result"] == "block" for r in rows):
        raise IntakeError(
            "C10_BLOCK", "C10 found blocking differences", evidence_ref=ref
        )
    return {
        "c10_object_count": len(rows),
        "c10_summary_count": len(summaries),
        "limited_count": sum(r["result"] == "limited" for r in rows),
    }
