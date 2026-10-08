"""Local, bounded execution of the three reviewed ARSIA native profiles.

Rules and original authorship are retained under profiles/upstream.json. This
new SQLite adapter implements the documented source decisions; it is NOT the
course Raw/Vault/Canonical/DW execution, E's SQL FP1, or production acceptance.
The original seven-file recipe remains untouched. All writes belong to one
isolated local-test attempt, and neither this module nor AI publishes a release.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from .date_bounds import MIN_YEAR, MAX_YEAR

import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .errors import NeedsInput, ValidationFailure
from .readers import READER_VERSION, inspect_file, iter_rows

PROFILE_DIR = Path(__file__).with_name("profiles")
VERSION = "local-native-sqlite-v1"
YEARS = (2020, 2024)
MONTHS = {v: i for i, v in enumerate("January February March April May June July August September October November December".split(), 1)}
ROLES = {"NSW": ("crash", "traffic_unit"), "VIC": ("crash", "vehicle", "person", "node"), "QLD": ("crash",)}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(path, check_cancelled=lambda: None):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while data := stream.read(1024 * 1024):
            digest.update(data)
            check_cancelled()
    return digest.hexdigest()


def _references():
    upstream = json.loads((PROFILE_DIR / "upstream.json").read_text())
    values = {}
    for pin in upstream["files"]:
        content = (PROFILE_DIR / pin["path"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != pin["sha256"]:
            raise ValidationFailure("A frozen source-rule reference changed; review a new profile.")
        values[pin["path"]] = json.loads(content)
    return upstream, values


def _supplement(file, tables=None):
    if file.get("role") in {"dictionary", "notes", "source_document"}:
        return True
    # Filename is never used to identify data roles. These are only non-table
    # evidence formats; their entire bytes still enter the fingerprint.
    if Path(file.get("name", "")).suffix.lower() in {".txt", ".md", ".json", ".pdf"}:
        return True
    if tables:
        for table in tables:
            header = {c.lower().replace(" ", "_") for c in table["header"]}
            if not (header & {"field", "field_name", "column", "column_name", "variable"}
                    and header & {"description", "definition", "meaning"}):
                return False
        return True
    return False


def _resembles_native(header):
    names = set(header)
    return (("Crash ID" in names and names & {"Year of crash", "Traffic unit ID"})
            or "Crash_Ref_Number" in names
            or "ACCIDENT_NO" in names)


def identify_bundle(files):
    """Recognize native roles by complete headers and sheet identity, not names.

    None means that no native source is recognized. A partial native package,
    duplicate role, mixed states, or changed native structure requires input;
    it must not fall through to a generic profile that evades source policy.
    """
    _, refs = _references()
    catalogue = refs["native-inputs.json"]["resources"]
    matched, supplements, unknown = [], [], []
    for file in files:
        if _supplement(file):
            supplements.append(file)
            continue
        try:
            tables = inspect_file(file)
        except (NeedsInput, ValidationFailure):
            # A broken or non-tabular attachment is not silently ignored.
            raise
        matches = [(entry, table) for table in tables for entry in catalogue
                   if table["header"] == entry["header"] and table["format"] == entry["format"]
                   and table["sheet"] == entry["sheet"]]
        if len(matches) == 1 and len(tables) == 1:
            entry, table = matches[0]
            matched.append({"file": file, "table": table, "spec": entry})
        elif matches or any(_resembles_native(t["header"]) for t in tables):
            raise NeedsInput("A native source has an unreviewed worksheet or column layout.",
                             ["Provide the reviewed original export, or register a new source-profile version."],
                             {"file_id": file.get("id")})
        elif _supplement(file, tables):
            supplements.append(file)
        else:
            unknown.append(file)
    if not matched:
        return None
    states = {row["spec"]["source_id"].removeprefix("official_").upper() for row in matched}
    if len(states) != 1:
        raise NeedsInput("One import must contain one state's complete file bundle.",
                         ["Create separate tasks for each state."], {"states": sorted(states)})
    state = states.pop()
    by_role = {}
    for row in matched:
        role = row["spec"]["resource_role"]
        if role in by_role:
            raise NeedsInput("Two files claim the same source role.", [f"Select exactly one {state} {role} file."])
        by_role[role] = row
    missing = sorted(set(ROLES[state]) - set(by_role))
    if missing:
        raise NeedsInput(f"The {state} bundle is incomplete.",
                         [f"Upload the missing {state} resource: {role}." for role in missing],
                         {"source_id": f"official_{state.lower()}", "missing_roles": missing})
    if unknown:
        raise NeedsInput("Unrecognized data tables accompany the native bundle.",
                         ["Identify the extra tables as source documentation or submit them in a separate import."],
                         {"file_ids": [f.get("id") for f in unknown]})
    return {"state": state, "source_id": f"official_{state.lower()}", "files_by_role": by_role,
            "supplements": supplements, "profile_id": f"{state.lower()}-pinned-local-2020-2024"}


def _block(message, code="QA05_SEMANTICS", **details):
    raise ValidationFailure(message, [{"code": code, "status": "block", "message": message,
                                        "metrics": details}], details)


def _key(value, field, locator):
    if not isinstance(value, str) or not value.strip():
        _block("A required native key is blank; no replacement identifier is generated.",
               "QA04_AUXILIARY", field=field, row_locator=locator)
    return value


def _number(value, field, locator, *, empty=True, required=False):
    if value is None or (empty and value == ""):
        if required:
            _block("A required declared count is missing.", field=field, row_locator=locator)
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value) or int(value) > 2147483647:
        _block("A count is not a nonnegative source integer.", field=field, row_locator=locator)
    return int(value)


def _sum_known(values):
    if any(v is None for v in values):
        return None
    total = sum(values)
    if total > 2147483647:
        _block("A source casualty sum exceeds the supported integer range.")
    return total


def _profile(state, refs):
    if state == "NSW":
        original = refs["official-nsw-v1.json"]
        definitions = original["severity"]["categories"]
        severity = [{"code": d["severity_code"], "label": d["severity_label"],
                     "is_fatal_crash": d["is_fatal_crash"]} for d in definitions]
        native = {d["native_value"]: d["severity_code"] for d in definitions if d["native_value"] is not None}
        counts = {c["resource_id"]: c["input"]["raw_count"] for c in original["contracts"]}
        return original, severity, native, counts
    original = refs["c05-qld-official-v1.json" if state == "QLD" else "vic-restricted-inputs-v1.json"]
    severity = [{"code": d["severity_code"], "label": d["severity_label"],
                 "is_fatal_crash": d["is_fatal_crash"]} for d in original["severity"]]
    native = (original["mappings"][0]["content"]["native_severity_codes"] if state == "QLD"
              else {d["code"]: d["code"] for d in severity if d["code"] != "__MISSING__"})
    counts = {c["id"]: c["content"]["input"]["raw_count"] for c in original["contracts"]}
    return original, severity, native, counts


def _database(path):
    if path.exists():
        raise ValidationFailure("Attempt index already exists; retries require a new attempt directory.")
    db = sqlite3.connect(path)
    db.execute("PRAGMA cache_size=-8192")
    db.execute("PRAGMA temp_store=FILE")
    # This disposable index is rebuilt after interruption; never used as a
    # publication checkpoint or as the durable task database.
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("PRAGMA synchronous=OFF")
    db.executescript("""
        CREATE TABLE crash (
          id TEXT PRIMARY KEY, year INTEGER NOT NULL, month INTEGER, day TEXT,
          severity TEXT NOT NULL, fatal INTEGER, fatalities INTEGER, casualties INTEGER,
          declared_units INTEGER, declared_people INTEGER, node_id TEXT, locator TEXT NOT NULL);
        CREATE TABLE unit (crash_id TEXT, id TEXT, type TEXT, locator TEXT,
                           PRIMARY KEY(crash_id,id));
        CREATE TABLE person (crash_id TEXT,id TEXT,vehicle_id TEXT,road_user TEXT,seat TEXT,
                             injury TEXT,locator TEXT, PRIMARY KEY(crash_id,id));
        CREATE TABLE node (crash_id TEXT,node_id TEXT,latitude TEXT,longitude TEXT,locator TEXT);
        CREATE INDEX node_parent ON node(crash_id,node_id);
    """)
    return db


def _insert(db, table, values, locator):
    try:
        db.execute(f"INSERT INTO {table} VALUES ({','.join('?' for _ in values)})", values)
    except sqlite3.IntegrityError as exc:
        _block("Duplicate native primary key; records are not deduplicated or repaired.",
               "QA04_AUXILIARY", table=table, row_locator=locator)


def _crashes(db, selected, state, native, severity, progress, check_cancelled):
    flags = {d["code"]: d["is_fatal_crash"] for d in severity}
    count = 0
    for locator, row in iter_rows(selected["file"], selected["table"], check_cancelled):
        count += 1
        key_field = {"NSW": "Crash ID", "QLD": "Crash_Ref_Number", "VIC": "ACCIDENT_NO"}[state]
        key = _key(row[key_field], key_field, locator)
        day = None
        if state == "VIC":
            token = row["ACCIDENT_DATE"]
            try:
                if not isinstance(token, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", token):
                    raise ValueError()
                parsed = date.fromisoformat(token)
            except ValueError:
                _block("Invalid native occurrence date.", row_locator=locator)
            year, month, day = parsed.year, parsed.month, token
        else:
            year_field = "Year of crash" if state == "NSW" else "Crash_Year"
            token = row[year_field]
            if not isinstance(token, str) or not re.fullmatch(r"[0-9]{4}", token):
                _block("Invalid native occurrence year.", row_locator=locator)
            year = int(token)
            token = row["Month of crash" if state == "NSW" else "Crash_Month"]
            missing = token is None or (state != "NSW" and token == "")
            month = None if missing else MONTHS.get(token.strip())
            if not missing and month is None:
                _block("Unknown native month category.", row_locator=locator)
        if not MIN_YEAR <= year <= MAX_YEAR:
            _block("Occurrence year falls outside the supported source range.", row_locator=locator)
        field = {"NSW": "Degree of crash - detailed", "QLD": "Crash_Severity", "VIC": "SEVERITY"}[state]
        token = row[field]
        missing = token is None or (state != "NSW" and token == "")
        code = "__MISSING__" if missing else native.get(token)
        if code is None:
            _block("Unregistered native severity; no severity is guessed.", field=field, row_locator=locator)
        count_fields = ({"NSW": ["No. killed", "No. seriously injured", "No. moderately injured", "No. minor-other injured"],
                         "QLD": ["Count_Casualty_Fatality", "Count_Casualty_Hospitalised", "Count_Casualty_MedicallyTreated", "Count_Casualty_MinorInjury"],
                         "VIC": ["NO_PERSONS_KILLED", "NO_PERSONS_INJ_2", "NO_PERSONS_INJ_3"]}[state])
        counts = [_number(row[f], f, locator, empty=state != "NSW") for f in count_fields]
        casualties = _sum_known(counts)
        if state == "QLD":
            total = _number(row["Count_Casualty_Total"], "Count_Casualty_Total", locator)
            if total is None or casualties is None:
                casualties = None
            elif total != casualties:
                _block("QLD source casualty total differs from its four components.", row_locator=locator)
        declared_units = declared_people = node = None
        if state == "NSW":
            declared_units = _number(row["No. of traffic units involved"], "No. of traffic units involved", locator, empty=False, required=True)
        elif state == "VIC":
            declared_units = _number(row["NO_OF_VEHICLES"], "NO_OF_VEHICLES", locator, required=True)
            declared_people = _number(row["NO_PERSONS"], "NO_PERSONS", locator, required=True)
            node = _key(row["NODE_ID"], "NODE_ID", locator)
        _insert(db, "crash", (key, year, month, day, code, flags[code], counts[0], casualties,
                              declared_units, declared_people, node, locator), locator)
        if count % 25000 == 0:
            progress("processing", f"Validated {count:,} native {state} crash records.", rows=count, role="crash")
    db.commit()
    return count


def _children(db, selected, role, state, refs, progress, check_cancelled):
    count, categories = 0, Counter()
    allowed_nsw = set(refs["official-nsw-v1.json"]["contracts"][1]["semantics"]["unit_type_groups"])
    for locator, row in iter_rows(selected["file"], selected["table"], check_cancelled):
        count += 1
        parent = _key(row["Crash ID" if state == "NSW" else "ACCIDENT_NO"], "crash parent", locator)
        if role in {"traffic_unit", "vehicle"}:
            field = "Traffic unit ID" if state == "NSW" else "VEHICLE_ID"
            key = _key(row[field], field, locator)
            token = row["TU type group" if state == "NSW" else "VEHICLE_TYPE"]
            if state == "NSW" and token is not None and token not in allowed_nsw:
                _block("Unknown NSW traffic-unit category.", row_locator=locator)
            categories[token] += 1
            _insert(db, "unit", (parent, key, token, locator), locator)
        elif role == "person":
            key = _key(row["PERSON_ID"], "PERSON_ID", locator)
            if row["VEHICLE_ID"] != "":
                _key(row["VEHICLE_ID"], "VEHICLE_ID", locator)
            categories[row["ROAD_USER_TYPE"]] += 1
            _insert(db, "person", (parent, key, row["VEHICLE_ID"], row["ROAD_USER_TYPE"],
                                    row["SEATING_POSITION"], row["INJ_LEVEL"], locator), locator)
        else:
            node = _key(row["NODE_ID"], "NODE_ID", locator)
            # Node multiplicity is preserved. No unique constraint or coordinate
            # repair can silently turn these observations into a trusted map.
            _insert(db, "node", (parent, node, row["LATITUDE"], row["LONGITUDE"], locator), locator)
        if count % 50000 == 0:
            progress("processing", f"Validated {count:,} {state} {role} records.", rows=count, role=role)
    db.commit()
    return count, dict(categories)


def _count(db, sql, args=()):
    return db.execute(sql, args).fetchone()[0]


def _same_cases(actual, expected, label):
    if sorted(actual) != sorted(expected):
        _block("VIC observations differ from the exact reviewed case register.", "QA04_AUXILIARY",
               case_group=label, observed_count=len(actual), expected_count=len(expected))


def _relationships(db, state, refs, categories, check_cancelled):
    tables = ["unit"] if state == "NSW" else ["unit", "person", "node"] if state == "VIC" else []
    metrics = {}
    for table in tables:
        check_cancelled()
        orphan = _count(db, f"SELECT count(*) FROM {table} x LEFT JOIN crash c ON c.id=x.crash_id WHERE c.id IS NULL")
        if orphan:
            _block("A child record has no crash in the complete source file.", "QA04_AUXILIARY", table=table, orphan_count=orphan)
        metrics[f"{table}_orphans"] = orphan
    if state == "NSW":
        delta = _count(db, """SELECT count(*) FROM crash c LEFT JOIN
            (SELECT crash_id,count(*) n FROM unit GROUP BY crash_id) u ON u.crash_id=c.id
            WHERE c.declared_units <> COALESCE(u.n,0)""")
        if delta:
            _block("NSW declared traffic-unit count differs from real child rows.", "QA04_AUXILIARY", mismatch_count=delta)
        metrics["declared_unit_mismatches"] = 0
    if state != "VIC":
        return metrics
    policy = refs["vic-restricted-use-v1.json"]
    cases = policy["cases"]
    # Every exception is compared by its original key/date/locator and native
    # attributes, not accepted because a total happens to match.
    actual = list(db.execute("""SELECT p.crash_id,p.id,p.vehicle_id,c.day,p.locator,c.locator,p.road_user,p.injury,p.seat
        FROM person p JOIN crash c ON c.id=p.crash_id LEFT JOIN unit u
        ON u.crash_id=p.crash_id AND u.id=p.vehicle_id WHERE p.vehicle_id<>'' AND u.id IS NULL"""))
    expected = [(c["accident_no"], c["person_id"], c["vehicle_id"], c["occurrence_date"], c["person"]["row_locator"],
                 c["accident"]["row_locator"], c["native_person_fields"]["ROAD_USER_TYPE"],
                 c["native_person_fields"]["INJ_LEVEL"], c["native_person_fields"]["SEATING_POSITION"])
                for c in cases["unmatched_person_vehicle"]]
    _same_cases(actual, expected, "unmatched_person_vehicle")
    metrics["registered_unmatched_person_vehicle"] = len(actual)
    actual = list(db.execute("""SELECT p.crash_id,p.id,p.vehicle_id,c.day,p.locator,c.locator,p.road_user,p.injury,p.seat
        FROM person p JOIN crash c ON c.id=p.crash_id
        WHERE p.vehicle_id='' AND NOT (p.road_user='1' AND p.seat='NA')"""))
    expected = [(c["accident_no"], c["person_id"], c["vehicle_id"], c["occurrence_date"], c["person"]["row_locator"],
                 c["accident"]["row_locator"], c["native_person_fields"]["ROAD_USER_TYPE"],
                 c["native_person_fields"]["INJ_LEVEL"], c["native_person_fields"]["SEATING_POSITION"])
                for c in cases["unknown_role_blank_vehicle"]]
    _same_cases(actual, expected, "unknown_role_blank_vehicle")
    metrics["registered_unresolved_blank_vehicle"] = len(actual)
    pedestrian = db.execute("""SELECT count(*),sum(c.year BETWEEN 2020 AND 2024)
        FROM person p JOIN crash c ON c.id=p.crash_id
        WHERE p.vehicle_id='' AND p.road_user='1' AND p.seat='NA'""").fetchone()
    rule = policy["blank_vehicle_rules"]["pedestrian_nonassociation"]
    if pedestrian != (rule["expected_full_rows"], rule["expected_analysis_rows"]):
        _block("VIC pedestrian nonassociation membership differs.", "QA04_AUXILIARY")
    metrics["pedestrian_nonassociation"] = pedestrian[0]
    for entity, table, field in [("vehicle", "unit", "declared_units"), ("person", "person", "declared_people")]:
        check_cancelled()
        actual = list(db.execute(f"""SELECT c.id,c.day,c.{field},COALESCE(x.n,0),c.locator FROM crash c
            LEFT JOIN (SELECT crash_id,count(*) n FROM {table} GROUP BY crash_id) x ON x.crash_id=c.id
            WHERE c.{field}<>COALESCE(x.n,0)"""))
        expected = [(c["accident_no"],c["occurrence_date"],c["declared"],c["observed"],c["accident"]["row_locator"])
                    for c in cases["declared_count_differences"] if c["entity"] == entity]
        _same_cases(actual, expected, f"declared_{entity}_differences")
        metrics[f"registered_{entity}_count_differences"] = len(actual)
    actual = list(db.execute("""SELECT c.id,c.node_id,c.day,c.locator FROM crash c
        WHERE NOT EXISTS(SELECT 1 FROM node n WHERE n.crash_id=c.id AND n.node_id=c.node_id)"""))
    expected = [(c["accident_no"], c["node_id"], c["occurrence_date"], c["accident"]["row_locator"])
                for c in cases["missing_node_matches"]]
    _same_cases(actual, expected, "missing_node_matches")
    metrics["registered_missing_node_matches"] = len(actual)
    observed = policy["category_observations"]
    for role, name in [("vehicle", "vehicle_type_full_counts"), ("person", "person_road_user_full_counts")]:
        if categories[role] != observed[name]:
            _block("VIC native category membership differs from the frozen profile.", role=role)
    for table, field, token, expected_count in [("unit", "type", "21", 149), ("person", "road_user", "16", 129)]:
        n = _count(db, f"SELECT count(*) FROM {table} x JOIN crash c ON c.id=x.crash_id WHERE x.{field}=? AND c.year BETWEEN 2020 AND 2024", (token,))
        if n != expected_count:
            _block("VIC unresolved-category analysis membership differs from the reviewed profile.")
    metrics.update(undefined_category_rows=observed["undefined_category_rows"],
                   unresolved_definition_count=len(policy["unresolved_definitions"]),
                   case_set_sha256=policy["case_set_digest"]["sha256"], case_set_match=True,
                   person_vehicle_reporting=False, map_enabled=False)
    return metrics


def _write_line(stream, value):
    stream.write(_json(value) + "\n")


def _aggregate(db, group=""):
    prefix = (group + ",") if group else ""
    suffix = (" GROUP BY " + group + " ORDER BY " + group) if group else ""
    return db.execute(f"""SELECT {prefix}count(*),sum(fatal),sum(fatalities),sum(casualties),
        count(fatal),count(fatalities),count(casualties)
        FROM crash WHERE year BETWEEN 2020 AND 2024{suffix}""").fetchall()


def _metrics(row):
    return dict(zip(("crash_count", "fatal_crash_count", "fatalities", "casualties", "fatal_crash_known_count",
                     "fatality_known_count", "casualty_known_count"), row, strict=True))


def _export(db, work_dir, bundle, severity, check_cancelled):
    selected = bundle["files_by_role"]["crash"]
    source_id, state = bundle["source_id"], bundle["state"]
    canonical = work_dir / "canonical.jsonl"
    count = 0
    with canonical.open("x", encoding="utf-8") as stream:
        for row in db.execute("""SELECT id,year,month,day,severity,fatal,fatalities,casualties,locator
            FROM crash WHERE year BETWEEN 2020 AND 2024 ORDER BY id"""):
            identity, year, month, day, code, fatal, fatalities, casualties, locator = row
            _write_line(stream, {"record_id": identity, "source_id": source_id, "year": year, "month": month,
                "occurrence_date": day, "severity": code, "is_fatal_crash": None if fatal is None else bool(fatal),
                "fatalities": fatalities, "casualties": casualties, "resource_id": selected["spec"]["resource_id"],
                "row_locator": locator, "raw_file_sha256": selected["file"]["sha256"], "map_eligible": False,
                "latitude": None, "longitude": None,
                "location_reason": "crs_unconfirmed" if state == "NSW" else "definition_unconfirmed"})
            count += 1
            if count % 1000 == 0:
                check_cancelled()
    summary = _metrics(_aggregate(db)[0])
    if summary["crash_count"] != count:
        _block("Exported Canonical record count does not reconcile.", "QA06_RECONCILIATION")
    summary.update(year_from=2020, year_to=2024,
                   excluded_crash_count=_count(db, "SELECT count(*) FROM crash WHERE year NOT BETWEEN 2020 AND 2024"),
                   unit_count=None, source_id=source_id,
                   canonical_unit_count=_count(db, "SELECT count(*) FROM unit u JOIN crash c ON c.id=u.crash_id WHERE c.year BETWEEN 2020 AND 2024"))
    trend = [{"year": row[0], **_metrics(row[1:])} for row in _aggregate(db, "year")]
    monthly = [{"year": row[0], "month": row[1], **_metrics(row[2:])} for row in _aggregate(db, "year,month")]
    distribution = dict(db.execute("SELECT severity,count(*) FROM crash WHERE year BETWEEN 2020 AND 2024 GROUP BY severity"))
    distribution = [{**d, "count": distribution.get(d["code"], 0)} for d in severity]
    unit_path = None
    if state == "NSW":
        rows = [{"unit_type": t, "count": n} for t, n in db.execute("""SELECT u.type,count(*) FROM unit u
            JOIN crash c ON c.id=u.crash_id WHERE c.year BETWEEN 2020 AND 2024 AND u.type IS NOT NULL
            GROUP BY u.type ORDER BY u.type""")]
        summary["unit_count"] = sum(row["count"] for row in rows)
        units = {"status": "available", "scope": "NSW traffic units, including pedestrians; not motor vehicles.", "rows": rows}
    else:
        units = {"status": "unavailable", "rows": None, "scope": "This source only.",
                 "reason": "VIC restricted policy excludes vehicle and person reporting." if state == "VIC"
                 else "QLD input provides no unit-detail records; aggregate attributes do not create units."}
    if state in {"NSW", "VIC"}:
        unit_path = work_dir / "units.jsonl"
        unit_spec = bundle["files_by_role"]["traffic_unit" if state == "NSW" else "vehicle"]
        with unit_path.open("x", encoding="utf-8") as stream:
            for i, row in enumerate(db.execute("""SELECT u.crash_id,u.id,u.type,u.locator FROM unit u JOIN crash c ON c.id=u.crash_id
                WHERE c.year BETWEEN 2020 AND 2024 ORDER BY u.crash_id,u.id""")):
                _write_line(stream, {"record_id": _json([row[0], row[1]]), "source_id": source_id,
                                    "crash_id": row[0], "unit_id": row[1], "unit_type": row[2],
                                    "count_eligible": state == "NSW" and row[2] is not None,
                                    "quality_reason": "definition_unconfirmed" if state == "VIC" else None,
                                    "row_locator": row[3], "resource_id": unit_spec["spec"]["resource_id"],
                                    "raw_file_sha256": unit_spec["file"]["sha256"]})
                if i % 1000 == 0:
                    check_cancelled()
    return summary, trend, monthly, distribution, units, canonical, unit_path


def process_native(files, work_dir, options, progress, check_cancelled):
    """Execute a complete pinned state bundle, returning a local-test candidate."""
    bundle = identify_bundle(files)
    if bundle is None:
        raise NeedsInput("No reviewed native source profile matches these files.")
    state, source_id = bundle["state"], bundle["source_id"]
    hint = options.get("source_hint")
    if hint and hint.lower() not in {state.lower(), source_id, "auto", "automatic"}:
        raise NeedsInput("Selected source conflicts with the observed native table headers.")
    upstream, refs = _references()
    original, definitions, native_severity, expected_counts = _profile(state, refs)
    work_dir = Path(work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    selected = bundle["files_by_role"]
    verified = []
    progress("profiling", f"Recognized the complete {state} native bundle; checking original bytes and frozen source rules.")
    for file in files:
        check_cancelled()
        if Path(file["path"]).is_symlink() or not Path(file["path"]).is_file():
            _block("Uploaded input must be a regular file.", "QA01_INPUT")
        actual = _sha(file["path"], check_cancelled)
        if actual != file["sha256"] or Path(file["path"]).stat().st_size != file["size"]:
            _block("Uploaded bytes changed after registration.", "QA01_INPUT", file_id=file.get("id"))
        verified.append({"id": file.get("id"), "name": file["name"], "sha256": actual, "size": file["size"]})
    for role, item in selected.items():
        if item["file"]["sha256"] != item["spec"]["expected_sha256"]:
            raise NeedsInput(f"The {state} {role} file has new bytes and is not covered by the pinned profile.",
                             ["Provide source/version evidence and validate a new profile before importing this revision."],
                             {"source_id": source_id, "role": role, "profile_id": bundle["profile_id"],
                              "expected_sha256": item["spec"]["expected_sha256"], "actual_sha256": item["file"]["sha256"]})
        for entry in verified:
            if entry["id"] == item["file"].get("id"):
                entry.update(role=role, resource_id=item["spec"]["resource_id"], format=item["table"]["format"])
    semantic = {"profile_id": bundle["profile_id"], "profile_version": VERSION, "reader_version": READER_VERSION,
                "analysis": {"year_from": 2020, "year_to": 2024}, "source_rules": original,
                "restricted_policy": refs["vic-restricted-use-v1.json"] if state == "VIC" else None,
                "upstream": upstream, "no_interstate_pooling": True, "official_maps_enabled": False}
    hashes = [{"role": f.get("role", "supporting_evidence"), "sha256": f["sha256"]} for f in verified]
    implementation = {p.name: _sha(p) for p in (Path(__file__), Path(__file__).with_name("readers.py"))}
    fingerprint = hashlib.sha256(_json({"files": sorted(hashes, key=_json), "semantics": semantic,
                                      "implementation": implementation}).encode()).hexdigest()
    db = _database(work_dir / "native-index.sqlite")
    try:
        progress("processing", f"Reading all {state} native rows into a bounded on-disk relationship index.")
        raw_counts = {"crash": _crashes(db, selected["crash"], state, native_severity, definitions, progress, check_cancelled)}
        categories = {}
        for role in ROLES[state][1:]:
            raw_counts[role], categories[role] = _children(db, selected[role], role, state, refs, progress, check_cancelled)
        for role, count in raw_counts.items():
            wanted = expected_counts[selected[role]["spec"]["resource_id"]]
            if count != wanted:
                _block("Native parser row count differs from the frozen source contract.", "QA02_RAW", role=role, actual=count, expected=wanted)
        progress("validating", f"Checking {state} complete-file keys, relationships, declarations and source policy.")
        relationship_metrics = _relationships(db, state, refs, categories, check_cancelled)
        summary, trend, monthly, severity, units, canonical, unit_path = _export(db, work_dir, bundle, definitions, check_cancelled)
        summary["raw_record_count"] = sum(raw_counts.values())
        # Reconcile independently from the SQL grouping against the completed
        # deterministic export, preserving unknown values rather than filling.
        observed = {"crash_count": 0, "fatal_crash_count": 0, "fatalities": 0, "casualties": 0}
        known = {"fatal_crash_count": 0, "fatalities": 0, "casualties": 0}
        with canonical.open(encoding="utf-8") as stream:
            for i, line in enumerate(stream):
                row = json.loads(line)
                observed["crash_count"] += 1
                for metric, field in [("fatal_crash_count", "is_fatal_crash"), ("fatalities", "fatalities"), ("casualties", "casualties")]:
                    if row[field] is not None:
                        observed[metric] += int(row[field])
                        known[metric] += 1
                if i % 1000 == 0:
                    check_cancelled()
        for metric, count in known.items():
            if not count:
                observed[metric] = None
        if any(summary[k] != v for k, v in observed.items()):
            _block("Canonical JSONL aggregates do not reconcile with source-derived measures.", "QA06_RECONCILIATION")
        for file in files:
            if _sha(file["path"], check_cancelled) != file["sha256"]:
                _block("Source bytes changed during execution.", "QA01_INPUT", file_id=file.get("id"))
        qa = [
            {"code": "QA01_INPUT", "status": "pass", "message": "Exact native hashes, complete role set and frozen source-rule references verified.", "metrics": {"files": len(selected), "supplements": len(bundle["supplements"])}},
            {"code": "QA02_RAW", "status": "pass", "message": "Full native counts reconciled; original upload bytes remain unchanged.", "metrics": raw_counts},
            {"code": "QA03_PROJECTED", "status": "pass", "message": "Unique crash keys and occurrence-year filtering checked before export.", "metrics": {"analysis_crashes": summary["crash_count"], "excluded_crashes": summary["excluded_crash_count"]}},
            {"code": "QA04_AUXILIARY", "status": "pass", "message": "Complete-file relationships and declarations validated against the source-specific policy.", "metrics": relationship_metrics},
            {"code": "QA05_SEMANTICS", "status": "pass", "message": "Source severity, count semantics and reporting restrictions preserved; no inferred categories or repaired keys."},
            {"code": "QA06_RECONCILIATION", "status": "pass", "message": "Exported records independently reconcile to source-derived aggregate results.", "metrics": observed},
            {"code": "QA07_LOCATION", "status": "limited", "message": "Official maps remain unavailable under the source policy; no coordinates were inferred.", "metrics": {"crash_count": summary["crash_count"], "mapped_count": 0, "unmapped_count": summary["crash_count"]}},
        ]
        limitations = ["LOCAL TEST publication only; this adapter does not execute the course PostgreSQL Vault/DW pipeline or E FP1.",
                       "Pinned 2020–2024 source snapshot; not current official totals or complete population coverage.",
                       "Source definitions differ; interstate totals and harmonized severity metrics are unsupported.",
                       "Official maps are unavailable; raw source evidence is retained without guessing coordinates."]
        if state == "VIC":
            limitations.extend(["Restricted VIC Accident metrics only. Full-source and publisher bundle confirmation remain false.",
                                "Person/Vehicle/Node files support exact relationship checks; their export totals and category analyses are unavailable."])
        if state == "QLD":
            limitations.append("Hospitalisation means taken to hospital, not proven admission or an interstate serious-injury category.")
        evidence = {"execution_kind": "local_sqlite_adapter", "upstream": upstream, "profile_id": bundle["profile_id"],
                    "profile_version": VERSION, "rule_fingerprint": fingerprint, "implementation": implementation,
                    "raw_counts": raw_counts, "relationship_checks": relationship_metrics,
                    "canonical_sha256": _sha(canonical), "canonical_records": summary["crash_count"],
                    "raw_rows_are_not_all_crashes": True, "files": verified,
                    "source_contract_confirmed": state != "VIC", "qa": qa, "limitations": limitations}
        for name, value in [("native-manifest.json", {"semantics": semantic, "files": verified, "fingerprint": fingerprint}),
                            ("native-evidence.json", evidence)]:
            with (work_dir / name).open("x", encoding="utf-8") as stream:
                stream.write(_json(value) + "\n")
        result = {"source_id": source_id, "profile_id": bundle["profile_id"], "profile_version": VERSION,
                  "fingerprint": fingerprint, "summary": summary, "trend": trend, "monthly_trend": monthly,
                  "severity": severity, "units": units, "limitations": limitations, "qa": qa,
                  "files": verified, "evidence": evidence, "canonical_path": str(canonical)}
        if unit_path is not None:
            result["units_path"] = str(unit_path)
        return result
    finally:
        db.close()
