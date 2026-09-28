#!/usr/bin/env python3
"""Validate the D11 three-report capture against a real private S0 build."""

import os

from verify_ac_postgres import main


if __name__ == "__main__":
    os.environ.setdefault(
        "D11_INTEGRATION_COMMIT",
        os.environ.get("ARSIA_VALIDATION_HEAD") or "working-tree",
    )
    raise SystemExit(
        main(
            tests=(),
            additional_tests=("../docs/evidence/d11-report-capture.py",),
            scope=(
                "D11 final integration: one private synthetic S0 B10/E06 "
                "publication and D05-D07 trend, severity and map reports"
            ),
        )
    )
