# Role A review fixes

Reviewed base: `jj/a06-vault-loader` at `d30405eab42ffb2475dea9f7322e7b803b879963`.

| Item | Correction | Contract basis |
|---|---|---|
| A02 | Migration 011 requires a non-NULL `location_crs` when `map_eligible=true`. | [02 field dictionary](https://arsia-team-design.vercel.app/?lang=en#dictionary), [04 AT01](https://arsia-team-design.vercel.app/?lang=en#contracts) |
| A05 | The encoder rejects all-whitespace components, including tabs, line breaks and Unicode whitespace. Valid text is encoded unchanged. | [05 §2: Business identity](https://arsia-team-design.vercel.app/?lang=en#sources) |
| A04 | Owner investigation stays complete; the NSW contracts stay draft until a real C review is recorded. No reviewer is fabricated and no QA gate is relaxed. | [05 §5: Confirmation](https://arsia-team-design.vercel.app/?lang=en#sources), [04 §8: DEC04](https://arsia-team-design.vercel.app/?lang=en#contracts) |

## Apply and verify

Apply migrations in numeric order to a fresh database. For an existing database
with 001-010 applied, run only 011 using the existing migration account:

```sh
psql "$ARSIA_MIGRATION_DSN" -X -v ON_ERROR_STOP=1 -f sql/migrations/011_review_validation_fixes.sql
python -m pytest -q tests/test_business_key_postgres.py tests/test_canonical_constraints_postgres.py tests/test_nsw_source_review.py
psql "$ARSIA_MIGRATION_DSN" -X -v ON_ERROR_STOP=1 -f sql/tests/a03_database_roles.sql
```

Set `ARSIA_TEST_DSN` to a PostgreSQL 16 UTF-8/UTC test database connection as
`arsia_loader`; without it, the database tests skip. Do not replay historical
migrations 006 or 010 on an existing database.

Migration 011 validates existing rows inside one transaction. If an existing
map-eligible row has missing/incorrect CRS, coordinates or location lineage, the
migration fails and rolls back. Investigate those rows before retrying; the
migration neither invents a CRS nor rewrites historical data. To inspect them:

```sql
SELECT batch_id, source_id, release_scope, crash_key
FROM canonical.crash
WHERE map_eligible
  AND (latitude IS NULL OR longitude IS NULL OR location_crs IS NULL
       OR location_crs <> 'EPSG:4326' OR location_record_id IS NULL);
```

The fixed whitespace predicate uses the 29 characters recognized by Python
`str.isspace()` (Unicode White_Space plus U+001C–U+001F), independently of the
database locale. It only tests emptiness; it never trims the encoded components.

## Recorded validation — 2026-09-24

In an isolated PostgreSQL 16.15 database with migrations 001-010:

- Before 011: the new key/map regression tests produced **35 failed, 12 passed**,
  reproducing the missing NULL-CRS check and non-space whitespace acceptance.
- After 011: the three listed Python test files produced **52 passed, 0 skipped**.
- The existing A03 SQL audit passed: 17 migrator-owned tables, no loader DELETE,
  no reader access to base tables, and seven reader views.
- An actual Canonical row admitted by the old constraint caused 011 to fail.
  The old constraint, function and row survived rollback. After explicitly
  making that synthetic test row map-ineligible, 011 succeeded and retained it.

These are focused review regressions, not full A06 or project acceptance.
The remaining genuine C review and exact per-resource handoff steps are in
[the NSW source guide](sources/nsw-crash-traffic-unit.md#confirmation-and-role-c-handoff).
