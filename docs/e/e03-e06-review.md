# E03/E06 repair handoff

These changes fix the six findings in the [PR #16 review](https://github.com/A3939/advance-database-assignment-uts/pull/16#pullrequestreview-5312480114).
The original FP1 and gate were written by Role E / Aditya in
[`ac06a93`](https://github.com/A3939/advance-database-assignment-uts/commit/ac06a93cf85891ad875b98d9890680a693dda1eb)
and [`2334444`](https://github.com/A3939/advance-database-assignment-uts/commit/2334444f39c3d60ea3c92d1a50044451d0a41a82).
Role B / Peixian added these repairs and acceptance tests. Their original
commits remain in the branch history.

## Changes

- FP1 uses PostgreSQL's built-in SHA-256 and grants the missing schema USAGE.
- E06 checks actual coverage, fixed metrics, evidence files and NULL reasons.
- Summaries must agree with concrete results. Extra blocking checks also block.
- QA07 limited results retain each unmapped crash and its reason.
- The exact VIC restricted policy stays in force. It does not grant publisher
  approval, enable VIC map points or allow other years.

Runtime paths are `sql/e/fp1.sql`, `src/arsia_ingest/publication.py` and
`src/arsia_ingest/publication_checks.py`. Bindings are `e03-fp1-v1.1` and
`e06-publication-v1.1`. The gate reuses B's manifest validation, errors and
packaged VIC policy; no new Python dependency or A migration is added.

## Reproduce

Use Python 3.12, Git, Docker and an unused output directory:

```sh
git fetch origin
python3.12 tools/verify_e_postgres.py --output ../e03-e06-check
```

The command creates a detached verification checkout at B
`1ae5ddbde746f3190fec5d58daaf948b0c483817`, overlays these E files, builds a
wheel and installs it in a fresh venv. Tests run outside the source directory
with `PYTHONPATH` removed. It leaves the checkout and logs for inspection.
It does not update B's branch or replace E's C/D files.

The private PostgreSQL 16.15 container applies A
`c0824da06b6e7b3f73c4ddeab2114d10b7156913` migrations 001–011 byte for byte.
FP1 is deployed by the owner; normal callbacks use `arsia_loader`. Only fault
injection and test cleanup use owner privileges. The unchanged A03 permission
audit runs before and after. The container is removed even if tests fail.

## Results

- Installed acceptance: **61 passed, 0 skipped, 0 failed**.
- **51 real PostgreSQL tests**: actual FP1, all seven real S0 producers, 43 gate
  fault cases, context checks and rollback. The three year scopes produce
  63, 57 and 51 persisted QA rows. Valid limited and zero-crash cases pass.
- **6 VIC policy tests** and **4 original E tests**. Policy tests do not load
  official records or claim that VIC semantic execution passed.
- E branch default suite: **625 passed, 156 skipped, 0 failed**. The skips need
  database/official-data environments; they are separate from the zero-skip
  PostgreSQL acceptance run.
- A03 audits passed. All 17 data tables were empty after cleanup. Test pointer
  updates were rolled back; no shared database or official release changed.

[Receipt and file hashes](../../evidence/e03-e06/receipt-evidence-binding.json) record the tested
inputs. Full logs are generated under `OUTPUT/postgres/`; the assembly and wheel
hash are in `OUTPUT/assembly.json`.

## Evidence binding follow-up

PR #30 review found that a valid file reference could belong to another QA
object. The gate now checks file/resource/source/year identities and requires
every concrete object to be covered. C's same-source parent/child references
remain valid. Detail documents must name the right rule/object; summary files
must contain the exact stored concrete results for that batch and rule.
Ten additional PostgreSQL cases cover these substitutions and omissions.
The earlier 51-test receipt remains as the initial run record.

## E review and next steps

Aditya: review the SQL grants, metric/NULL rules, limited evidence and summary
checks. Run the command, then merge this repair into `e/aditya-e01-e06` if it
looks right. This updates the head of PR #16; it does not merge PR #16 into B.
Request another review of PR #16 after checking its current diff.

B can then import the reviewed E changes, register both real bindings and
refresh their inventory hashes. The test assembly uses a real FrozenManifest
with a partial inventory. Final platform freeze, `run_build` acceptance and
official-data replay remain separate work. No missing analysis module or hash
has been invented to make a full build pass.
