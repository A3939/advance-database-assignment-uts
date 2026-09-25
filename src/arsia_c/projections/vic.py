"""C04 with C07 assembly: complete selected VIC projections in B's transaction."""

import json
from .source_contracts import (
    parameters,
    stage,
    sql,
    check,
    clear_projection,
    vic_definitions,
)
from arsia_c.node_location import iter_node_observation_groups, resolve_location_update


def _assemble_locations(connection, p):
    # The accident lookup is bounded by selected analysis rows. All Node groups
    # are streamed; no first-row SQL selection, rounding or geographic inference.
    with connection.cursor() as cur:
        cur.execute(
            "SELECT c.native_key,c.payload->>'NODE_ID',i.crash_key,i.quality_notes FROM pg_temp.c45_crash c JOIN pg_temp.arsia_i_crash i ON i.raw_record_id=c.raw_record_id WHERE i.batch_id=%s AND i.source_id=%s AND i.release_scope=%s",
            (p["batch_id"], p["source_id"], p["release_scope"]),
        )
        targets = {}
        while rows := cur.fetchmany(1000):
            for accident, node, key, notes in rows:
                targets[(accident, node)] = (key, notes)
    with connection.cursor() as cur:
        cur.execute(
            "CREATE INDEX IF NOT EXISTS c45_i_crash_lookup ON pg_temp.arsia_i_crash (batch_id,source_id,release_scope,crash_key)"
        )
    updates = []
    counts = {"mapped": 0, "unmapped": 0}
    statement = "UPDATE pg_temp.arsia_i_crash SET latitude=%s,longitude=%s,location_crs=%s,map_eligible=%s,location_record_id=%s,quality_notes=%s::jsonb WHERE batch_id=%s AND source_id=%s AND release_scope=%s AND crash_key=%s"

    def append(key, notes, accident, node, observations):
        update = resolve_location_update(
            observations,
            expected_accident_no=accident,
            expected_node_id=node,
            crs_confirmed=p["map_enabled"],
            existing_quality_notes=notes,
            evidence_ref=p["location_evidence"],
        )
        counts["mapped" if update["map_eligible"] else "unmapped"] += 1
        updates.append(
            (
                update["latitude"],
                update["longitude"],
                update["location_crs"],
                update["map_eligible"],
                update["location_record_id"],
                json.dumps(update["quality_notes"]),
                p["batch_id"],
                p["source_id"],
                p["release_scope"],
                key,
            )
        )

    def flush():
        if updates:
            with connection.cursor() as cur:
                cur.executemany(statement, updates)
            updates.clear()

    for (accident, node), observations in iter_node_observation_groups(
        connection, p["selected"]["node"]
    ):
        target = targets.pop((accident, node), None)
        if target:
            append(*target, accident, node, observations)
            if len(updates) >= 1000:
                flush()
    for (accident, node), (key, notes) in targets.items():
        append(key, notes, accident, node, [])
        if len(updates) >= 1000:
            flush()
    flush()
    return counts


def _official_cases(connection):
    """No count-only tolerance: exact pinned accident IDs and native locators."""
    policy = vic_definitions()["mappings"][0]["content"]
    with connection.cursor() as cur:
        cur.execute(
            """WITH detail AS (
          SELECT payload->>'ACCIDENT_NO' AS key, count(*) AS n,
                 array_agg(row_locator ORDER BY row_locator) AS refs
          FROM pg_temp.c45_vehicle GROUP BY 1)
          SELECT c.native_key,c.payload->>'ACCIDENT_DATE',c.row_locator,
                 (c.payload->>'NO_OF_VEHICLES')::integer,coalesce(v.n,0),coalesce(v.refs,ARRAY[]::text[])
          FROM pg_temp.c45_crash c LEFT JOIN detail v ON v.key=c.native_key
          WHERE (c.payload->>'NO_OF_VEHICLES')::integer IS DISTINCT FROM coalesce(v.n,0)"""
        )
        actual = sorted(
            (key, date, locator, declared, observed, sorted(refs))
            for key, date, locator, declared, observed, refs in cur.fetchall()
        )
        expected = sorted(
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
        if actual != expected:
            raise ValueError("VIC exact declared vehicle case set differs")
        cur.execute(
            """SELECT c.native_key,c.payload->>'NODE_ID',c.payload->>'ACCIDENT_DATE',c.row_locator
          FROM pg_temp.c45_crash c WHERE NOT EXISTS (SELECT 1 FROM pg_temp.c45_node n
          WHERE n.payload->>'ACCIDENT_NO'=c.native_key AND n.payload->>'NODE_ID'=c.payload->>'NODE_ID')"""
        )
        expected = sorted(
            (
                r["accident_no"],
                r["node_id"],
                r["occurrence_date"],
                r["accident"]["row_locator"],
            )
            for r in policy["cases"]["missing_node_matches"]
        )
        if sorted(cur.fetchall()) != expected:
            raise ValueError("VIC exact missing Node case set differs")
        cur.execute(
            "SELECT payload->>'VEHICLE_TYPE',count(*) FROM pg_temp.c45_vehicle GROUP BY 1"
        )
        if (
            dict(cur.fetchall())
            != policy["category_observations"]["vehicle_type_full_counts"]
        ):
            raise ValueError("VIC pinned vehicle category counts differ")


def project(connection, context):
    p = parameters(context.manifest.as_dict(), context.batch_id, "VIC")
    if getattr(context, "dataset_kind", p["dataset_kind"]) != p["dataset_kind"]:
        raise ValueError("Context/manifest dataset_kind mismatch")
    stage(connection, p)
    with connection.cursor() as cur:
        check(
            cur,
            sql("c04_vic_staged_relationship_check.sql"),
            None,
            "VIC full-input relationships",
        )
        check(cur, sql("c04_vic_semantic_check.sql"), p, "VIC vehicle semantics")
        cur.execute("CREATE INDEX ON pg_temp.c45_vehicle ((payload->>'ACCIDENT_NO'))")
        cur.execute(
            "CREATE INDEX ON pg_temp.c45_node ((payload->>'ACCIDENT_NO'),(payload->>'NODE_ID'))"
        )
        # Synthetic counts have declared common scope; official differences stay
        # unchanged and are checked against exact case membership by C06/C10.
        if not p["official_vic"]:
            check(
                cur,
                "SELECT count(*) FROM pg_temp.c45_crash c WHERE NULLIF(c.payload->>'NO_OF_VEHICLES','')::integer <> (SELECT count(*) FROM pg_temp.c45_vehicle v WHERE v.payload->>'ACCIDENT_NO'=c.native_key)",
                None,
                "VIC declared vehicle counts",
            )
        cur.execute("DROP TABLE IF EXISTS pg_temp.c45_values")
        cur.execute(sql("c04_vic_crash_base_insert.sql"))
        clear_projection(cur, p)
        cur.execute(
            sql("c45_crash_insert.sql"), {**p, "fatality_field": "NO_PERSONS_KILLED"}
        )
        crashes = cur.rowcount
        cur.execute(sql("c04_vic_unit_insert.sql"), p)
        units = cur.rowcount
    if p["official_vic"]:
        _official_cases(connection)
    locations = _assemble_locations(connection, p)
    if locations["mapped"] + locations["unmapped"] != crashes:
        raise ValueError("VIC location assembly count mismatch")
    context.evidence.write_json(
        "c04-vic-projection-counts.json",
        {
            "source_id": p["source_id"],
            "raw_crash_count": p["selected"]["crash"]["raw_count"],
            "crash_count": crashes,
            "unit_count": units,
            "excluded_crash_count": p["selected"]["crash"]["raw_count"] - crashes,
            "excluded_unit_count": p["selected"]["vehicle"]["raw_count"] - units,
            **locations,
            "c07_assembled": True,
            "scope": "projection component; C06/C10 exact-case QA and E publication remain separate",
        },
    )
