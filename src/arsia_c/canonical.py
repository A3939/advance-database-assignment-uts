from __future__ import annotations

from arsia_ingest.vault_load import iter_satellites


def load_canonical(connection, context) -> None:
    crash_rows = iter_satellites(
        connection,
        context,
        "crash",
    )

    unit_rows = iter_satellites(
        connection,
        context,
        "unit",
    )

    # Canonical inserts are added next.
    _ = crash_rows
    _ = unit_rows
