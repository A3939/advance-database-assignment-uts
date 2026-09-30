# D05–D08 integration in B

B packages D's four query modules and their SQL. The original import matched
`yihua/dev` commit `d57c3f4ff2fb57eb84ebc414ef77911073c0de06` byte for byte
and retains `yyyZYH` as author. Peixian added packaging, inventory and reader
tests. The later [official build](official-build.md#d08-first-read-query-fix)
adds B's D08 parent-matching repair; the other three query modules are unchanged.

| Module | Python entry | Original D commit | Version |
|---|---|---|---|
| D05 trend | `arsia_d05.query_trend` | `7f8d99c` | `d05-0.1.0` |
| D06 severity | `arsia_d06.query_severity` | `38e32e9` | `d06-0.1.0` |
| D07 points/coverage | `arsia_d07.query_map` | `6c32a65` | `d07-0.1.0` |
| D08 units | `arsia_d08.query_units` | `8df3b0c` | `d08-0.1.0` |

These are read APIs with an explicit successful batch. They are not B10 load
callbacks. The caller owns the connection and transaction.
[D09's dashboard](d09-local-dashboard.md) is now integrated; the
[official reader adapter](official-build.md) keeps its source-specific limits.

## Install and deploy

Use Python 3.12 and build the wheel from this branch. The four packages live
under `src/arsia_d05` through `src/arsia_d08`. Each includes `sql/*.sql`.

Apply A's fixed migrations 001–011 first. Then, as `arsia_migrator`, deploy:

```text
src/arsia_d05/sql/d05_trend.sql
src/arsia_d06/sql/d06_severity.sql
src/arsia_d07/sql/d07_map.sql
src/arsia_d08/sql/d08_units.sql
```

Each package's `install_sql()` returns the same packaged SQL after wheel
installation. Deployment belongs to the schema owner, not the reader.
Functions retain D's fixed `pg_catalog` search path and owner. Public query
entries grant EXECUTE to `arsia_reader` and `arsia_loader`; helper functions
remain private. No internal table access is added for readers.

```python
from arsia_d05 import TrendRequest, query_trend
from arsia_d06 import SeverityRequest, query_severity
from arsia_d07 import MapRequest, query_map
from arsia_d08 import UnitRequest, query_units

# Pin one successful batch for all queries on the page.
trend = query_trend(reader, TrendRequest("synthetic", batch_id))
severity = query_severity(reader, SeverityRequest("synthetic", batch_id))
mapping = query_map(reader, MapRequest("synthetic", batch_id))
units = query_units(reader, UnitRequest("synthetic", batch_id))
```

The [analysis inventory](../config/analysis-inventory.json) lists the actual
paths, hashes, versions, SQL deployment order and dependencies. Existing B
inventories also have the new `pyproject.toml` hash. The analysis fragment is
partial: combine it with the real remaining components before final freezing.

## Reproduce the installed checks

Use Docker, Python 3.12 and fresh output paths:

```sh
python3.12 -m venv ../analysis-venv
../analysis-venv/bin/python -m pip install -r requirements-db.txt
../analysis-venv/bin/python -m pip wheel --no-deps . -w ../analysis-wheels
../analysis-venv/bin/python -m pip install --no-deps ../analysis-wheels/arsia_native_intake-0.1.0-py3-none-any.whl
../analysis-venv/bin/python tools/verify_analysis_postgres.py --output ../analysis-results
```

The verifier checks installed resource hashes, starts private PostgreSQL
16.15, and applies A `c0824da` migrations and audits unchanged. SQL deployment
uses `arsia_migrator`. New query tests use a separate `arsia_reader` login.
The database/container are disposable; no shared release is changed.

## Original integration results

The focused run passed **131 tests, 0 skipped, 0 failed**: 63 database cases
and 68 unit/inventory cases. Twenty new database cases cover the three-source
chain, reader grants, fixed batches, filters and result semantics. The suite
also reruns D's original checks and B's seven-QA integration cases.

The normal S0 query fixture has 19 Raw rows, six crash facts, six severity
groups, four points (66.67% coverage), three NSW units and three VIC units.
QLD has no invented unit-detail rows. Zero counts and unknown values stay
distinct; month filters exclude unknown months explicitly. Reader queries
keep their batch even after the current pointer changes.

The fixture runs real C/D loading and all seven QA producers, then explicitly
seeds a successful test state so reader functions can run. It does not call
E03/E06, claim a real publication or execute complete `run_build` acceptance.
Both A03 audits passed; all 17 data tables were empty after cleanup.

[The receipt](evidence/analysis-integration-2026-09-26.json) records input,
wheel, query and report hashes. The normal default suite is recorded there
separately; its environment-dependent skips are not database acceptance.

PRs #30 and #16 are merged, and E's FP1/publication are connected in B.
The [official guide](official-build.md) records the full-snapshot runs,
D08 repair and restricted reader interface. D09 and the Docker acceptance
commands are now integrated. See the [main integration record](main-integration.md)
for exact later evidence and remaining course materials. The original seeded
S0 checks do not prove publication or approve unrestricted use.
