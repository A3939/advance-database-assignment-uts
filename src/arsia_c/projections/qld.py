"""C05: manifest-selected QLD Raw -> typed crash projection; never invent units."""

from .source_contracts import parameters, stage, sql, check, clear_projection


def project(connection, context):
    p = parameters(context.manifest.as_dict(), context.batch_id, "QLD")
    if getattr(context, "dataset_kind", p["dataset_kind"]) != p["dataset_kind"]:
        raise ValueError("Context/manifest dataset_kind mismatch")
    stage(connection, p)
    with connection.cursor() as cur:
        check(cur, sql("c05_qld_reconciliation.sql"), None, "QLD casualty components")
        cur.execute("DROP TABLE IF EXISTS pg_temp.c45_values")
        cur.execute(sql("c05_qld_values.sql"), p)
        clear_projection(cur, p)
        cur.execute(
            sql("c45_crash_insert.sql"),
            {**p, "fatality_field": "Count_Casualty_Fatality"},
        )
        count = cur.rowcount
    context.evidence.write_json(
        "c05-qld-projection-counts.json",
        {
            "source_id": p["source_id"],
            "raw_crash_count": p["selected"]["crash"]["raw_count"],
            "crash_count": count,
            "excluded_crash_count": p["selected"]["crash"]["raw_count"] - count,
            "unit_count": 0,
            "official_map_enabled": False,
            "scope": "projection component; no publication or persisted QA claim",
        },
    )
