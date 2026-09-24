# D02 · Source / Month / Severity dimensions

This local delivery implements Role D's three warehouse dimensions from B's
frozen manifest.  It does not invent source labels, severity mappings or
coverage.

## Inputs

`build_dimension_rows()` accepts either:

- a final `FrozenManifest.as_dict()` value, where severity definitions are at
  `rules.severity`; or
- B's `s0_definitions()` value, where severity definitions are temporarily at
  the top level for fixture development.

For the fixed S0 contract the expected rows are:

| Dimension | Rows | Basis |
|---|---:|---|
| `dw.dim_source` | 3 | `syn_nsw`, `syn_vic`, `syn_qld` |
| `dw.dim_month` | 60 | every calendar month in 2020–2024 |
| `dw.dim_severity` | 12 | four complete definitions per source, including `__MISSING__` |

`dim_month` contains no invented unknown-month row. A crash known only to year
precision must later have a NULL `month_id` in `dw.fact_crash`.

## B10 callback

Register `arsia_d02.dimensions.runner_callback` as, or call it from, the `dw`
module callback. It uses `context.batch_id` and
`context.manifest.as_dict()`, writes `d02-dimensions.json` through B's evidence
writer, and leaves commit/rollback/close to B10.

When D03 is implemented, the team `dw` callback should call D02 first and D03
second on the same connection and transaction.

## Run the local checks

From this directory:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

To regenerate the S0 evidence from B's real helper, make both packages visible:

```powershell
$env:PYTHONPATH = "src;../team-repo/src"
python tools/verify_b_s0.py `
  --contract ../team-repo/tests/fixtures/s0/contract.json `
  --output evidence/s0-validation.json
```

## Integration boundary

The SQL targets the A02 table contract currently published in the team design:

- `dw.dim_source(batch_id, source_id, source_name, jurisdiction_code, release_label, release_scope)`
- `dw.dim_month(month_id, calendar_year, calendar_month)`
- `dw.dim_severity(batch_id, source_id, severity_code, severity_label, definition_version, definition_text)`

The [PostgreSQL review](docs/postgres-review.md) records real loader-role tests
against fixed A migrations 001–011, the collation fix, and reproducible commands.
The original seven scripted tests remain separate from that database evidence.
The real FrozenManifest object and B10 callback interface are verified; final
platform inventory freezing, D03, FP1 and full build/publication remain dependencies.
