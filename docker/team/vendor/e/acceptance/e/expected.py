"""Small independent oracle from document 04's hand-calculated rows."""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path


def load_expected(root=None):
    if root is None:
        here = Path(__file__).resolve()
        root = here.parents[2] if here.parent.name == "e" else here.parents[1]
    return json.loads((Path(root) / "config/e-acceptance-s0-v1.json").read_text(encoding="utf-8"))


def crashes(variant="s0"):
    oracle = load_expected()
    rows = deepcopy(oracle["crashes"])
    if variant == "revised_n1":
        rows[0].update(fatalities=3, casualties=4)
    elif variant == "delete_q2":
        rows = [row for row in rows if row["alias"] != "Q2"]
    elif variant == "known_n2":
        rows[1].update(fatal=False, severity="N")
    elif variant == "s8":
        rows.append(deepcopy(oracle["s8_crash"]))
    elif variant != "s0":
        raise ValueError("Unknown expectation variant: " + variant)
    return rows


def metrics(rows):
    rows = list(rows)
    known = {key: [r[key] for r in rows if r[key] is not None]
             for key in ("fatal", "fatalities", "casualties")}
    return {
        "crash_count": len(rows),
        "month_known_count": sum(r["month"] is not None for r in rows),
        "fatal_crash_count": sum(known["fatal"]) if known["fatal"] else None,
        "fatal_crash_known_count": len(known["fatal"]),
        "fatality_count": sum(known["fatalities"]) if known["fatalities"] else None,
        "fatality_known_count": len(known["fatalities"]),
        "casualty_count": sum(known["casualties"]) if known["casualties"] else None,
        "casualty_known_count": len(known["casualties"]),
    }


def trends(variant="s0", *, grain="year", sources=None, year_from=2020, year_to=2024):
    rows = crashes(variant)
    sources = sources or sorted({r["source_id"] for r in rows})
    result = {}
    for source in sources:
        for year in range(year_from, year_to + 1):
            yearly = [r for r in rows if r["source_id"] == source and r["year"] == year]
            for month in range(1, 13) if grain == "month" else (None,):
                selected = yearly if month is None else [r for r in yearly if r["month"] == month]
                result[source, year, month] = {
                    **metrics(selected), "coverage_status": "covered",
                    "requested_month_count": 12 if month is None else 1,
                    "covered_month_count": 12 if month is None else 1,
                    "excluded_unknown_month_count": 0 if month is None else sum(r["month"] is None for r in yearly),
                }
    return result


def map_coverage(rows):
    rows = list(rows)
    points = sum(r["latitude"] is not None for r in rows)
    return {"crash_count": len(rows), "point_count": points,
            "coverage_percentage": None if not rows else
                (Decimal(points) * 100 / len(rows)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)}


def qa_objects(files, variant="s0"):
    """Only file identities come from the run; required kinds and years do not."""
    resources = load_expected()["resources"].copy()
    if variant == "s8":
        resources["syn_sa_crash"] = {"kind": "crash", "rows": 1}
    assert {f["resource_id"] for f in files} == set(resources)
    assert len(files) == len(resources)
    file_keys = {f"file:{f['resource_id']}:{f['file_sha256']}:{f['parser_version']}" for f in files}
    sources = {r["source_id"] for r in crashes(variant)}
    source_years = {f"source_year:{source}:{year}" for source in sources for year in range(2020, 2025)}
    return {
        "QA01_INPUT": file_keys | {"batch"}, "QA02_RAW": file_keys | {"batch"},
        "QA03_PROJECTED": {"resource:" + key for key, r in resources.items() if r["kind"] in {"crash", "unit"}} | {"batch"},
        "QA04_AUXILIARY": {"resource:" + key for key, r in resources.items() if r["kind"] in {"unit", "person", "node"}} | {"batch"},
        "QA05_SEMANTICS": {"source:" + source for source in sources} | {"batch"},
        "QA06_RECONCILIATION": source_years | {"batch"},
        "QA07_LOCATION": source_years | {"batch"},
    }
