"""Declarative, source-specific crash intake for additional Australian states.

Original local platform implementation. A profile declares meanings; neither
column aliases nor a model's confidence constitute source approval. Original
payloads are retained in an attempt-owned SQLite staging artifact. Canonical
crashes are streamed to JSONL for the PostgreSQL publication transaction.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from .date_bounds import MIN_YEAR, MAX_YEAR

import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .errors import NeedsInput, ValidationFailure
from .readers import inspect_file, iter_rows

STATES = {"NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"}
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
NOTES = {".json", ".txt", ".md", ".pdf"}
MAX_PROFILE_BYTES = 262144


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def _need(message):
    raise NeedsInput(message, [message])


def _fail(code, message, **metrics):
    raise ValidationFailure(message, [{"code": code, "status": "block",
                                       "message": message, "metrics": metrics}])


def _text(value, name, limit=4096):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        _need(f"Declare a nonempty {name} (at most {limit} characters).")
    return value


def _field_list(value, name):
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        _need(f"{name} must list 1–16 distinct fields.")
    fields = [_text(v, name, 256) for v in value]
    if len(set(fields)) != len(fields):
        _need(f"{name} contains duplicate fields.")
    return fields


def validate_profile(profile):
    if not isinstance(profile, dict) or len(_json(profile).encode()) > MAX_PROFILE_BYTES:
        _need("Provide a mapping profile JSON object no larger than 256 KiB.")
    allowed = {"profile_version", "source_id", "jurisdiction", "source_name", "publisher",
               "source_evidence", "licence", "confirmed", "analysis", "resources", "relations",
               "mapping", "severity"}
    if set(profile) - allowed:
        _need("Unknown profile properties: " + ", ".join(sorted(set(profile) - allowed)))
    if profile.get("profile_version") != "generic-v1" or profile.get("confirmed") is not True:
        _need("Review the field meanings and source evidence, then set profile_version to generic-v1 and confirmed to true.")
    sid = _text(profile.get("source_id"), "source_id", 64)
    if not IDENTIFIER.fullmatch(sid) or sid.startswith(("official_", "syn_")):
        _need("Use a stable local source_id such as wa_crashes, without official_ or syn_ prefixes.")
    if profile.get("jurisdiction") not in STATES:
        _need("Declare one Australian state or territory in jurisdiction.")
    for field in ("source_name", "publisher", "source_evidence", "licence"):
        _text(profile.get(field), field)
    analysis = profile.get("analysis", {})
    if not isinstance(analysis, dict) or set(analysis) != {"year_from", "year_to"}:
        _need("analysis must declare year_from and year_to.")
    if (any(type(analysis[k]) is not int for k in analysis)
            or not MIN_YEAR <= analysis["year_from"] <= analysis["year_to"] <= MAX_YEAR):
        _need("Declare an ordered analysis year range between 1800 and 2200.")
    resources = profile.get("resources")
    if not isinstance(resources, list) or not 1 <= len(resources) <= 8:
        _need("resources must declare 1–8 data tables.")
    roles, names = {}, set()
    for r in resources:
        if not isinstance(r, dict) or set(r) - {"role", "filename", "sheet", "key"}:
            _need("Each resource accepts role, filename, sheet and key only.")
        role = _text(r.get("role"), "resource role", 64)
        if not IDENTIFIER.fullmatch(role) or role in roles:
            _need("Resource roles must be unique lowercase identifiers.")
        name = _text(r.get("filename"), "resource filename", 255)
        if Path(name).name != name or name in names:
            _need("Resource filenames must be unique uploaded basenames.")
        if "sheet" in r:
            _text(r["sheet"], "worksheet name", 128)
        _field_list(r.get("key"), f"{role} key")
        roles[role] = r
        names.add(name)
    if "crash" not in roles:
        _need("Declare exactly one crash resource. Aggregated monthly tables are not individual crash rows.")
    mapping = profile.get("mapping")
    mapping_fields = {"year", "month", "date", "date_format", "severity", "fatalities",
                      "casualties", "declared_units", "unit_type"}
    if not isinstance(mapping, dict) or set(mapping) - mapping_fields:
        _need("Provide the declared crash mapping fields; executable transformations are not accepted.")
    for key, value in mapping.items():
        if key == "casualties":
            _field_list(value, "casualty component fields")
        else:
            _text(value, f"mapping.{key}", 256)
    if "severity" not in mapping:
        _need("Declare the native severity field and its source-specific categories.")
    if "date" in mapping:
        if "year" in mapping or "month" in mapping or "date_format" not in mapping:
            _need("Use either date with an explicit date_format, or year with optional numeric month.")
        fmt = mapping["date_format"]
        if fmt not in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y", "%Y-%m-%dT%H:%M:%S"):
            _need("Choose a supported explicit date format; ambiguous dates are not guessed.")
    elif "year" not in mapping or "date_format" in mapping:
        _need("Declare the occurrence year field, or a date and its explicit format.")
    if ("unit_type" in mapping or "declared_units" in mapping) and "unit" not in roles:
        _need("Unit fields require a complete unit resource and its crash relationship.")
    severity = profile.get("severity")
    if not isinstance(severity, dict) or not 1 <= len(severity) <= 100:
        _need("Declare 1–100 native severity categories, with explicit missing values if applicable.")
    seen_codes = set()
    for native, definition in severity.items():
        if not isinstance(native, str) or len(native) > 256 or not isinstance(definition, dict):
            _need("Severity categories must map native text to category objects.")
        if set(definition) != {"code", "label", "is_fatal_crash"}:
            _need("Each severity category needs code, label and is_fatal_crash.")
        code = _text(definition["code"], "severity code", 64)
        _text(definition["label"], "severity label", 256)
        if code in seen_codes:
            _need("Use distinct severity codes; undocumented category merging is not supported.")
        seen_codes.add(code)
        if definition["is_fatal_crash"] is not None and type(definition["is_fatal_crash"]) is not bool:
            _need("is_fatal_crash must be true, false, or null for an explicitly unknown category.")
    relations = profile.get("relations", [])
    if not isinstance(relations, list) or len(relations) > 16:
        _need("relations must be a list of at most 16 declared key relationships.")
    edges = set()
    for rel in relations:
        if not isinstance(rel, dict) or set(rel) - {"child", "parent", "fields", "allow_blank"}:
            _need("Each relationship accepts child, parent, fields, and allow_blank only.")
        child, parent = rel.get("child"), rel.get("parent")
        if child not in roles or parent not in roles or child == parent or (child, parent) in edges:
            _need("Relationships must name distinct registered roles without duplicate edges.")
        fields = _field_list(rel.get("fields"), "relationship fields")
        if len(fields) != len(roles[parent]["key"]):
            _need("Relationship fields must correspond in order to the parent's complete key.")
        if "allow_blank" in rel and type(rel["allow_blank"]) is not bool:
            _need("allow_blank must be a boolean backed by the source definition.")
        if child == "unit" and parent == "crash" and rel.get("allow_blank"):
            _need("Published units require a known crash parent.")
        edges.add((child, parent))
    if "unit" in roles and ("unit", "crash") not in edges:
        _need("Declare the unit-to-crash relationship before computing unit results.")
    for role in roles:
        if role != "crash" and not any(c == role for c, _ in edges):
            _need(f"Declare the parent relationship for the {role} resource.")
    # Reject disconnected cyclic auxiliary graphs: every table must reach crash.
    reachable = {"crash"}
    for _ in roles:
        reachable.update(c for c, p in edges if p in reachable)
    if set(roles) != reachable:
        _need("Every auxiliary resource must connect to the crash table.")
    return roles


def _integer(value, label, nullable=False):
    if value in (None, "") and nullable:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
        _fail("QA05_SEMANTICS", f"{label} must be an explicit non-negative integer; unknown values are not filled.")
    number = int(value)
    if number > 2**31 - 1:
        _fail("QA05_SEMANTICS", f"{label} exceeds the supported integer range.")
    return number


def _key(payload, fields, label, allow_blank=False):
    values = [payload[f] for f in fields]
    if all(v in (None, "") for v in values) and allow_blank:
        return None
    if any(v in (None, "") for v in values):
        _fail("QA03_PROJECTED", f"{label} has an incomplete key; identifiers are never generated.")
    return _json(values)


def _time(payload, mapping):
    if "date" in mapping:
        value = payload[mapping["date"]]
        try:
            parsed = datetime.strptime(value or "", mapping["date_format"])
        except (ValueError, TypeError):
            _fail("QA05_SEMANTICS", "A date does not match the explicitly declared occurrence-date format.")
        return parsed.year, parsed.month
    year = _integer(payload[mapping["year"]], "Occurrence year")
    if not MIN_YEAR <= year <= MAX_YEAR:
        _fail("QA05_SEMANTICS", "Occurrence year is outside the declared supported range.")
    month = _integer(payload[mapping["month"]], "Occurrence month", True) if "month" in mapping else None
    if month is not None and not 1 <= month <= 12:
        _fail("QA05_SEMANTICS", "Occurrence month must be 1–12 or explicitly missing.")
    return year, month


def _aggregate(rows):
    rows = list(rows)
    return {"crash_count": len(rows),
            "fatal_crash_count": None if any(r[0] is None for r in rows) else sum(r[0] for r in rows),
            "fatalities": None if any(r[1] is None for r in rows) else sum(r[1] for r in rows),
            "casualties": None if any(r[2] is None for r in rows) else sum(r[2] for r in rows)}


def _sql_aggregate(db, year=None):
    clause = "selected=1" + (" AND year=?" if year is not None else "")
    args = (year,) if year is not None else ()
    row = db.execute(f"SELECT count(*),count(fatal),sum(fatal),count(fatalities),sum(fatalities),count(casualties),sum(casualties) FROM canonical WHERE {clause}", args).fetchone()
    count = row[0]
    return {"crash_count": count,
            "fatal_crash_count": (row[2] or 0) if row[1] == count else None,
            "fatalities": (row[4] or 0) if row[3] == count else None,
            "casualties": (row[6] or 0) if row[5] == count else None}


def process_generic(files, work_dir, options, progress, check_cancelled):
    profile = options["profile"]
    roles = validate_profile(profile)
    if options.get("source_hint") and str(options["source_hint"]).upper() not in ("AUTO", profile["jurisdiction"], profile["source_id"].upper()):
        _need("The chosen state and the reviewed profile disagree.")
    by_name = {file["name"]: file for file in files}
    if len(by_name) != len(files):
        _need("Resolve duplicate uploaded filenames before assigning resource roles.")
    selected_names = {r["filename"] for r in roles.values()}
    missing = selected_names - by_name.keys()
    if missing:
        _need("Upload the missing resources: " + ", ".join(sorted(missing)))
    extra = [f["name"] for f in files if f["name"] not in selected_names and Path(f["name"]).suffix.lower() not in NOTES]
    if extra:
        _need("Assign or remove unregistered data files: " + ", ".join(extra))

    tables = {}
    mapping = profile["mapping"]
    relations = profile.get("relations", [])
    for role, resource in roles.items():
        available = inspect_file(by_name[resource["filename"]])
        if resource.get("sheet"):
            available = [t for t in available if t.get("sheet") == resource["sheet"]]
        if len(available) != 1:
            _need(f"Choose one explicit worksheet for {role}; found {len(available)} matches.")
        table = available[0]
        needed = set(resource["key"])
        needed.update(f for rel in relations if rel["child"] == role for f in rel["fields"])
        if role == "crash":
            needed.update(v for k, v in mapping.items() if k not in ("date_format", "unit_type", "casualties"))
            needed.update(mapping.get("casualties", []))
        elif role == "unit" and mapping.get("unit_type"):
            needed.add(mapping["unit_type"])
        absent = needed - set(table["header"])
        if absent:
            _need(f"The {role} mapping refers to missing columns: " + ", ".join(sorted(absent)))
        tables[role] = table

    work_dir = Path(work_dir)
    db = sqlite3.connect(work_dir / "staging.sqlite")
    try:
        db.executescript("""
          PRAGMA journal_mode=DELETE;
          PRAGMA temp_store=FILE;
          PRAGMA cache_size=-16384;
          CREATE TABLE raw_rows(role TEXT, pk TEXT, locator TEXT, payload TEXT,
                                PRIMARY KEY(role,pk));
          CREATE TABLE relations(child TEXT, child_pk TEXT, parent TEXT, parent_pk TEXT);
          CREATE INDEX rel_parent ON relations(parent,parent_pk);
          CREATE TABLE canonical(pk TEXT PRIMARY KEY, year INTEGER, month INTEGER, severity TEXT,
              fatal INTEGER, fatalities INTEGER, casualties INTEGER, selected INTEGER, payload TEXT);
          CREATE INDEX canon_year ON canonical(selected,year);
          CREATE TABLE declared_units(pk TEXT PRIMARY KEY, expected INTEGER NOT NULL);
        """)
        counts, field_usage = {}, {}
        progress("processing", "Parsing the reviewed source contract and preserving original rows.")
        for role, resource in roles.items():
            file = by_name[resource["filename"]]
            counts[role] = 0
            used = set(resource["key"])
            for rel in relations:
                if rel["child"] == role:
                    used.update(rel["fields"])
            if role == "crash":
                used.update(v for k, v in mapping.items() if k not in ("date_format", "unit_type", "casualties"))
                used.update(mapping.get("casualties", []))
            elif role == "unit" and "unit_type" in mapping:
                used.add(mapping["unit_type"])
            field_usage[role] = {"used": sorted(used), "retained_raw_only": [f for f in tables[role]["header"] if f not in used]}
            for locator, payload in iter_rows(file, tables[role], check_cancelled):
                counts[role] += 1
                pk = _key(payload, resource["key"], role)
                try:
                    db.execute("INSERT INTO raw_rows VALUES (?,?,?,?)", (role, pk, _json(locator), _json(payload)))
                except sqlite3.IntegrityError:
                    _fail("QA03_PROJECTED", f"Duplicate {role} primary key; the source must resolve it.", row=counts[role])
                for rel in relations:
                    if rel["child"] == role:
                        parent_pk = _key(payload, rel["fields"], f"{role} parent", rel.get("allow_blank", False))
                        if parent_pk is not None:
                            db.execute("INSERT INTO relations VALUES (?,?,?,?)", (role, pk, rel["parent"], parent_pk))
                if role == "crash":
                    year, month = _time(payload, mapping)
                    native_severity = payload[mapping["severity"]]
                    severity = profile["severity"].get(native_severity if native_severity is not None else "")
                    if severity is None:
                        _fail("QA05_SEMANTICS", "An observed severity category has no reviewed definition.", row=counts[role])
                    fatalities = _integer(payload[mapping["fatalities"]], "Fatality count", True) if "fatalities" in mapping else None
                    components = [_integer(payload[f], "Casualty component", True) for f in mapping.get("casualties", [])]
                    casualties = sum(components) if components and all(v is not None for v in components) else None
                    if fatalities is not None and casualties is not None and fatalities > casualties:
                        _fail("QA05_SEMANTICS", "Fatalities exceed the declared casualty total.", row=counts[role])
                    selected = profile["analysis"]["year_from"] <= year <= profile["analysis"]["year_to"]
                    canonical = {"record_id": pk, "source_id": profile["source_id"], "resource_id": role,
                                 "year": year, "month": month, "severity": severity["code"],
                                 "is_fatal_crash": severity["is_fatal_crash"], "fatalities": fatalities,
                                 "casualties": casualties, "row_locator": locator, "raw_file_sha256": file["sha256"],
                                 "latitude": None, "longitude": None, "location_reason": "crs_unconfirmed"}
                    db.execute("INSERT INTO canonical VALUES (?,?,?,?,?,?,?,?,?)",
                               (pk,year,month,severity["code"],severity["is_fatal_crash"],fatalities,casualties,selected,_json(canonical)))
                    if "declared_units" in mapping:
                        expected = _integer(payload[mapping["declared_units"]], "Declared unit count")
                        db.execute("INSERT INTO declared_units VALUES (?,?)", (pk,expected))
                if counts[role] % 5000 == 0:
                    db.commit()
                    check_cancelled()
                    progress("processing", f"Parsed {counts[role]:,} {role} records.", resource=role, records=counts[role])
            if not counts[role]:
                _fail("QA02_RAW", f"The required {role} resource is empty.")
            db.commit()
        check_cancelled()
        progress("validating", "Checking complete-file relationships and independent reconciliations.")
        orphan = db.execute("""SELECT count(*) FROM relations r LEFT JOIN raw_rows p
                ON p.role=r.parent AND p.pk=r.parent_pk WHERE p.pk IS NULL""").fetchone()[0]
        if orphan:
            _fail("QA04_AUXILIARY", "Child rows reference missing parents; no links were repaired.", orphan_count=orphan)
        if "declared_units" in mapping:
            mismatch = db.execute("""SELECT count(*) FROM declared_units d LEFT JOIN
              (SELECT parent_pk,count(*) n FROM relations WHERE child='unit' AND parent='crash' GROUP BY parent_pk) r
              ON r.parent_pk=d.pk WHERE d.expected!=coalesce(r.n,0)""").fetchone()[0]
            if mismatch:
                _fail("QA04_AUXILIARY", "Declared unit totals do not match the complete child file.", mismatched_crashes=mismatch)
        summary = _sql_aggregate(db)
        if not summary["crash_count"]:
            _fail("QA06_RECONCILIATION", "The selected analysis range contains no crashes; publishing an empty replacement requires a separate policy.")
        summary.update(raw_record_count=sum(counts.values()), excluded_crash_count=counts["crash"]-summary["crash_count"],
                       year_from=profile["analysis"]["year_from"], year_to=profile["analysis"]["year_to"])
        trend = [{"year": y, **_sql_aggregate(db,y)} for y in range(summary["year_from"],summary["year_to"]+1)]
        severity_counts = dict(db.execute("SELECT severity,count(*) FROM canonical WHERE selected=1 GROUP BY severity"))
        severity_rows = [{"code": s["code"], "label": s["label"], "count": severity_counts.get(s["code"],0),
                          "is_fatal_crash": s["is_fatal_crash"]} for s in profile["severity"].values()]
        if sum(r["crash_count"] for r in trend) != summary["crash_count"] or sum(r["count"] for r in severity_rows) != summary["crash_count"]:
            _fail("QA06_RECONCILIATION", "Annual and severity outputs do not reconcile with canonical crashes.")
        canonical_path = work_dir / "canonical.jsonl"
        with canonical_path.open("x", encoding="utf-8") as output:
            for n, (payload,) in enumerate(db.execute("SELECT payload FROM canonical WHERE selected=1 ORDER BY pk"),1):
                output.write(payload+"\n")
                if n % 5000 == 0:
                    check_cancelled()
        units = {"status": "unavailable", "scope": "Source-specific units", "rows": [], "reason": "No reviewed unit resource supplied."}
        unit_count, units_path = None, None
        if "unit" in roles:
            unit_count = 0
            type_counts = Counter()
            units_path = work_dir / "units.jsonl"
            with units_path.open("x", encoding="utf-8") as output:
                for pk, payload, parent in db.execute("""SELECT u.pk,u.payload,r.parent_pk FROM raw_rows u
                      JOIN relations r ON r.child='unit' AND r.child_pk=u.pk AND r.parent='crash'
                      JOIN canonical c ON c.pk=r.parent_pk AND c.selected=1 WHERE u.role='unit' ORDER BY u.pk"""):
                    unit_count += 1
                    values = json.loads(payload)
                    unit_type = values.get(mapping.get("unit_type")) if mapping.get("unit_type") else None
                    type_counts[unit_type] += 1
                    output.write(_json({"record_id":pk,"crash_record_id":parent,"unit_type":unit_type,"source_id":profile["source_id"]})+"\n")
                    if unit_count % 5000 == 0:
                        check_cancelled()
            units = {"status":"available","scope":f"{profile['source_name']} native units; no interstate equivalence assumed",
                     "rows":[{"unit_type":key,"count":count} for key,count in sorted(type_counts.items(),key=lambda x:str(x[0]))]}
        summary["unit_count"] = unit_count
        evidence_files = [{k:f[k] for k in ("id","name","size","sha256") if k in f} for f in files]
        identity = {"profile":profile, "files":sorted([{"name":f["name"],"sha256":f["sha256"]} for f in files],key=lambda f:f["name"])}
        qa = [
          {"code":"QA01_INPUT","status":"pass","message":"Uploaded structure matches the explicitly confirmed local source contract."},
          {"code":"QA02_RAW","status":"pass","message":"Complete native rows retained in staging with file hashes and row locators.","metrics":{"records":counts}},
          {"code":"QA03_PROJECTED","status":"pass","message":"Full-file keys are nonempty and unique; only the declared occurrence range is selected."},
          {"code":"QA04_AUXILIARY","status":"pass","message":"All declared relationships and unit totals reconcile.","metrics":{"orphans":0,"relations":len(relations)}},
          {"code":"QA05_SEMANTICS","status":"pass","message":"Dates, severity and count semantics follow the confirmed profile; missing counts remain unknown."},
          {"code":"QA06_RECONCILIATION","status":"pass","message":"Canonical counts, annual series and severity distribution reconcile."},
          {"code":"QA07_LOCATION","status":"limited","message":"No validated coordinate transformation is declared. Map points remain unavailable.","metrics":{"eligible":0,"total":summary["crash_count"],"reason":"crs_unconfirmed"}}
        ]
        result = {"source_id":profile["source_id"],"profile_id":"generic:"+profile["source_id"],"profile_version":"generic-v1",
                  "fingerprint":hashlib.sha256(_json(identity).encode()).hexdigest(),"summary":summary,"trend":trend,
                  "severity":severity_rows,"units":units,"limitations":["Local test publication based on a user-confirmed profile; not publisher certification.",
                   "Source-specific measures only; interstate totals are not combined.","Official map points are unavailable without a reviewed CRS transformation."],
                  "qa":qa,"files":evidence_files,"canonical_path":str(canonical_path),
                  "evidence":{"profile":profile,"file_counts":counts,"field_usage":field_usage,"retention":"Immutable uploaded originals plus complete attempt-owned SQLite raw staging.",
                              "raw_grain":"Resource-specific rows; raw record totals are not crash counts."}}
        if units_path:
            result["units_path"] = str(units_path)
        return result
    finally:
        db.close()


def describe_unknown(files):
    schemas = []
    for file in files:
        if Path(file["name"]).suffix.lower() in (".csv", ".xlsx"):
            for table in inspect_file(file):
                schemas.append({"filename":file["name"],"format":table["format"],"sheet":table.get("sheet"),"columns":table["header"]})
    return {"schemas":schemas,"profile_example":"pipeline/examples/wa-profile.json",
            "questions":["Which state or territory and publisher produced this extract? Supply its source definition or data dictionary.",
                         "Which table contains individual crashes, and which fields identify each crash and its child rows?",
                         "Declare the occurrence-date format, native severity meanings, casualty definitions and analysis years in a reviewed generic-v1 mapping profile."]}
