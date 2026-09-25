# C10 QA07 year coverage

QA07 only visited the manifest's analysis years. An extra current-batch Canonical crash or fact outside that interval was therefore absent from its results. This fixes the [PR #26 finding](https://github.com/A3939/advance-database-assignment-uts/pull/26#discussion_r4102996024).

It also fixes [PR #27's invalid-Raw attribution finding](https://github.com/A3939/advance-database-assignment-uts/pull/27#discussion_r4104548369).

## Reproduction and change

The PostgreSQL reproduction added 2019 and 2025 crashes for each S0 source under the 2020–2024 manifest. It also tested an extra Canonical crash without a fact. All seven cases left QA07 `limited` instead of `block`. QA05 already blocked these cases, so the evidence shows a QA07 coverage gap, not a successful C10 or publication bypass.

QA07 now visits the union of configured years and years present in the selected sources' current-batch Canonical/fact rows. Extra years produce blocking `source_year:<source_id>:<year>` results with zero expected crashes, `outside_analysis_year` reasons, located JSON evidence and a blocking QA07 summary. Required zero-row years remain present. The manifest interval and Raw rows are unchanged.

Invalid Raw crashes are now grouped by their native year before QA07 runs. A valid year token can still locate an error when its month or day is invalid; it does not make the date valid. When no year can be assigned, one extra `unknown_year:<source_id>` blocking diagnostic records `unassigned_raw_count` and located reasons. Required source-year objects keep their existing metrics. No year is invented and unrelated empty years no longer inherit the same error.

Runtime: `src/arsia_c/qa.py` and `qa_expectations.py`, version `c10-role-c-v1.2`. The fragment in `config/c10-inventory.json` has the new hash. No migration, grant, SQL-resource or business mapping changed. The callback still leaves commit and rollback to B.

## Validation

| Run | Passed | Failed | Skipped |
|---|---:|---:|---:|
| Before fix, B interface suite with new cases | 71 | 7 | 0 |
| Before Raw attribution fix, six added cases | 78 | 6 | 0 |
| Fixed C10/C06 database suite | 113 | 0 | 0 |
| Fixed B callback/interface suite | 84 | 0 | 0 |
| C wheel and Person adapter regression | 21 | 0 | 0 |

The C database suite contains 28 existing C10 cases, 69 C06 cases and 16 new year-coverage cases. The B suite includes those same 16 new cases; totals overlap. Six Raw-attribution cases cover bad months/dates/counts, an unknown year and an out-of-scope native year. The three controls cover inclusive interval boundaries, retained out-of-scope Raw and unchanged committed history from another batch.

Tests used Python 3.12.6, installed wheels and isolated PostgreSQL 16.15. A `c0824da06b6e7b3f73c4ddeab2114d10b7156913` migrations 001–011 and the original A03 audit were retained. The extra-crash fixtures use `arsia_loader` INSERT permissions with foreign keys enabled. The six labelled Raw mutations use the private database owner, then switch back to `arsia_loader` for QA; no grants are changed. Both fixed database runs passed the before/after permission audit, left all 17 tables empty after cleanup and removed their containers. No shared database was used.

The [receipt](c10-year-coverage-validation.json) records input hashes and local logs under `artifacts/c10-year-coverage-20260925/`.

## Run

From C's checkout, with Python 3.12 and Docker:

```sh
python3.12 -m venv ../c10-year-venv
../c10-year-venv/bin/python -m pip install -r requirements-dev.txt 'psycopg[binary]==3.3.6'
../c10-year-venv/bin/python -m pytest -q tests/test_c10_packaging.py tests/test_person_checks.py
../c10-year-venv/bin/python tools/verify_c10_postgres.py --output /path/to/new-results
```

The existing verifier assembles C with B checkpoint `2750d8ea3f909cfacdc4cb10b35b87ffe729a468`. The separate B run uses PR #27's real installed binding on base `8e794241a231dc53857b67e1829ac9d80111b4ab`. Both use real `FrozenManifest` objects with partial inventories. Fetch the pinned B and A commits if they are missing locally.

## Ownership and review

Role C wrote the original C10 (`7bfb08e`, `ba65982`, `b0626ea`). Peixian's earlier supplement is `3f6c94795ee0fc8ec0f17903f23fd4a85b5646ac` in PR #26. This fix and its tests are Peixian's assistance as Role B, recorded in `975d8b6456d3e31cf711e48dd7c449610db0dc0d` (range coverage) and `c3fbbd45f6d5511e89cee7083f80a42c8347b6f1` (Raw attribution) on C base `9697c9f65b35477b03d5d05e0adc00bf15235e2c`.

C should review the extra-year blocks, the unknown-year diagnostic, summary counts, evidence and regression cases, then merge this small fix into `yue/role-c`. B reuses the same fix through PR #27 and updates its binding version and inventory. Original authorship is unchanged.

Full official archives were not replayed for this patch. Combined QA01–07, E's corrected FP1/publication and final B10 acceptance remain separate. This patch does not claim publication or full-platform completion.
