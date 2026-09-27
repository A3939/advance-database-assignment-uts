# AT15: S0 + S8 build

Peixian completed the synthetic fourth-source extension in B. The same runner
loads S0 plus one SA crash, runs QA01–QA07, calls E's FP1 and publishes through
E's real gate. No table, migration, loader grant or executor source-count rule
was changed. This is synthetic acceptance, not an official SA release.

## Code and ownership

B base: `0b9f951aee1b41a599c66c3e14dd463cdb63cbfb` (merged PR #33).
The original A/C/D/E versions remain in `config/build-inventory.json`:
A `c0824da`, C `6987e60`, D `d57c3f4`, E `aec3b46`.
Their original modules and commits remain credited to their authors.

Peixian added:

- `src/arsia_c/projections/sa.py` and `src/arsia_c/sql/s8_sa_*.sql`: the pinned
  `s8-native-v1` mapping into C's existing 24/11-field projection contract.
- SA support in `qa_expectations.py` and `qa.py`, version `c10-b-s8-v1`.
  QA derives expected values from Raw; it does not copy projection results.
  Contract admission is shared, while value calculations are separate.
- The SA dispatcher binding (`b-s8-project-v1`), `synthetic_request()` and
  `s8_request()` in `arsia_ingest.build`, inventories, tests and this handoff.

`config/build-inventory.json` hashes every installed runtime file and all eleven
migrations. `config/cd-inventory.json` records the component paths and B additions.
Both keep `final_platform: false`. The original S0 files and contracts are unchanged.

S8 retains key `0001`, numeric month `01`, month precision and direct casualty
totals. Missing counts stay NULL. No units or declared unit count are invented.
Invalid keys, dates, categories and counts block before filtering. Unusable
coordinates retain the crash without a map point. The adapter rejects official SA.

## Run

Use Python 3.12 and Docker. Run from the checkout; choose a new output directory.
The venv and validation working directory must be outside the source checkout.

```sh
python3.12 -m venv ../s8-venv
../s8-venv/bin/python -m pip install -r requirements-dev.txt -r requirements-db.txt
../s8-venv/bin/python -m pip wheel --no-deps --no-build-isolation . -w ../s8-wheel
../s8-venv/bin/python -m pip install --no-deps ../s8-wheel/arsia_native_intake-0.1.0-py3-none-any.whl
../s8-venv/bin/python tools/verify_s8_postgres.py --output ../s8-validation
```

The verifier uses a pinned PostgreSQL 16.15 image, A's unchanged migrations
001–010 plus `011_review_validation_fixes.sql`, and actual `arsia_loader` logins.
It deploys FP1 and D05–D08, checks the original A03 permission audit before and
after, and removes the private container. SQL loads from the installed wheel;
pytest runs outside the checkout with `PYTHONPATH` removed.

For a prepared S8 run, pass `s8_request(connect=..., project_root=...,
prepared_run=..., evidence_root=...)` to `run_build(**request)`. Use
`tests/fixtures/s8-bad-key/contract.json` with its matching prepared input for
the negative case. The existing runner guide explains deployment and connections.

## Results

The final installed run passed **484 checks**, including **181 real PostgreSQL
tests**, with no failures or skips. These include 69 new S8 database cases and
112 existing S0/E database regressions. The default suite passed **872 tests**
with 379 optional database/archive checks skipped. The totals overlap.

The [validation receipt](evidence/s8-validation-2026-09-27.json) records input/code
hashes, environment, commands and report hashes. Full local logs are under
`artifacts/role-b-at15-20260927/validation-final/` in the workspace.

| Check | Actual result |
|---|---|
| Inputs | 4 sources, 8 files, 20 Raw rows |
| Loaded snapshot | 7 crashes, 6 units, 7 facts |
| Dimensions | 4 sources, 60 months, 16 severity definitions, including unused categories |
| Metrics | 3 fatal crashes, 4 fatalities, 8 casualties |
| Map | 5/7 points, 71.43%; SA alone 1/1 |
| QA | 70 concrete objects and 7 summaries; no blocking result |
| Repeat | `no_change`; no duplicate Raw or batch writes |
| S0 preservation | Original source rows, Raw IDs and old B0 rows remain unchanged |
| Bad SA key | Fails in projection; B0 remains current, no candidate Vault/DW rows |

Tests also cover missing values, CRS uncertainty, exact coordinate bounds,
invalid years/counts, duplicate keys outside the analysis window, incomplete Raw,
and rollback after real Vault/DW/publication callbacks. Deliberately wrong
projection values fail independent C10 QA. Removing SA QA05/06/07 objects fails
the real E gate. Registered Raw may remain after a failed build, as designed;
no candidate business rows or published pointer survive rollback.

D05–D08 run as `arsia_reader`: all four sources appear in trend results, SA has
one severity group and no unit rows, and old batches remain readable. Test fault
injection uses the owner only to damage QA rows, then restores `arsia_loader`.

## Review and remaining work

B can review and merge this branch into `peixian/dev`. C does not need to write
S8 or approve it before B's technical validation can finish. If C later imports
the shared QA changes, keep the commits and repeat her branch's tests.

E still needs an independent acceptance review against the team AT15 expectations.
D09 integration, admitted official-source replay, final platform freezing and the
four course decisions in `docs/e/e01-course-decisions.md` remain separate.
No new S0/S8 input material is needed from Peixian.
