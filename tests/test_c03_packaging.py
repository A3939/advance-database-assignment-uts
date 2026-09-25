"""C03 SQL must travel with the installed package."""

from pathlib import Path

from arsia_c.projections.nsw import SQL_DIR, _load_sql


SQL_NAMES = {
    "c03_nsw_relationship_check.sql",
    "c03_nsw_year_check.sql",
    "c03_nsw_month_check.sql",
    "c03_nsw_semantic_check.sql",
    "c03_nsw_unit_check.sql",
    "c03_projection_tables.sql",
    "c03_nsw_crash_insert.sql",
    "c03_nsw_unit_insert.sql",
    "c03_nsw_projection_check.sql",
}


def test_packaged_sql_matches_the_reviewed_sources(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "src/arsia_c/projections/sql"
    monkeypatch.chdir(tmp_path)
    assert {p.name for p in SQL_DIR.iterdir() if p.name.endswith(".sql")} == SQL_NAMES
    for name in SQL_NAMES:
        assert _load_sql(name) == (source / name).read_text(encoding="utf-8")
