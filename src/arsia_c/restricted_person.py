"""C06 checks for the pinned VIC policy; this does not authorize publication."""
from collections import Counter
from copy import deepcopy
import hashlib
import json

from .person_checks import ROOT, ROLES, _fail, _run, _selection


POLICY_PATH = ROOT / "config/vic-restricted-use-v1.json"
INPUT_PATH = ROOT / "config/c06-vic-r1.json"
MAPPING_ID = "official_vic_restricted_use"


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def restricted_inputs():
    """Return disposable copies of the supported declarations and adopted policy."""
    spec = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    data = POLICY_PATH.read_bytes()
    if hashlib.sha256(data).hexdigest() != spec["policy_sha256"]:
        _fail("The adopted policy changed; review a new C06 version")
    return spec, json.loads(data)


def review_restricted(connection, files, analysis, policy):
    """Inspect all selected Raw rows, without a build or publication claim."""
    spec, supported = restricted_inputs()
    if _canonical(policy) != _canonical(supported) or _canonical(analysis) != _canonical(spec["analysis"]):
        _fail("Unsupported C06 policy or analysis years")
    if (not isinstance(files, list) or len(files) != len(spec["files"])
            or any(not isinstance(f, dict) for f in files)):
        _fail("C06 restricted review needs the four pinned file declarations")
    if sorted(map(_canonical, files)) != sorted(map(_canonical, spec["files"])):
        _fail("C06 selected files differ from the adopted snapshot")
    selected = [{**f, "role": role} for role in ROLES for f in files
                if f["resource_id"] == f"official_vic_{role}"]
    _selection(selected, analysis)
    return _run(connection, selected, analysis, synthetic=False,
                restricted=RestrictedChecks(policy))


def review_restricted_manifest(connection, value):
    """Called only after B has validated a FrozenManifest for the new protocol."""
    spec, policy = restricted_inputs()
    if value["rules"]["qa_contract"]["version"] != spec["protocol_version"]:
        _fail("Official C06 requires team-v1.1-vic-r1; legacy QA remains blocked")
    entries = [m for m in value["rules"]["mappings"] if m["id"] == MAPPING_ID]
    if (len(entries) != 1 or entries[0]["version"] != spec["profile_id"]
            or _canonical(entries[0]["content"]) != _canonical(policy)):
        _fail("Freeze the complete supported VIC policy in its mapping entry")
    selected = [f for f in value["files"] if f["source_id"] == policy["source_id"]]
    ids = {f["resource_id"] for f in selected}
    contracts = [c for c in value["rules"]["contracts"] if c["id"] in ids]
    if (len(contracts) != 4 or any(MAPPING_ID not in c["mapping_ids"] for c in contracts)
            or any(f["entity_kind"] == "person_raw" and f["source_id"] != policy["source_id"]
                   for f in value["files"])):
        _fail("All VIC contracts must reference the policy; other Person rules are unsupported")
    return review_restricted(connection, selected, value["analysis"], entries[0]["content"])


def _refs(values):
    return sorted(({"resource_id": v["resource_id"], "row_locator": v["row_locator"]}
                   for v in values), key=lambda v: (v["resource_id"], v["row_locator"]))


def _case(value, kind):
    """Compare native evidence, excluding dispositions and database-generated IDs."""
    common = ("accident_no", "scope", "occurrence_date", "accident")
    fields = common + (("declared", "observed", "person_refs", "vehicle_refs")
                       if kind == "counts" else
                       ("person_id", "vehicle_id", "person", "native_person_fields"))
    result = {k: value[k] for k in fields}
    if kind == "unmatched":
        result["available_vehicle_refs"] = _refs(value["available_vehicle_refs"])
        result["missing_target"] = value["missing_target"]
    if kind == "counts":
        for key in ("person_refs", "vehicle_refs"):
            result[key] = _refs(result[key])
    return _canonical(result)


class RestrictedChecks:
    """Accumulate SQL observations against independent policy expectations."""

    def __init__(self, policy):
        self.policy = deepcopy(policy)
        self.accident_resource = policy["source_id"] + "_accident"
        self.person_resource = policy["source_id"] + "_person"
        cases = policy["cases"]
        self.expected = {
            "unmatched": {_case(c, "unmatched") for c in cases["unmatched_person_vehicle"]},
            "blank": {_case(c, "blank") for c in cases["unknown_role_blank_vehicle"]},
            "counts": {_case(c, "counts") for c in cases["declared_count_differences"]
                       if c["entity"] == "person"},
        }
        self.observed = {key: set() for key in self.expected}
        self.counts = Counter()
        self.duplicates = set()
        self.limitations = Counter()

    def observe(self, row):
        role = row["kind"]
        self.counts[role] += 1
        issues = row["issues"]
        if role == "person":
            for key in ("native_person_fields", "parent_locator", "occurrence_date",
                        "available_vehicle_refs", "parent_match_count", "vehicle_reference"):
                if key not in row:
                    _fail("Restricted Person SQL omitted case evidence", field=key)
            if "duplicate_person_key" in issues:
                self.duplicates.add((row["accident_no"], row["person_id"]))
            if row["parent_match_count"] == 0:
                self.counts["orphans"] += 1
            reference = row["vehicle_reference"]
            if reference == "allowed_pedestrian_blank":
                self.counts["pedestrian_full"] += 1
                self.counts["pedestrian_analysis"] += row["in_scope"] is True
            if reference not in {"unmatched", "unresolved_blank"}:
                return
            kind = "unmatched" if reference == "unmatched" else "blank"
            candidate = {
                "accident_no": row["accident_no"], "person_id": row["person_id"],
                "vehicle_id": row["vehicle_id"], "scope": self._scope(row),
                "occurrence_date": row["occurrence_date"],
                "person": {"resource_id": row["resource_id"], "row_locator": row["row_locator"]},
                "accident": {"resource_id": self.accident_resource, "row_locator": row["parent_locator"]},
                "native_person_fields": row["native_person_fields"],
                "available_vehicle_refs": row["available_vehicle_refs"],
                "missing_target": [row["accident_no"], row["vehicle_id"]],
            }
            self.counts[kind + "_full"] += 1
            self.counts[kind + "_analysis"] += row["in_scope"] is True
            self._recognize(row, candidate, kind,
                            "unmatched_nonblank_vehicle_ref" if kind == "unmatched"
                            else "blank_vehicle_reference_unconfirmed")
        elif role == "accident":
            if "diagnostic_count_delta" not in row:
                _fail("Restricted Accident SQL omitted the diagnostic comparison")
            if row["count_state"] == "diagnostic":
                self.counts["diagnostic_comparisons"] += 1
            if row["diagnostic_count_delta"] in (None, 0):
                return
            candidate = {
                "accident_no": row["accident_no"], "scope": self._scope(row),
                "occurrence_date": row["date_text"],
                "declared": row["declared_count"], "observed": row["observed_count"],
                "accident": {"resource_id": row["resource_id"], "row_locator": row["row_locator"]},
                "person_refs": row["person_references"], "vehicle_refs": row["vehicle_references"],
            }
            self.counts["counts_full"] += 1
            self.counts["counts_analysis"] += row["in_scope"] is True
            self._recognize(row, candidate, "counts", None)

    @staticmethod
    def _scope(row):
        return "2020-2024" if row["in_scope"] is True else (
            "outside_2020-2024" if row["in_scope"] is False else "unresolved")

    def _recognize(self, row, candidate, kind, native_issue):
        identity = _case(candidate, kind)
        self.observed[kind].add(identity)
        if identity in self.expected[kind]:
            if native_issue in row["issues"]:
                row["issues"].remove(native_issue)
            row["restricted_disposition"] = "registered_native_limitation"
            self.limitations[kind] += 1
        else:
            row["issues"].append("unregistered_" + kind + "_case")
        row["case_evidence"] = candidate

    def finish(self, report):
        missing = {k: [json.loads(c) for c in sorted(self.expected[k] - self.observed[k])]
                   for k in self.expected}
        unexpected = {k: [json.loads(c) for c in sorted(self.observed[k] - self.expected[k])]
                      for k in self.expected}
        match = not any(missing.values()) and not any(unexpected.values())
        checks = {"case_set_match": match}
        blank = self.policy["blank_vehicle_rules"]["pedestrian_nonassociation"]
        checks["pedestrian_count_match"] = (
            self.counts["pedestrian_full"] == blank["expected_full_rows"]
            and self.counts["pedestrian_analysis"] == blank["expected_analysis_rows"])
        for kind, name in (("unmatched", "unmatched_person_vehicle"),
                           ("blank", "unknown_role_blank_vehicle"),
                           ("counts", "declared_person_differences")):
            checks[name + "_count_match"] = all(
                self.counts[kind + "_" + scope] == self.policy["case_counts"][name][scope]
                for scope in ("full", "analysis"))
        for key, passed in checks.items():
            if not passed:
                report["reason_counts"][key + "_failed"] = 1
                report["status"] = "block"
        # Summary failures are separate from distinct offending Raw rows.
        report["summary_violation_count"] = sum(not value for value in checks.values())
        metrics = {
            "orphan_count": self.counts["orphans"],
            "nonblank_unmatched_count": self.counts["unmatched_full"],
            "declared_count_delta": None, "duplicate_group_count": len(self.duplicates),
            "coordinate_conflict_group_count": None, "case_set_match": match,
            "full_count_difference_count": self.counts["counts_full"],
            "analysis_count_difference_count": self.counts["counts_analysis"],
        }
        expected = self.policy["qa_expectations"]["QA04_AUXILIARY"]["expected_metrics_by_resource"][self.person_resource]
        report.update({
            "profile_id": self.policy["profile_id"], "protocol_version": self.policy["protocol_version"],
            "policy_case_sha256": self.policy["case_set_digest"]["sha256"],
            "dataset_kind": self.policy["dataset_kind"],
            "team_use_approved": self.policy["authority"]["team_use_approved"],
            "publication_authorized": False,
            "policy_checks": checks, "missing_cases": missing, "unexpected_cases": unexpected,
            "registered_limitations": dict(self.limitations),
            "observed_counts": dict(self.counts),
            "qa04_person_contribution": {
                "resource_id": self.person_resource, "evaluated_count": self.counts["person"],
                "actual_metrics": metrics, "expected_metrics": {k: expected[k] for k in metrics},
                "unexecuted_metrics": {"restriction_violation_count": "C10 must verify D's output restrictions"},
                "null_reasons": {"declared_count_delta": "Common export completeness remains unconfirmed",
                                 "coordinate_conflict_group_count": "Person has no location observations"},
            },
            "unavailable_outputs": self.policy["unavailable_outputs"],
        })
        return report
