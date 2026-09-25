"""Frozen inputs for C04/C05. No transaction, FP1, or publication ownership."""

import hashlib
import json
from importlib.resources import files

MONTHS = dict(
    zip(
        (
            "January February March April May June July August September October November December"
        ).split(),
        range(1, 13),
    )
)
VIC_COUNTS = ["NO_PERSONS_KILLED", "NO_PERSONS_INJ_2", "NO_PERSONS_INJ_3"]
QLD_COUNTS = [
    "Count_Casualty_Fatality",
    "Count_Casualty_Hospitalised",
    "Count_Casualty_MedicallyTreated",
    "Count_Casualty_MinorInjury",
]


def read_pinned(path, digest):
    data = files("arsia_c").joinpath(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"Changed frozen source definition: {path}")
    return json.loads(data)


def vic_definitions():
    values = read_pinned(
        "config/vic-restricted-inputs-v1.json",
        "7eaf1e4834c6dcdb8c74e933aaff602dcaad0094e72f5508fe64ab3a34b583a3",
    )
    policy = read_pinned(
        "config/vic-restricted-use-v1.json",
        "bc892d07f81f51fc2859cccd9c1302e4b1ade22240bd36f8fe118d95e861ec40",
    )
    values["mappings"] = [
        {
            "id": "official_vic_restricted_use",
            "version": policy["profile_id"],
            "content": policy,
        }
    ]
    return values


def qld_definitions():
    """Confirmed project rules for the pinned no-map snapshot, not build acceptance."""
    return read_pinned(
        "config/c05-qld-official-v1.json",
        "40c0535ae002e57bd3a072ce90415c9ca619a801d3063db1ab524d8684fddeb4",
    )


def _one(items, label):
    if len(items) != 1:
        raise ValueError(f"Expected exactly one {label}, got {len(items)}")
    return items[0]


def parameters(manifest, batch_id, state):
    if state not in ("VIC", "QLD"):
        raise ValueError("Unsupported source projection")
    kind = manifest["dataset_kind"]
    if kind not in ("synthetic", "official"):
        raise ValueError("Explicit dataset_kind required")
    years = manifest["analysis"]
    lo, hi = years["year_from"], years["year_to"]
    if type(lo) is not int or type(hi) is not int or not 1 <= lo <= hi <= 9999:
        raise ValueError("Invalid analysis calendar-year interval")
    source = _one(
        [s for s in manifest["sources"] if s["jurisdiction_code"] == state],
        state + " source",
    )
    sid = source["source_id"]
    prefix = "syn_" if kind == "synthetic" else "official_"
    if not sid.startswith(prefix) or not source.get("release_scope"):
        raise ValueError("Source namespace/release mismatch")
    files = [f for f in manifest["files"] if f["source_id"] == sid]
    roles = (
        {"crash": "crash"}
        if state == "QLD"
        else {
            "crash": "crash",
            "vehicle": "unit",
            "person": "person_raw",
            "node": "node_raw",
        }
    )
    if len(files) != len(roles) or len({f["resource_id"] for f in files}) != len(files):
        raise ValueError("Unexpected or duplicate selected resources")
    if set(source["resource_ids"]) != {f["resource_id"] for f in files}:
        raise ValueError("Source resource inventory mismatch")
    selected = {}
    contracts = {}
    mappings = {}
    for role, entity in roles.items():
        f = _one(
            [
                f
                for f in files
                if f["resource_role"] == role and f["entity_kind"] == entity
            ],
            role,
        )
        c = _one(
            [c for c in manifest["rules"]["contracts"] if c["id"] == f["resource_id"]],
            role + " contract",
        )
        status = (
            "synthetic_defined"
            if kind == "synthetic"
            else ("restricted" if state == "VIC" else "confirmed")
        )
        if c["status"] != status or not c.get("version"):
            raise ValueError("Draft or unsupported source contract")
        if (
            c["content"]["input"] != f
            or c["content"]["identity"]["release_scope"] != source["release_scope"]
        ):
            raise ValueError("Contract input/release mismatch")
        if (
            not f["resource_id"].startswith(prefix)
            or type(f["raw_count"]) is not int
            or f["raw_count"] < 0
        ):
            raise ValueError("Invalid resource namespace/Raw count")
        if len(c["mapping_ids"]) != 1:
            raise ValueError("Exactly one supported mapping is required")
        m = _one(
            [
                m
                for m in manifest["rules"]["mappings"]
                if m["id"] == c["mapping_ids"][0]
            ],
            role + " mapping",
        )
        if not m.get("version"):
            raise ValueError("Missing mapping version")
        selected[role] = f
        contracts[role] = c
        mappings[role] = m
    ci = contracts["crash"]["content"]["identity"]
    key = "ACCIDENT_NO" if state == "VIC" else "Crash_Ref_Number"
    if ci["key"]["fields"] != [key] or ci["parent"] is not None:
        raise ValueError("Unsupported crash identity")
    if kind == "official":
        expected = vic_definitions() if state == "VIC" else qld_definitions()
        for name, actual in [
            ("sources", [source]),
            ("contracts", list(contracts.values())),
            ("mappings", list({m["id"]: m for m in mappings.values()}.values())),
            (
                "severity",
                [s for s in manifest["rules"]["severity"] if s["source_id"] == sid],
            ),
        ]:
            order = lambda v: json.dumps(v, sort_keys=True)
            if sorted(actual, key=order) != sorted(expected[name], key=order):
                raise ValueError(f"Official {state} {name} differ from frozen version")
        if years != expected["analysis"]:
            raise ValueError("Official analysis scope differs from frozen version")
        if (
            state == "VIC"
            and manifest["rules"]["qa_contract"]["version"] != "team-v1.1-vic-r1"
        ):
            raise ValueError("Restricted VIC needs its exact QA protocol")
    cm = mappings["crash"]["content"]
    official_vic = kind == "official" and state == "VIC"
    if not official_vic:
        required = {
            "fatality_count": (VIC_COUNTS if state == "VIC" else QLD_COUNTS)[0],
            "casualty_components": VIC_COUNTS if state == "VIC" else QLD_COUNTS,
            "severity_raw": "SEVERITY" if state == "VIC" else "Crash_Severity",
        }
        if state == "VIC":
            required["occurrence_date"] = "ACCIDENT_DATE"
        else:
            required.update(
                occurrence_year="Crash_Year",
                occurrence_month="Crash_Month",
                casualty_count="Count_Casualty_Total",
            )
        if any(cm.get(k) != v for k, v in required.items()):
            raise ValueError("Unsupported field mapping operation")
    version = contracts["crash"]["content"]["semantics"]["severity_definition_version"]
    defs = [d for d in manifest["rules"]["severity"] if d["source_id"] == sid]
    codes = {d["severity_code"]: d for d in defs}
    if (
        len(codes) != len(defs)
        or "__MISSING__" not in codes
        or codes["__MISSING__"]["is_fatal_crash"] is not None
        or any(d["definition_version"] != version for d in defs)
        or any(
            type(d["is_fatal_crash"]) is not bool
            for k, d in codes.items()
            if k != "__MISSING__"
        )
    ):
        raise ValueError("Incomplete/inconsistent severity definitions")
    if official_vic:
        native = {k: k for k in codes if k != "__MISSING__"}
    elif kind == "official":
        native = cm["native_severity_codes"]
    else:
        if cm.get("severity_code", {}).get("mapping") != version:
            raise ValueError("Synthetic severity mapping differs from definitions")
        native = {k: k for k in codes if k != "__MISSING__"}
    if not native or any(k not in codes for k in native.values()):
        raise ValueError("Invalid native severity mapping")
    loc = cm.get("location", {}) if not official_vic else {}
    map_enabled = kind == "synthetic" and loc.get("crs") == "EPSG:4326"
    if state == "VIC" and kind == "synthetic":
        node_loc = mappings["node"]["content"].get("location", {})
        if (
            node_loc.get("latitude") != "LATITUDE"
            or node_loc.get("longitude") != "LONGITUDE"
            or node_loc.get("crs") != loc.get("crs")
            or not node_loc.get("basis")
        ):
            raise ValueError("VIC Node location declaration mismatch")
    if kind == "synthetic":
        if loc.get("crs") not in (None, "EPSG:4326") or (
            map_enabled and not loc.get("basis")
        ):
            raise ValueError("Unsupported or unevidenced synthetic CRS")
        expected_loc = (
            {
                "resource_id": selected["node"]["resource_id"],
                "fields": ["ACCIDENT_NO", "NODE_ID"],
            }
            if state == "VIC"
            else {"latitude": "Crash_Latitude", "longitude": "Crash_Longitude"}
        )
        if any(loc.get(k) != v for k, v in expected_loc.items()):
            raise ValueError("Unsupported location mapping")
    p = {
        "state": state,
        "dataset_kind": kind,
        "batch_id": batch_id,
        "source_id": sid,
        "release_scope": source["release_scope"],
        "year_from": lo,
        "year_to": hi,
        "severity_version": version,
        "severity_map": json.dumps(
            {
                k: {"code": v, "fatal": codes[v]["is_fatal_crash"]}
                for k, v in native.items()
            }
        ),
        "contract_version": contracts["crash"]["version"],
        "map_enabled": map_enabled,
        "location_evidence": loc.get(
            "basis", mappings["crash"]["id"] + ":" + mappings["crash"]["version"]
        ),
        "selected": selected,
        "key_field": key,
        "severity_field": "SEVERITY" if state == "VIC" else "Crash_Severity",
        "count_fields": (
            VIC_COUNTS if state == "VIC" else QLD_COUNTS + ["Count_Casualty_Total"]
        ),
        "month_map": json.dumps(MONTHS),
        "official_vic": official_vic,
    }
    if state == "VIC":
        for role, fields in [
            ("vehicle", ["ACCIDENT_NO", "VEHICLE_ID"]),
            ("person", ["ACCIDENT_NO", "PERSON_ID"]),
            ("node", ["ACCIDENT_NO", "NODE_ID"]),
        ]:
            ident = contracts[role]["content"]["identity"]
            parent = ident.get("parent")
            if (
                ident["key"]["fields"] != fields
                or not parent
                or parent["resource_id"] != selected["crash"]["resource_id"]
                or parent["fields"] not in (["ACCIDENT_NO"], ["ACCIDENT_NO", "NODE_ID"])
            ):
                raise ValueError("Unsupported VIC child identity/parent")
        if official_vic:
            policy = cm
            types = {
                k: k
                for k in policy["category_observations"]["vehicle_type_full_counts"]
            }
            scope = (
                "VIC native Vehicle export; audit-only under "
                + mappings["vehicle"]["version"]
            )
        else:
            um = mappings["vehicle"]["content"]
            types = um.get("unit_types")
            scope = um.get("statistical_scope")
            if um.get("unit_type_raw") != "VEHICLE_TYPE":
                raise ValueError("Unsupported vehicle field mapping")
        if (
            not isinstance(types, dict)
            or not types
            or any(
                not isinstance(k, str)
                or not k.strip()
                or not isinstance(v, str)
                or not v.strip()
                for k, v in types.items()
            )
            or not scope
        ):
            raise ValueError("Missing frozen unit type/scope mapping")
        p.update(
            unit_types=json.dumps(types),
            statistical_scope=scope,
            unit_contract_version=contracts["vehicle"]["version"],
        )
    return p


def sql(name):
    return files("arsia_c").joinpath("sql", name).read_text(encoding="utf-8")


def check(cursor, query, params, label):
    cursor.execute(query, params)
    row = cursor.fetchone()
    if row is None or any(row):
        raise ValueError(f"{label} validation failed: {row}")


def stage(connection, p):
    """Full selected input validation precedes analytical-year filtering."""
    if connection.autocommit is not False:
        raise ValueError("Projection requires B caller-owned transaction")
    with connection.cursor() as cur:
        for role, f in p["selected"].items():
            cur.execute(
                "SELECT source_id,resource_role,entity_kind FROM meta.resource WHERE resource_id=%s",
                (f["resource_id"],),
            )
            if cur.fetchone() != (p["source_id"], f["resource_role"], f["entity_kind"]):
                raise ValueError("Resource registration mismatch")
            identity = (
                p["source_id"],
                f["resource_id"],
                f["file_sha256"],
                f["parser_version"],
            )
            cur.execute(
                "SELECT count(*) FROM raw.record WHERE source_id=%s AND resource_id=%s AND file_sha256=%s AND parser_version=%s",
                identity,
            )
            if cur.fetchone()[0] != f["raw_count"]:
                raise ValueError("Incomplete selected Raw: " + role)
            if role == "person":
                continue  # Full Person semantics remain C06 responsibility.
            # Names come only from the closed role list above, never native data.
            cur.execute(f"DROP TABLE IF EXISTS pg_temp.c45_{role}")
            cur.execute(
                f"CREATE TEMP TABLE c45_{role} ON COMMIT DROP AS SELECT raw_record_id,payload,row_locator,file_sha256,parser_version FROM raw.record WHERE source_id=%s AND resource_id=%s AND file_sha256=%s AND parser_version=%s",
                identity,
            )
            check(
                cur,
                f"SELECT count(*) FROM pg_temp.c45_{role} r WHERE NOT payload ?& %s::text[] OR EXISTS(SELECT 1 FROM jsonb_each(payload) e WHERE jsonb_typeof(e.value) NOT IN ('string','null'))",
                (f["header"],),
                "Raw native fields/types",
            )
        cur.execute(
            "ALTER TABLE pg_temp.c45_crash ADD COLUMN native_key text, ADD COLUMN crash_key text"
        )
        cur.execute(
            "UPDATE pg_temp.c45_crash SET native_key=payload->>%s, crash_key=rv.encode_business_key(payload->>%s)",
            (p["key_field"], p["key_field"]),
        )
        check(
            cur,
            "SELECT count(*)-count(DISTINCT crash_key) FROM pg_temp.c45_crash",
            None,
            "Duplicate crash keys",
        )
        cur.execute("CREATE UNIQUE INDEX ON pg_temp.c45_crash(native_key)")
        cur.execute(
            sql("c45_crash_check.sql"),
            {**p, "count_fields": json.dumps(p["count_fields"])},
        )
        row = cur.fetchone()
        if row is None or any(row):
            raise ValueError(f"Crash dates/categories/counts validation failed: {row}")
        cur.execute(sql("c03_projection_tables.sql"))


def clear_projection(cursor, p):
    for kind in ("unit", "crash"):
        cursor.execute(
            f"DELETE FROM pg_temp.arsia_i_{kind} WHERE batch_id=%s AND source_id=%s AND release_scope=%s",
            (p["batch_id"], p["source_id"], p["release_scope"]),
        )
