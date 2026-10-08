"""Read-only aggregate checks for the CURRENT isolated local release.

Run after full-volume imports: `.venv/bin/python tools/verify_database.py --require-official`.
No original, crash, vehicle or person records are printed. No writes are performed.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arsia_pipeline import store
from arsia_pipeline.reconcile import verify_candidate

EXPECTED = {"official_nsw": (170747, 170747), "official_vic": (132372, 0), "official_qld": (0, 0)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-official", action="store_true")
    args = parser.parse_args()
    reports = []
    with store.connect() as conn:
        conn.execute("SET default_transaction_read_only=on")
        current = conn.execute("SELECT r.id,r.sources FROM current_release c JOIN releases r ON r.id=c.release_id").fetchone()
        if not current:
            raise RuntimeError("No current LOCAL TEST publication")
        if args.require_official and not set(EXPECTED) <= set(current["sources"]):
            raise RuntimeError("The current local release does not yet contain all three official sources")
        for source, batch in sorted(current["sources"].items()):
            result = conn.execute("SELECT result FROM batches WHERE id=%s", (batch,)).fetchone()["result"]
            metrics = verify_candidate(conn, batch, result)
            if source in EXPECTED:
                actual = (metrics["canonical_unit_count"], metrics["eligible_unit_count"])
                if actual != EXPECTED[source]:
                    raise RuntimeError(f"Pinned native {source} unit totals differ from the independently specified expectation")
                if source != "official_nsw" and (result["summary"]["unit_count"] is not None or result["units"]["status"] != "unavailable"):
                    raise RuntimeError("Restricted/unavailable unit reporting was incorrectly enabled")
            reports.append({"source_id": source, "batch_id": batch, **metrics,
                            "reported_unit_count": result["summary"].get("unit_count"),
                            "unit_report_status": result["units"]["status"]})
    print(json.dumps({"mode": "local-test", "status": "passed", "read_only": True,
                      "release_id": str(current["id"]), "sources": reports}, indent=2))


if __name__ == "__main__":
    main()
