"""E06 checks for the agreed QA fields, coverage and evidence."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from .models import IntakeError
from .vic_restricted import validate_profile, vic_restricted_definitions

METRICS = {
    "QA01_INPUT": "hash_match header_match bundle_confirmed contract_confirmed",
    "QA02_RAW": "raw_count distinct_locator_count payload_mismatch_count",
    "QA03_PROJECTED": "input_count excluded_count projected_count duplicate_key_count orphan_count invalid_value_count",
    "QA04_AUXILIARY": "orphan_count nonblank_unmatched_count declared_count_delta duplicate_group_count coordinate_conflict_group_count",
    "QA05_SEMANTICS": "undefined_category_count unconfirmed_definition_count eligibility_error_count",
    "QA06_RECONCILIATION": "missing_fact_count extra_fact_count field_mismatch_count lineage_error_count definition_error_count crash_delta fatal_crash_delta fatality_delta casualty_delta fatal_crash_known_delta fatality_known_delta casualty_known_delta",
    "QA07_LOCATION": "crash_count map_count unmapped_count invalid_eligible_count",
}


def fail(message, code="PUBLICATION_QA"):
    raise IntakeError(code, message)


def same(actual, expected):
    # JSON booleans must not compare equal to the integer 0 or 1.
    return type(actual) is type(expected) and actual == expected


def count(value):
    return type(value) is int and value >= 0


def shape(value):
    if (not isinstance(value, dict)
            or set(value) != {"evaluated_count", "violation_count", "metrics"}
            or not count(value["evaluated_count"])
            or not count(value["violation_count"])
            or not isinstance(value["metrics"], dict)):
        fail("Invalid actual/expected shape")


def evidence(row, files, cache, *, batch_id=None, concrete=None, empty=False):
    rule, object_key = row[:2]
    targets = list(concrete) if concrete is not None else [row]
    by_key = {r[1]: r for r in targets}
    wanted, seen = set(by_key), set()

    def identity(ref):
        key = ref.get("object_key")
        if key is not None and key not in wanted:
            fail("Evidence object differs from the checked object", "PUBLICATION_QA_EVIDENCE")
        if "rule_id" in ref and ref["rule_id"] != rule:
            fail("Evidence rule differs from the checked rule", "PUBLICATION_QA_EVIDENCE")
        if key is not None and "result" in ref and ref["result"] != by_key[key][2]:
            fail("Evidence disposition differs from its object", "PUBLICATION_QA_EVIDENCE")
        rid, sid, year = ref.get("resource_id"), ref.get("source_id"), ref.get("occurrence_year")
        if rid is not None and rid not in files:
            fail("Evidence resource is not frozen", "PUBLICATION_QA_EVIDENCE")
        if rid is not None:
            sid = files[rid]["source_id"]
        if rid is None and sid is None and year is None:
            if object_key == "batch" and key is not None:
                seen.add(key)
            return
        allowed = False
        for target in wanted:
            parts = target.split(":")
            kind = parts[0]
            target_file = files.get(parts[1]) if kind in {"file", "resource"} else None
            target_source = target_file["source_id"] if target_file else parts[1]
            if sid != target_source:
                continue
            if kind == "file":
                matched = rid == parts[1]
                allowed |= matched
            elif kind == "resource":
                # C includes parent/child references from the same source.
                allowed = True
                matched = rid == parts[1]
            elif kind == "source":
                allowed = True
                matched = rid is not None or sid is not None
            else:
                if year is not None and (type(year) is not int or year != int(parts[2])):
                    continue
                allowed = True
                matched = (year == int(parts[2]) and ref.get("batch_id") == batch_id)
                if rule == "QA07_LOCATION":
                    matched |= rid is not None
            if matched:
                seen.add(target)
        if not allowed:
            fail("Evidence belongs to another QA object or source-year", "PUBLICATION_QA_EVIDENCE")

    item = row[6]
    if (not isinstance(item, dict)
            or not isinstance(item.get("reason_codes"), list)
            or any(not isinstance(s, str) or not s.strip() for s in item["reason_codes"])
            or any(not isinstance(item.get(k), str) or not item[k].strip()
                   for k in ("resolution", "producer_version"))
            or not isinstance(item.get("references"), list)
            or (not empty and not item["references"])):
        fail("Missing QA evidence fields", "PUBLICATION_QA_EVIDENCE")
    if row[2] == "limited" and not item["reason_codes"]:
        fail("Limited results need reasons", "PUBLICATION_QA_EVIDENCE")
    details, null_reasons, coverage = [], {}, []

    def visit(ref):
        if isinstance(ref, list):
            for child in ref:
                visit(child)
        elif isinstance(ref, dict):
            identity(ref)
            if "batch_id" in ref and ref["batch_id"] != batch_id:
                fail("Evidence refers to another batch", "PUBLICATION_QA_EVIDENCE")
            if "source_id" in ref and ref["source_id"] not in {f["source_id"] for f in files.values()}:
                fail("Evidence refers to another source", "PUBLICATION_QA_EVIDENCE")
            if "resource_id" in ref:
                file = files.get(ref["resource_id"])
                if file is None or any(k in ref and ref[k] != file[k]
                                      for k in ("file_sha256", "parser_version", "source_id")):
                    fail("Evidence refers to a different frozen file", "PUBLICATION_QA_EVIDENCE")
            if "coverage" in ref and "basis" in ref:
                coverage.append(ref["coverage"])
            if "null_metric_reasons" in ref:
                reasons = ref["null_metric_reasons"]
                if not isinstance(reasons, dict):
                    fail("Invalid NULL metric reasons", "PUBLICATION_QA_EVIDENCE")
                null_reasons.update(reasons)
            if "path" in ref or "sha256" in ref:
                path, digest = ref.get("path"), ref.get("sha256")
                if (not isinstance(path, str) or not path
                        or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                    fail("A detail file needs its path and SHA256", "PUBLICATION_QA_EVIDENCE")
                key = (path, digest)
                if key not in cache:
                    try:
                        data = Path(path).read_bytes()
                        if hashlib.sha256(data).hexdigest() != digest:
                            fail("Evidence file hash changed", "PUBLICATION_QA_EVIDENCE")
                        parsed = ([json.loads(line) for line in data.splitlines()]
                                  if Path(path).suffix == ".jsonl" else json.loads(data))
                    except (OSError, ValueError) as exc:
                        raise IntakeError("PUBLICATION_QA_EVIDENCE", "Evidence file is missing or invalid", path=path) from exc
                    cache[key] = parsed
                parsed = cache[key]
                if isinstance(parsed, dict):
                    if "rule_id" in parsed or "object_key" in parsed:
                        identity(parsed)
                    if "batch_id" in parsed and parsed["batch_id"] != batch_id:
                        fail("Evidence document belongs to another batch", "PUBLICATION_QA_EVIDENCE")
                    if object_key == "batch" and isinstance(parsed.get("rows"), list):
                        selected = [r for r in parsed["rows"] if r.get("rule_id") == rule]
                        keys = [r.get("object_key") for r in selected]
                        if Counter(keys) != Counter({k: 1 for k in wanted}):
                            fail("Evidence document does not cover this summary", "PUBLICATION_QA_EVIDENCE")
                        fields = ("rule_id", "object_key", "result", "affected_count", "actual", "expected", "evidence")
                        if any(tuple(r.get(k) for k in fields) != by_key[r["object_key"]] for r in selected):
                            fail("Evidence document differs from stored QA objects", "PUBLICATION_QA_EVIDENCE")
                        seen.update(keys)
                if "detail_row_count" in ref:
                    rows = parsed.get("rows") if isinstance(parsed, dict) else None
                    if (not isinstance(rows, list) or not count(ref["detail_row_count"])
                            or len(rows) != ref["detail_row_count"]
                            or parsed.get("row_count") != len(rows)):
                        fail("Detail rows do not match their count", "PUBLICATION_QA_EVIDENCE")
                    details.extend(rows)
                records = len(parsed) if Path(path).suffix == ".jsonl" else 1
                if "row_count" in ref and (not count(ref["row_count"]) or records != ref["row_count"]):
                    fail("Evidence records do not match their count", "PUBLICATION_QA_EVIDENCE")
            for child in ref.values():
                if isinstance(child, (dict, list)):
                    visit(child)

    for ref in item["references"]:
        if (not isinstance(ref, dict) or not ref
                or not set(ref) & {"resource_id", "source_id", "object_key", "path", "null_metric_reasons", "coverage", "definition_version"}):
            fail("Evidence references need an object identity or detail file", "PUBLICATION_QA_EVIDENCE")
        visit(ref)
    if seen != wanted:
        fail("Evidence does not identify every checked object", "PUBLICATION_QA_EVIDENCE")
    return details, null_reasons, coverage


class Requirements:
    def __init__(self, connection, batch_id, manifest):
        self.connection, self.batch, self.manifest = connection, batch_id, manifest
        self.files = {f["resource_id"]: f for f in manifest["files"]}
        self.restricted = validate_profile(manifest)
        self.policy = (vic_restricted_definitions()["mappings"][0]["content"]["qa_expectations"]
                       if self.restricted else {})
        self.cache = {}

    def query(self, sql, params):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def expected(self, rule, key):
        file = self.files.get(key.split(":")[1])
        metrics = dict.fromkeys(METRICS[rule].split(), 0)
        if rule == "QA01_INPUT":
            metrics = (self.policy[rule].copy() if file["resource_id"] in self.restricted
                       else dict.fromkeys(metrics, True))
            return 1, metrics
        if rule == "QA02_RAW":
            n = file["raw_count"]
            return n, dict(raw_count=n, distinct_locator_count=n, payload_mismatch_count=0)
        if rule == "QA03_PROJECTED":
            # QA03 verifies exclusions from Raw. E also ties its coverage to stored Canonical rows.
            n = self.query(f"""SELECT count(*) FROM canonical.{file['entity_kind']} c
                JOIN raw.record r ON r.raw_record_id=c.raw_record_id
                WHERE c.batch_id=%s AND r.resource_id=%s AND r.file_sha256=%s
                  AND r.parser_version=%s""", (self.batch, file["resource_id"],
                                             file["file_sha256"], file["parser_version"]))[0][0]
            if n > file["raw_count"]:
                fail("Projection exceeds the frozen input", "PUBLICATION_QA_COVERAGE")
            metrics.update(input_count=file["raw_count"], excluded_count=file["raw_count"]-n, projected_count=n)
            return n, metrics
        if rule == "QA04_AUXILIARY":
            if file["resource_id"] in self.restricted:
                return file["raw_count"], self.policy[rule]["expected_metrics_by_resource"][file["resource_id"]].copy()
            kind = file["entity_kind"]
            metrics.update(nonblank_unmatched_count=None, declared_count_delta=None, coordinate_conflict_group_count=None)
            if kind == "person_raw":
                metrics.update(nonblank_unmatched_count=0, declared_count_delta=0)
            elif kind == "node_raw":
                metrics["duplicate_group_count"] = None
            else:
                source = next(s for s in self.manifest["sources"] if s["source_id"] == file["source_id"])
                declared = any(m["content"].get("declared_unit_count", {}).get("resource_id") == file["resource_id"]
                               for m in self.manifest["rules"]["mappings"])
                if source["jurisdiction_code"] == "VIC" or declared:
                    metrics["declared_count_delta"] = 0
            return file["raw_count"], metrics
        if rule == "QA05_SEMANTICS":
            source = key.removeprefix("source:")
            selected = [f for f in self.files.values() if f["source_id"] == source]
            if any(f["resource_id"] in self.restricted for f in selected):
                metrics = self.policy[rule].copy()
            return sum(f["raw_count"] for f in selected), metrics
        _, source, year = key.split(":")
        n, mapped = self.query("""SELECT count(*),count(*) FILTER (WHERE map_eligible)
            FROM canonical.crash WHERE batch_id=%s AND source_id=%s AND occurrence_year=%s""",
                              (self.batch, source, int(year)))[0]
        if rule == "QA07_LOCATION":
            fact_counts = self.query("""SELECT count(*),count(*) FILTER (WHERE map_eligible)
                FROM dw.fact_crash WHERE batch_id=%s AND source_id=%s AND occurrence_year=%s""",
                                     (self.batch, source, int(year)))[0]
            if fact_counts != (n, mapped):
                fail("Location coverage differs between Canonical and DW", "PUBLICATION_QA_COVERAGE")
            if source == "official_vic" and self.restricted and mapped:
                fail("Restricted VIC cannot publish map points")
            metrics.update(crash_count=n, map_count=mapped, unmapped_count=n-mapped, invalid_eligible_count=0)
        return n, metrics

    def check(self, row):
        rule, key, result, affected, actual, expected, _ = row
        for value in (actual, expected):
            shape(value)
            if value["violation_count"] != 0:
                fail("A QA object has violations", "PUBLICATION_QA_VIOLATION")
        if result not in {"pass", "limited"} or not count(affected):
            fail("Invalid result or affected count")
        if result == "limited" and rule != "QA07_LOCATION":
            fail("Only QA07 can be limited", "PUBLICATION_QA_LIMITED")
        details, reasons, coverage = evidence(row, self.files, self.cache, batch_id=self.batch)
        n, wanted = self.expected(rule, key)
        if actual["evaluated_count"] != n or expected["evaluated_count"] != n:
            fail("QA evaluation did not reach required coverage", "PUBLICATION_QA_COVERAGE")
        if set(actual["metrics"]) != set(wanted) or set(expected["metrics"]) != set(wanted):
            fail("QA metric keys differ from the protocol", "PUBLICATION_QA_METRICS")
        for name, value in wanted.items():
            observed = actual["metrics"][name]
            if not same(expected["metrics"][name], value):
                fail("QA expectation differs from the frozen contract", "PUBLICATION_QA_EXPECTED")
            if value is None:
                node_observation = (rule == "QA04_AUXILIARY"
                                    and self.files[key.removeprefix("resource:")]["entity_kind"] == "node_raw"
                                    and name in {"duplicate_group_count", "coordinate_conflict_group_count"})
                if (node_observation and not count(observed)) or (not node_observation and observed is not None):
                    fail("Invalid diagnostic or inapplicable metric", "PUBLICATION_QA_METRICS")
                if not isinstance(reasons.get(name), str) or not reasons[name].strip():
                    fail("NULL expectations need reasons", "PUBLICATION_QA_EVIDENCE")
            elif not same(observed, value):
                fail("QA metric differs from its required value", "PUBLICATION_QA_METRICS")
        limited = wanted["unmapped_count"] if rule == "QA07_LOCATION" else 0
        if result != ("limited" if limited else "pass") or affected != limited:
            fail("QA result/affected count differs from concrete metrics", "PUBLICATION_QA_AFFECTED")
        if rule == "QA07_LOCATION":
            expected_coverage = wanted["map_count"] / n if n else None
            if (len(coverage) != 1 or coverage[0] != expected_coverage
                    or (n and type(coverage[0]) not in (float, int))):
                fail("Location coverage needs its real denominator", "PUBLICATION_QA_EVIDENCE")
            if limited:
                _, source, year = key.split(":")
                missing = dict(self.query("""SELECT raw_record_id::text,quality_notes->'location'->>'reason_code'
                    FROM canonical.crash WHERE batch_id=%s AND source_id=%s AND occurrence_year=%s
                    AND NOT map_eligible""", (self.batch, source, int(year))))
                identities = []
                for detail in details:
                    ref = detail.get("reference", {})
                    identity = ref.get("raw_record_id")
                    reason = detail.get("reason_code")
                    if not reason or missing.get(identity) != reason:
                        fail("Unmapped crash lacks its recorded reason", "PUBLICATION_QA_EVIDENCE")
                    identities.append(identity)
                if Counter(identities) != Counter({identity: 1 for identity in missing}):
                    fail("Limited evidence must cover each unmapped crash once", "PUBLICATION_QA_EVIDENCE")

    def summary(self, row, concrete):
        rule, _, result, affected, actual, expected, _ = row
        counts = Counter(r[2] for r in concrete)
        metrics = dict(object_count=len(concrete), pass_count=counts["pass"], limited_count=counts["limited"],
                       block_count=0, missing_count=0)
        for value in (actual, expected):
            shape(value)
            if (value["evaluated_count"] != len(concrete) or value["violation_count"] != 0
                    or set(value["metrics"]) != set(metrics)
                    or any(not same(value["metrics"][k], v) for k, v in metrics.items())):
                fail("Summary differs from concrete QA objects", "PUBLICATION_QA_SUMMARY")
        state = "limited" if counts["limited"] else "pass"
        total = sum(r[3] for r in concrete)
        if result != state or not count(affected) or affected != total:
            fail("Summary disposition differs from concrete QA objects", "PUBLICATION_QA_SUMMARY")
        evidence(row, self.files, self.cache, batch_id=self.batch, concrete=concrete, empty=not concrete)
        return {"rule_id": rule, "result": state, "affected_count": total}
