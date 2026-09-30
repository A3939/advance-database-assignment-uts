# QA01–QA07 joint validation

All seven QA groups now have a joint S0 test on B's installed package. The normal run writes 56 concrete results and seven summaries for one batch. QA01–QA06 pass. QA07 is correctly `limited` for two retained, unmapped crashes.

B base: `8b752870c624eed10d87ad6e52b636453e621f2e` (PR #27). C10/C06 match C's PR #28 merge `6987e604bb93809aa94a736085c3e8320452461d`. D04 is the integrated `daa9e575732b9016ffbe0b5024f67a055a2947ad` fix. A is `c0824da06b6e7b3f73c4ddeab2114d10b7156913`, migrations 001–011. The existing 77-file component inventory and 11 migration hashes are unchanged.

## What ran

`tests/test_qa_joint_postgres.py` uses B's real S0 definitions, `FrozenManifest`, `ModuleBinding`, `ModuleConnection`, `RunContext` and evidence paths. It calls QA01, loads Raw and the projection/Vault/Canonical/DW chain, then runs QA02, C10 and D04 in the runner's order. Each producer writes its actual results to `qa.check_result`.

| Rule | Required concrete results | Normal result |
|---|---:|---|
| QA01 input | 7 files | pass |
| QA02 Raw | 7 files | pass |
| QA03 projection | 5 resources | pass |
| QA04 auxiliary | 4 resources | pass |
| QA05 semantics | 3 sources | pass |
| QA06 reconciliation | 15 source-years | pass |
| QA07 location | 15 source-years | 13 pass, 2 limited |

The chain retains 19 Raw rows, six crashes, six units, four map points and 3/60/12 dimension rows. The four Node observations remain; their two duplicate groups and one coordinate-conflict group are recorded. Zero-crash years have NULL map coverage.

The 23 new database cases cover:

- Normal S0, a narrower year range and an entirely empty reporting range.
- A changed archive and one fault in each downstream QA group. Later checks stay unexecuted after a block.
- Each missing summary, a missing concrete result, repeat writes from all four producers, and unchanged QA history in a second batch.
- Required object keys, fixed metrics, summary counts, evidence hashes and caller rollback. Rolled-back evidence files remain readable.

Fault injection uses the private database owner only where persistent rows must change. Producers still run as `arsia_loader`. The QA02 failure case persists its blocked report for inspection; the normal runner would stop before that write. A03 permission audits pass before and after. All 17 tables are empty after cleanup and the disposable container is removed.

## Results and repeat command

| Suite | Passed | Skipped | Failed |
|---|---:|---:|---:|
| Joint verifier and related regressions | 125 | 0 | 0 |
| Installed default suite, including clean-wheel checks | 734 | 353 | 0 |

The verifier includes 68 database cases, four inventory checks, one build-preflight check and 52 runner unit tests. It reruns the earlier C10 year cases and D04 lineage cases. The two suites overlap. Default skips require PostgreSQL or optional official archives.

Use Python 3.12 and Docker. Build and install the wheel in a separate venv, with `PYTHONPATH` unset:

```sh
python3.12 -m venv ../qa-joint-venv
../qa-joint-venv/bin/python -m pip install -r requirements-db.txt
../qa-joint-venv/bin/python -m pip wheel --no-deps --no-build-isolation . -w ../qa-joint-wheels
../qa-joint-venv/bin/python -m pip install --no-deps ../qa-joint-wheels/arsia_native_intake-0.1.0-py3-none-any.whl
../qa-joint-venv/bin/python tools/verify_qa_joint_postgres.py --output ../qa-joint-results
```

Use a fresh output directory. The [receipt](evidence/qa-joint-validation-2026-09-25.json) pins the image, inputs, commands and local evidence under `artifacts/role-b-qa-joint-20260925/`.

## Boundary and next work

This is joint component validation, not a complete `run_build` or publication run. It uses a real `FrozenManifest` with partial inventory and labelled test batch identifiers, not E's FP1. There is no dummy publication callback. History fixtures are explicitly unpublished. Official archives and the VIC restricted profile were not replayed here.

One case removes a concrete result while leaving all seven summaries. B's summary transport still accepts those summaries; the independent test coverage check rejects the missing object. This is why E's complete object gate is still required. The test helper is not a deployed gate.

B can now move from S0 component checks to agreed official-scope integration. C/D own source semantics and module follow-ups. E still supplies corrected, database-tested FP1 and publication code. B and the module owners then freeze the full inventory and run full B10 acceptance.

A, C and D retain ownership of their modules. Peixian added these joint tests, the verifier and evidence as Role B. No business code, permission, migration or source policy changed in this delivery.
