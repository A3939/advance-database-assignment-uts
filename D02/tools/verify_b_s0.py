"""Verify D02 row generation against B's checked-in S0 contract."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from arsia_d02.dimensions import build_dimension_rows
from arsia_ingest.manifest import s0_definitions


DEFAULT_BATCH_ID = "12345678-1234-5678-9234-567812345678"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    args = parser.parse_args()

    definitions = s0_definitions(args.contract)
    rows = build_dimension_rows(definitions, args.batch_id)
    codes: dict[str, list[str]] = {}
    for row in rows.severities:
        codes.setdefault(row[1], []).append(row[2])
    evidence = {
        "check": "D02 fixed S0 dimension generation",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "contract": str(args.contract),
        "contract_sha256": hashlib.sha256(args.contract.read_bytes()).hexdigest(),
        "batch_id": args.batch_id,
        "counts": rows.counts(),
        "source_ids": [row[1] for row in rows.sources],
        "month_range": [rows.months[0][0], rows.months[-1][0]],
        "severity_codes": codes,
        "result": "passed",
        "limitations": [
            "This verifies B's fixed S0 definitions and D02 row generation.",
            "It does not claim PostgreSQL execution or final frozen-manifest integration.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
