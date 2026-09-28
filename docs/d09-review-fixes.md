# D09 review fixes

These fixes address the five comments on [PR #43](https://github.com/A3939/advance-database-assignment-uts/pull/43#pullrequestreview-5337471871).
The base is `peixian/dev` at
`c027d96d2cd114c1f1dc48198afbb687bb401a4f`, including the D10 and D11 merges.

Role D (`yyyZYH`) wrote D09 in
`d468cec2392a10a10b83c2ae8d6a5caac0516995` and delivered the integration
in PR #43. Role B / Peixian added these fixes and regression checks.
The original commits and dated evidence are retained.

## Changes

- SQL argument errors now return an escaped HTTP 400 page. Other database
  failures return a generic 500 page without internal details.
- D09 rejects years outside the pinned manifest. Blank endpoints use that
  manifest's bounds. A pointer switch does not change an existing page read.
  Standalone D05 queries keep their uncovered-period behavior.
- Trend tables show fatal-crash counts, all outcome known counts, known
  months and unknown-month exclusions. SQL NULL and zero stay distinct.
- The build test checks required pipeline components plus the separate
  dashboard group. No dashboard callback was added to B10.
- The optional PostgreSQL test skips before importing psycopg.

Runtime version: `d09-0.1.1`, under `src/arsia_d09/`.
The D09 and build inventories contain the new file hashes.
Redeploy the installed `arsia_d09/sql/d09_context.sql` as
`arsia_migrator` before starting the updated page. It adds
`published.d09_batch_years(text, uuid)`; no migration or base-table grant
changes are needed.

## Results

Python 3.12.6, PostgreSQL 16.15, A migrations 001–011 pinned to
`c0824da06b6e7b3f73c4ddeab2114d10b7156913`:

| Run | Result |
| --- | --- |
| Installed wheel, default suite | 1,002 passed, 398 skipped |
| Fresh requirements-dev environment, no psycopg | 1,002 passed, 398 skipped |
| D09 PostgreSQL verifier | 42 passed, no skips |
| B full S0 build verifier | 335 passed, no skips |

The D09 run includes 15 real database/HTTP tests and 27 unit/inventory
checks. It covers bad sources, both year bounds, default filters, SQL values
in HTML, old/new publication bounds, function permissions and HTTP 500s.
The B run includes 112 database tests for the existing build and publication
chain. Both use installed wheel code from outside the checkout.
The D09 SQL, HTML and CSS bytes match the installed resources.

Both private containers were removed. The original A03 audit passed before
and after each run, and all tracked test tables were empty at cleanup.
Default-suite skips are opt-in database and local-data checks.
A compact receipt is in `docs/evidence/d09-review-fixes-2026-09-28.json`.

## Reproduce

From the checkout, with Python 3.12 and Docker available:

```sh
d09_repo="$PWD"
d09_out="$(mktemp -d)"
python3.12 -m venv "$d09_out/venv"
d09_python="$d09_out/venv/bin/python"
"$d09_python" -m pip install -r "$d09_repo/requirements-db.txt"
"$d09_python" -m pip wheel --no-deps --no-build-isolation "$d09_repo" -w "$d09_out/wheel"
"$d09_python" -m pip install --no-deps "$d09_out"/wheel/*.whl
cd "$d09_out"
unset PYTHONPATH
"$d09_python" -m pytest -q -o pythonpath= "$d09_repo/tests"
"$d09_python" "$d09_repo/tools/verify_d09_full_build_postgres.py" --output "$d09_out/d09"
"$d09_python" "$d09_repo/tools/verify_full_build_postgres.py" --output "$d09_out/build"
```

For the no-driver check, create a second fresh venv, install
`requirements-dev.txt` and the wheel with `--no-deps`, then run the same
default pytest command outside the checkout.

## D review

Check the year rule against D09's task criteria, the displayed SQL meanings,
and the new helper's permissions. Apply the SQL alongside the wheel, then
review and merge this follow-up into `peixian/dev` if it looks right.
These are synthetic regression results. They do not replace E's independent
platform acceptance or publish an official dataset.
