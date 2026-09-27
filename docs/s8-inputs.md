# AT15: S8 input preparation

S8 adds one fictional SA crash to S0, as specified in team v1.1 document 04 §5. The expanded input has **four sources, eight resources and 20 L1 records**. The original seven S0 files and their manifest definitions stay unchanged. See [B's S8 integration](s8-integration.md) for the installed projection, full-build commands and database results.

## Definition and files

[`synthetic-s8.json`](../config/synthetic-s8.json) defines the CSV fields, values, coverage and mapping. It uses `source_id=syn_sa`, `resource_id=syn_sa_crash`, `release_scope=s0`, release label `Synthetic S8 v1` and the existing fictional `syn-1` severity categories. Peixian adds the SA projection and QA support in B's integration; C retains authorship of the original projection and QA modules.

| Field | Native text |
|---|---|
| CRASH_ID | `0001` |
| YEAR / MONTH | `2020` / `01` |
| SEVERITY | `F` |
| FATALITIES / CASUALTIES | `1` / `1` |
| LATITUDE / LONGITUDE | `-34.92` / `138.60` |

Casualties include deaths. The date has month precision. The invented coordinates are explicitly defined as EPSG:4326; no official SA data or CRS claim is involved. S8 supplies no unit records or declared unit count. Its synthetic coverage is every month in 2020–2024, using the same analysis window as S0.

Two shared fixture directories are ready to read:

- [`tests/fixtures/s8/`](../tests/fixtures/s8/): normal S0 + S8.
- [`tests/fixtures/s8-bad-key/`](../tests/fixtures/s8-bad-key/): the same input with S8's `CRASH_ID` replaced by exactly three spaces.

Each contains `syn_sa_crash.csv`, `config.json` and `contract.json`. The configurations reference the seven files in `../s0/`; no copies are needed. Both variants prepare 20 records. The reader preserves the bad key, leading zeros and decimal text for later SQL checks.

## Prepare or regenerate

Run from the repository root with the existing environment:

```sh
.venv/bin/python -m arsia_ingest --config tests/fixtures/s8/config.json --output artifacts/s8-intake
.venv/bin/python -m arsia_ingest --config tests/fixtures/s8-bad-key/config.json --output artifacts/s8-bad-key-intake
```

For fresh standalone copies, choose new or empty output directories:

```sh
.venv/bin/python tools/create_s0_inputs.py --output artifacts/s8-inputs --variant s8
.venv/bin/python tools/create_s0_inputs.py --output artifacts/s8-bad-key-inputs --variant s8_bad_key
```

Add `--reuse-s0 tests/fixtures/s0` to reference existing S0 files instead. The generator compares every reused file with the generated baseline bytes and refuses mismatches. Each variant starts independently from S0. Existing output is never replaced.

## Manifest and QA01

Use the existing B09 helper with either fixture contract:

```python
from arsia_ingest.manifest import s0_definitions

definitions = s0_definitions("tests/fixtures/s8/contract.json")
```

This returns four sources, eight contracts/mappings and 16 severity entries. S8 has its own version, coverage and confirmation basis; the seven S0 definitions are unchanged. `arsia_ingest.build.s8_request()` combines the matching prepared run with the actual build inventory and all seven callbacks. `synthetic_request()` takes an explicit `contract_path` for a generated variant. Both return arguments for `run_build`; they do not publish until the runner succeeds. See the [manifest guide](manifest.md#using-s0-and-s8).

QA01 requires the declared mappings to match the supplied supported mappings. The installed SA projection also validates its supported synthetic contract. The input-only tests explicitly supply fixture mapping support; omitting it blocks with `MAPPING_UNSUPPORTED`. QA01 preserves the bad key, which the SA business projection must reject.

## Checks and handoff

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
```

[`test_s8.py`](../tests/test_s8.py) checks native values, file hashes, counts, reproducible generation, S0 preservation, manifest assembly and QA01's mapping boundary. Manifest tests use temporary test-only code inventories. The [validation receipt](evidence/at15-b-input-validation-2026-09-19.json) records the actual results and final file hashes; earlier receipts are unchanged.

AT15 expects 20 Raw rows, 7 crashes, 6 units, 3 fatal crashes, 4 deaths, 8 casualties and 5/7 map coverage, with the original three states unchanged. The bad-key run must fail while preserving B0. These constants come from the team contract; actual database results and reproduction commands are recorded separately in [S8 integration](s8-integration.md).

B's extension reuses A's schema/A06, C's existing modules, D's dimensions/facts/queries and E's real FP1/publication gate. E can use these unchanged fixtures for an independent acceptance comparison. The older receipt remains an input-preparation record; no official SA data or whole-project acceptance is claimed.
