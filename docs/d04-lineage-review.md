# D04 lineage review

PR18's same-file wrong-row gap is confirmed in PostgreSQL 16.15. D04 returns
`pass` after six deliberate lineage changes. C09 rejects the same six changes
before Canonical loading. This is a gap in D04's independent check; the tests
do not show that the normal C09 pipeline produces these bad rows.

## Tested versions

- B / [PR18](https://github.com/A3939/advance-database-assignment-uts/pull/18): `ecd946ef725f3c28aa91d71c06e4663eceb1d480`.
- D input: `337101f68079ed666701c43f387a5df1c526ed4a`.
- C input: `ad8baeddd3f6d2eeccdc2e31bafd71b687ad4da8`.
- A schema: `c0824da06b6e7b3f73c4ddeab2114d10b7156913`, migrations 001–011 and the original A03 audit.
- D04 path in B: `src/arsia_d04/reconciliation.py`; its runtime bytes are unchanged.
- Tests: `tests/test_d04_lineage_postgres.py`. Runner: `tools/verify_d04_lineage_postgres.py`.

## Results

| Run | Passed | Failed | Skipped |
|---|---:|---:|---:|
| Defect reproduction and controls | 31 | 0 | 0 |
| Required fix assertions on unchanged D04 | 25 | 6 | 0 |

These are two modes of the same 31 checks, not 62 separate tests. They include
26 database behavior checks and five inventory/interface/preflight checks.
The six failures are the expected evidence that the fix is still needed.

| Owner-injected change after C09 and D03 | Cases | Current QA06 | Required QA06 |
|---|---:|---|---|
| Primary Raw points to another crash in the same file (NSW/VIC/QLD) | 3 | pass | block |
| Direct location points to another crash Raw (NSW/QLD) | 2 | pass | block |
| VIC location points to a Node with a different parent | 1 | pass | block |

Each replacement keeps the source, resource, file hash and parser unchanged.
The tests compare ordered native keys with A's SQL encoder. Fact rows stay
unchanged. D04 writes 15 passing source-year rows and a passing batch summary,
with `lineage_error_count=0` and no difference file.

Controls confirm that C09 rejects all six corresponding Satellite changes.
D04 still blocks a wrong-file primary and a changed fact coordinate. Loader
UPDATE is denied, missing/cross-source Raw references fail foreign keys, and
caller rollback leaves no rows. The normal S0 chain still has 19 Raw rows,
6 crashes, 6 units, 3/60/12 dimensions and 6 facts.

## Reproduce

Use Python 3.12 and Docker. From a clone of the repository, create a separate
checkout so your own branch stays unchanged:

```sh
git fetch origin
git worktree add --detach ../arsia-pr18-review origin/peixian/b-cd-integration
cd ../arsia-pr18-review
python3.12 -m venv ../.venv-pr18
../.venv-pr18/bin/python -m pip install -r requirements-db.txt
../.venv-pr18/bin/python -m pip wheel --no-deps --no-build-isolation . --wheel-dir ../pr18-wheels
../.venv-pr18/bin/python -m pip install --force-reinstall --no-deps ../pr18-wheels/arsia_native_intake-0.1.0-py3-none-any.whl
../.venv-pr18/bin/python tools/verify_d04_lineage_postgres.py --output ../pr18-lineage-reproduction
../.venv-pr18/bin/python tools/verify_d04_lineage_postgres.py --require-fix --output ../pr18-lineage-fix-check
```

Use new checkout/venv/output directory names if they already exist. The first
verification command exits 0 only when the known defect and controls reproduce.
The `--require-fix` command exits 1 on current D04. After
D's fix is integrated, update the real inventory hashes, rebuild/install the
wheel and use `--require-fix`; all 31 checks should then pass.

The runner checks A's migration and audit bytes against the fixed local Git
commit before starting Docker. Each run uses a fresh container, loopback port
and temporary data volume. A03 audits pass before and after, all 17 tables end
empty, and containers are removed. The new fault tests use an owner session
with `SET ROLE arsia_loader` for every application call; only labelled injection
uses the owner. Existing B chain tests use a direct loader login. Grants are unchanged.

The [six case snapshots](evidence/d04-lineage-cases-2026-09-25.json) include the
original/replacement Raw rows and persisted QA object/batch results. Full local
logs remain in the two output directories; rerunning the commands produces a
new copy. The [receipt](evidence/d04-lineage-review-2026-09-25.json) records their
hashes and the installed code. Its uncommitted test state describes the run
before this delivery commit. The manifest uses the real
`FrozenManifest` constructor and a partial inventory. No FP1 or publication is performed.

## Handoff

D should fix `src/arsia_d04/reconciliation.py` on `yihua/dev`, or through a small
fix branch and PR targeting `yihua/dev`. Check the primary Raw key,
direct-location identity and ordered Node parent fields from the frozen contract.
Keep A's key encoder, loader permissions and caller-owned transaction. The fix
must block the affected object and batch, record one lineage error, and write
detail evidence for the exact source/crash. It must keep the valid S0 case passing.

B will review D's commit/PR and test output, import the fix into PR18, update
inventory hashes and rerun fix acceptance plus affected integration tests.
Please link the fix and results in PR18; keep PR18 open until that rerun passes.
This delivery adds the
reproduction, regression assertions and evidence; it does not change D04.
C10, E FP1/publication and final inventory remain separate full-B10 dependencies.
