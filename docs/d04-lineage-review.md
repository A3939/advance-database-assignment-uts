# D04 lineage integration and acceptance

B now uses D's fix from [PR #23](https://github.com/A3939/advance-database-assignment-uts/pull/23).
The six same-file wrong-row cases now block QA06 and retain located evidence.
D wrote the runtime fix. Peixian (Role B) added the reproductions, integrated the
fix, updated B's binding/inventory and reran the installed-package checks.

## Versions

- B base: `a1768623aef837daa082f7ed564d97c07b60b4cf`, including B14 from PR #19.
- D branch: `yihua/dev` at `d57c3f4ff2fb57eb84ebc414ef77911073c0de06`.
- Original D fix: `daa9e575732b9016ffbe0b5024f67a055a2947ad`.
- B import: `f21dd70`; cherry-picked with D's author and original commit reference.
- C projection/Canonical input: `ad8baeddd3f6d2eeccdc2e31bafd71b687ad4da8`.
- A: `c0824da06b6e7b3f73c4ddeab2114d10b7156913`, migrations 001–011 and original A03 audit.

`src/arsia_d04/reconciliation.py` matches D's merged runtime byte for byte.
Its producer version is `d04-0.1.1`; B's binding is `d04-daa9e57`.
B uses `config/cd-inventory.json` for its combined component layout. D's standalone
inventory was not copied because B has different packaging and dependencies.
The D unit test retains B's existing combined-inventory assertion.

## What is checked

| Owner-injected change after normal C09/D03 | Cases | Required result |
|---|---:|---|
| Primary Raw points to a different crash in the same file, NSW/VIC/QLD | 3 | Object and batch block |
| Direct location points to a different crash Raw, NSW/QLD | 2 | Object and batch block |
| VIC location points to a Node with a different parent | 1 | Object and batch block |

Each case keeps the source, resource, file hash and parser unchanged. Facts stay
unchanged. Assertions require exactly one lineage error, affected count one,
and a matching source/crash in the hashed detail file. The other 14 source-year
objects still pass. C09 independently rejects the six equivalent pre-load faults.

Controls cover wrong-file references, changed fact coordinates, loader UPDATE
denial, foreign keys, visibility from a fresh session and caller rollback.
Normal S0 still produces 19 Raw, six crashes, six units, 3/60/12 dimensions,
six facts and 15 passing QA06 objects plus one summary.

The installed focused suite passed **31 tests, 0 skipped, 0 failed** on Python
3.12.6 and private PostgreSQL 16.15. It contains 26 database behavior checks and
five inventory/interface/preflight checks. A03 audits passed before and after;
all 17 tables ended empty and the container was removed. Fault injection uses
the test owner; application calls use the unchanged loader privileges.

The [acceptance receipt](evidence/d04-lineage-acceptance-2026-09-25.json) records
versions, hashes, commands, six case results and cleanup. The broader component
results are listed in the [integration guide](cd-integration.md). These suites
overlap; their totals must not be added as separate coverage.

## Reproduce

Use Python 3.12, Docker, a fresh venv and new output directories:

```sh
python3.12 -m venv ../.venv-b-cd
../.venv-b-cd/bin/python -m pip install -r requirements-db.txt
../.venv-b-cd/bin/python -m pip wheel --no-deps --no-build-isolation . --wheel-dir ../b-cd-wheels
../.venv-b-cd/bin/python -m pip install --no-deps ../b-cd-wheels/arsia_native_intake-0.1.0-py3-none-any.whl
unset PYTHONPATH
../.venv-b-cd/bin/python tools/verify_d04_lineage_postgres.py --require-fix --output ../d04-acceptance
../.venv-b-cd/bin/python tools/verify_cd_postgres.py --output ../cd-postgres
```

Both verifier commands now enforce the fix. `--require-fix` remains accepted for
older run instructions. The six cases also run in the normal CD database suite.
The wheel is checked against source hashes and loaded outside the source tree.
No schema, privilege or business rule is relaxed.

## Earlier finding and remaining work

At B commit `2750d8e`, D04 still missed the six cases. The old reproduction passed
31 checks; the old acceptance run had 25 passes and six failures. The
[original receipt](evidence/d04-lineage-review-2026-09-25.json) and
[case snapshots](evidence/d04-lineage-cases-2026-09-25.json) remain historical evidence.

This closes the D04 integration finding in PR #18. Real `FrozenManifest` objects
are used with a partial inventory; this is not an E FP1 or full B10 release.
C10 is merged upstream in C's PR #26 but still needs B integration and verification
of its QA07 year-coverage finding. E's FP1/publication fixes, the final inventory,
and D05–D08 query integration remain separate work.
