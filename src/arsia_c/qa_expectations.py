"""C10 expectations from selected Raw rows and frozen source rules."""

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import re

from .projections.nsw import _parameters as nsw_parameters
from .projections.sa import parameters as sa_parameters
from .projections.source_contracts import parameters, MONTHS, VIC_COUNTS, QLD_COUNTS

NSW_COUNTS = [
    "No. killed",
    "No. seriously injured",
    "No. moderately injured",
    "No. minor-other injured",
]


def key(*values):
    if any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValueError("blank_key")
    return json.dumps(values, ensure_ascii=False)


def number(value, *, empty=True):
    if value is None or (empty and value == ""):
        return None
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[0-9]+", value)
        or int(value) > 2147483647
    ):
        raise ValueError("invalid_count")
    return int(value)


def coordinate(lat, lon):
    try:
        pair = tuple(Decimal(v) for v in (lat, lon))
        if not all(v.is_finite() for v in pair) or not (
            -90 <= pair[0] <= 90 and -180 <= pair[1] <= 180
        ):
            return None
        return pair
    except (TypeError, ValueError, InvalidOperation):
        return None


def reference(row, file):
    return {
        k: file[k]
        for k in ("source_id", "resource_id", "file_sha256", "parser_version")
    } | {"raw_record_id": row["raw_record_id"], "row_locator": row["row_locator"]}


class Source:
    def __init__(self, manifest, source, raw, batch):
        self.manifest, self.source, self.batch = manifest, source, str(batch)
        self.sid = source["source_id"]
        self.state = source["jurisdiction_code"]
        self.files = [f for f in manifest["files"] if f["source_id"] == self.sid]
        self.by_role = {f["resource_role"]: f for f in self.files}
        if self.state not in ("NSW", "VIC", "QLD", "SA"):
            raise ValueError("unsupported_source")
        self.p = (
            nsw_parameters(manifest, batch)
            if self.state == "NSW"
            else sa_parameters(manifest, batch)
            if self.state == "SA"
            else parameters(manifest, batch, self.state)
        )
        roles = (
            {"crash", "traffic_unit"}
            if self.state == "NSW"
            else {"crash", "vehicle", "person", "node"}
            if self.state == "VIC"
            else {"crash"}
        )
        if set(self.by_role) != roles or len(self.files) != len(roles):
            raise ValueError("source_resource_coverage")
        self.raw = {f["resource_id"]: raw.get(f["resource_id"], []) for f in self.files}
        self.coverage = [
            f["resource_id"]
            for f in self.files
            if len(self.raw[f["resource_id"]]) != f["raw_count"]
        ]
        self.official_vic = (
            self.state == "VIC" and manifest["dataset_kind"] == "official"
        )
        self.errors = defaultdict(set)
        self.semantic_errors = defaultdict(set)
        self.projected = defaultdict(list)
        self.all_crashes = []
        self.crashes = defaultdict(list)
        self.nodes = defaultdict(list)
        if self.state == "VIC":
            for row in self.rows("node"):
                payload = row["payload"]
                self.nodes[(payload.get("ACCIDENT_NO"), payload.get("NODE_ID"))].append(
                    row
                )
        self._derive()

    def rows(self, role):
        return (
            self.raw[self.by_role[role]["resource_id"]] if role in self.by_role else []
        )

    def field_key(self):
        return {
            "NSW": "Crash ID", "VIC": "ACCIDENT_NO",
            "QLD": "Crash_Ref_Number", "SA": "CRASH_ID",
        }[self.state]

    def in_scope(self, year):
        a = self.manifest["analysis"]
        return year is not None and a["year_from"] <= year <= a["year_to"]

    def raw_year(self, payload):
        """Locate an invalid crash by its native year, even if its month/day is bad."""
        if self.state == "VIC":
            token = payload.get("ACCIDENT_DATE")
            if not isinstance(token, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", token):
                return None
            token = token[:4]
        else:
            token = payload.get({"NSW": "Year of crash", "QLD": "Crash_Year", "SA": "YEAR"}[self.state])
        if (isinstance(token, str) and re.fullmatch(r"[0-9]{4}", token)
                and 1900 <= int(token) <= 2100):
            return int(token)
        return None

    def time(self, payload):
        if self.state == "SA":
            year = self.raw_year(payload)
            if year is None:
                raise ValueError("invalid_year")
            month = payload.get("MONTH")
            if (not isinstance(month, str) or not re.fullmatch(r"[0-9]{1,2}", month)
                    or not 1 <= int(month) <= 12):
                raise ValueError("invalid_month")
            return year, int(month), None, "month"
        if self.state == "VIC":
            token = payload.get("ACCIDENT_DATE")
            if not isinstance(token, str) or not re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}", token
            ):
                raise ValueError("invalid_date")
            d = date.fromisoformat(token)
            if not 1900 <= d.year <= 2100:
                raise ValueError("invalid_year")
            return d.year, d.month, d.isoformat(), "day"
        year = payload.get("Year of crash" if self.state == "NSW" else "Crash_Year")
        if (
            not isinstance(year, str)
            or not re.fullmatch(r"[0-9]{4}", year)
            or not 1900 <= int(year) <= 2100
        ):
            raise ValueError("invalid_year")
        token = payload.get("Month of crash" if self.state == "NSW" else "Crash_Month")
        empty = self.state != "NSW" or self.manifest["dataset_kind"] == "synthetic"
        missing = token is None or (empty and token == "")
        month = (
            None
            if missing
            else MONTHS.get(token.strip())
            if isinstance(token, str)
            else None
        )
        if not missing and month is None:
            raise ValueError("invalid_month")
        return int(year), month, None, "year" if missing else "month"

    def location(self, row):
        payload = row["payload"]
        empty = {
            "latitude": None,
            "longitude": None,
            "location_crs": None,
            "location_record_id": None,
            "map_eligible": False,
        }
        if self.state == "VIC":
            observations = self.nodes[
                (payload.get("ACCIDENT_NO"), payload.get("NODE_ID"))
            ]
            pairs = [
                coordinate(r["payload"].get("LATITUDE"), r["payload"].get("LONGITUDE"))
                for r in observations
            ]
            if not observations:
                return empty, "no_location", []
            if None in pairs:
                return empty, "invalid_coordinate", observations
            if len(set(pairs)) != 1:
                return empty, "location_conflict", observations
            if not self.p["map_enabled"]:
                return empty, "crs_unconfirmed", observations
            chosen = min(
                observations, key=lambda r: int(r["row_locator"].split(":")[-1])
            )
            pair = pairs[0]
        else:
            fields = (
                ("Latitude", "Longitude")
                if self.state == "NSW"
                else ("LATITUDE", "LONGITUDE")
                if self.state == "SA"
                else ("Crash_Latitude", "Crash_Longitude")
            )
            values = [payload.get(f) for f in fields]
            pair = coordinate(*values)
            if not self.p["map_enabled"]:
                return (
                    empty,
                    "crs_unconfirmed"
                    if self.state in ("NSW", "SA")
                    else "definition_unconfirmed",
                    [row],
                )
            if pair is None:
                return (
                    empty,
                    "missing"
                    if any(v in (None, "") for v in values)
                    else "invalid_coordinate",
                    [row],
                )
            chosen = row
            observations = [row]
        return (
            {
                "latitude": pair[0].quantize(
                    Decimal(".0000001"), rounding=ROUND_HALF_UP
                ),
                "longitude": pair[1].quantize(
                    Decimal(".0000001"), rounding=ROUND_HALF_UP
                ),
                "location_crs": "EPSG:4326",
                "map_eligible": True,
                "location_record_id": chosen["raw_record_id"],
            },
            "",
            observations,
        )

    def crash(self, row):
        payload = row["payload"]
        y, m, d, precision = self.time(payload)
        native = payload.get(self.field_key())
        result = {
            "batch_id": self.batch,
            "source_id": self.sid,
            "release_scope": self.source["release_scope"],
            "crash_key": key(native),
            "raw_record_id": row["raw_record_id"],
            "occurrence_year": y,
            "occurrence_month": m,
            "occurrence_date": d,
            "date_precision": precision,
        }
        severity_field = {
            "NSW": "Degree of crash - detailed",
            "VIC": "SEVERITY",
            "QLD": "Crash_Severity",
            "SA": "SEVERITY",
        }[self.state]
        severity = payload.get(severity_field)
        empty = self.state != "NSW" or self.manifest["dataset_kind"] == "synthetic"
        mapping = json.loads(self.p["severity_map"])
        missing = severity is None or (empty and severity == "")
        classification = None if missing else mapping.get(severity)
        if missing and self.state == "NSW":
            contract = next(c for c in self.manifest["rules"]["contracts"]
                            if c["id"] == self.by_role["crash"]["resource_id"])
            declaration = next(m for m in self.manifest["rules"]["mappings"]
                               if m["id"] == contract["mapping_ids"][0])
            code = declaration["content"].get("missing_severity_code")
            if code is not None:
                definition = next(s for s in self.manifest["rules"]["severity"]
                                  if s["source_id"] == self.sid and s["severity_code"] == code)
                classification = {"code": code, "fatal": definition["is_fatal_crash"]}
                result["_severity_rule"] = {
                    "code": code, "reason": declaration["content"]["missing_severity_reason"],
                    "mapping_version": declaration["version"],
                }
        if not missing and classification is None:
            self.semantic_errors[row["raw_record_id"]].add("undefined_category")
            raise ValueError("undefined_category")
        fields = (
            NSW_COUNTS
            if self.state == "NSW"
            else VIC_COUNTS
            if self.state == "VIC"
            else ["FATALITIES", "CASUALTIES"]
            if self.state == "SA"
            else QLD_COUNTS
        )
        counts = [number(payload.get(f), empty=empty) for f in fields]
        if self.state == "SA":
            # SA supplies a total that already includes deaths.
            total = counts[1]
            if all(v is not None for v in counts) and total < counts[0]:
                raise ValueError("casualty_total_mismatch")
        else:
            total = None if any(v is None for v in counts) else sum(counts)
            if sum(v for v in counts if v is not None) > 2147483647:
                raise ValueError("count_overflow")
        if self.state == "QLD":
            declared = number(payload.get("Count_Casualty_Total"))
            if total is not None and declared != total:
                raise ValueError("casualty_total_mismatch")
        result.update(
            severity_raw=severity,
            severity_code=classification["code"] if classification else "__MISSING__",
            severity_definition_version=self.p["severity_version"],
            is_fatal_crash=classification["fatal"] if classification else None,
            fatality_count=counts[0],
            casualty_count=total,
            fatal_crash_eligible=classification is not None,
            fatality_eligible=counts[0] is not None,
            casualty_eligible=total is not None,
        )
        location, reason, observations = self.location(row)
        result.update(location)
        result["_location_reason"] = reason
        result["_location_refs"] = observations
        result["_raw"] = row
        result["_note_version"] = self.p.get(
            "crash_contract_version", self.p.get("contract_version")
        )
        return result

    def _derive(self):
        for f in self.files:
            for row in self.raw[f["resource_id"]]:
                p = row["payload"]
                valid = row.get("_native_valid")
                if valid is None:
                    valid = set(p) == set(f["header"]) and all(
                        v is None or isinstance(v, str) for v in p.values()
                    )
                if not valid:
                    self.errors[row["raw_record_id"]].add("native_fields_or_types")
        for row in self.rows("crash"):
            rid = row["raw_record_id"]
            try:
                derived = self.crash(row)
                self.all_crashes.append(derived)
                self.crashes[row["payload"].get(self.field_key())].append(derived)
                if self.in_scope(derived["occurrence_year"]):
                    self.projected[row["resource_id"]].append(derived)
            except (ValueError, TypeError) as exc:
                self.errors[rid].add(str(exc))
        for native, group in self.crashes.items():
            if len(group) > 1:
                for row in group:
                    self.errors[row["raw_record_id"]].add("duplicate_key")
        for f in self.files:
            if f["entity_kind"] == "crash":
                continue
            groups = defaultdict(list)
            fields = {
                "unit": [
                    self.field_key(),
                    "Traffic unit ID" if self.state == "NSW" else "VEHICLE_ID",
                ],
                "person_raw": ["ACCIDENT_NO", "PERSON_ID"],
                "node_raw": ["ACCIDENT_NO", "NODE_ID"],
            }[f["entity_kind"]]
            for row in self.raw[f["resource_id"]]:
                rid, p = row["raw_record_id"], row["payload"]
                try:
                    native_key = key(*(p.get(k) for k in fields))
                    groups[native_key].append(row)
                    parents = self.crashes.get(p.get(self.field_key()), [])
                    if len(parents) != 1:
                        self.errors[rid].add("orphan_or_ambiguous_parent")
                        continue
                    parent = parents[0]
                    if f["entity_kind"] != "unit":
                        continue
                    field = "TU type group" if self.state == "NSW" else "VEHICLE_TYPE"
                    token = p.get(field)
                    mapping = json.loads(self.p["unit_types"])
                    missing = token is None or (
                        token == ""
                        and (
                            self.state != "NSW"
                            or self.manifest["dataset_kind"] == "synthetic"
                        )
                    )
                    if not missing and token not in mapping:
                        self.semantic_errors[rid].add("undefined_category")
                        self.errors[rid].add("undefined_category")
                    projected = {
                        k: parent[k]
                        for k in ("batch_id", "source_id", "release_scope", "crash_key")
                    }
                    projected.update(
                        unit_key=native_key,
                        raw_record_id=rid,
                        unit_type_raw=token,
                        unit_type_code=None if missing else mapping.get(token),
                        statistical_scope=self.p["statistical_scope"],
                        count_eligible=not missing and not self.official_vic,
                        _raw=row,
                        _restricted=self.official_vic,
                        _note_version=self.p["unit_contract_version"],
                    )
                    if self.in_scope(parent["occurrence_year"]):
                        self.projected[f["resource_id"]].append(projected)
                except (ValueError, TypeError) as exc:
                    self.errors[rid].add(str(exc))
            if f["entity_kind"] != "node_raw":
                for group in groups.values():
                    if len(group) > 1:
                        for row in group:
                            self.errors[row["raw_record_id"]].add("duplicate_key")


def different(actual, expected, fields):
    diffs = []
    for field in fields:
        a, e = actual.get(field), expected.get(field)
        if field in ("latitude", "longitude") and a is not None:
            try:
                a = Decimal(str(a))
            except InvalidOperation:
                pass
        if a != e or (type(e) is bool and type(a) is not bool):
            diffs.append(field)
    return diffs


def missing_reasons(row, expected):
    notes = row.get("quality_notes")
    if not isinstance(notes, dict):
        return ["quality_notes"]
    fields = notes.get("fields", [])
    required = []
    for flag, field in [
        ("fatal_crash_eligible", "fatal_crash_eligible"),
        ("fatality_eligible", "fatality_count"),
        ("casualty_eligible", "casualty_count"),
        ("count_eligible", "count_eligible"),
    ]:
        if expected.get(flag) is False:
            required.append(field)
    missing = [
        f
        for f in required
        if not any(
            isinstance(n, dict)
            and n.get("field") == f
            and n.get("reason_code")
            == ("definition_unconfirmed" if expected.get("_restricted") else "missing")
            and n.get("contract_version") == expected["_note_version"]
            for n in fields
        )
    ]
    if expected.get("_severity_rule") is not None and notes.get("severity_rule") != expected["_severity_rule"]:
        missing.append("severity_rule")
    return missing
