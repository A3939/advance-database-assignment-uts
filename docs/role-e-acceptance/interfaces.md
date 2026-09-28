# E02 interface and ownership index

Use [the version file](../../config/e-acceptance-versions.json) for the exact
runtime and environment revisions. The receipt records what was actually run;
moving branch heads are not a replay pin.

| Interface | Implementation in the pinned B runtime | Owner and evidence |
| --- | --- | --- |
| S0/S8 input and build request | [build.py: s0_request / s8_request][build]; real `FrozenManifest`, `BuildModules`, `ModuleBinding` and evidence context | B; [build inventory][inventory], input receipts and frozen manifest |
| Full build and recovery | [runner.py: run_build][runner], [recovery.py: recover_run][recovery] | B; run markers, failure files, committed batch and pointer checks |
| E03 fingerprint | [sql/e/fp1.sql][fp1], deployed as `e.fp1(jsonb)` | E; PostgreSQL SHA-256, UTF8 and UTC; B calls the supplied operation |
| E05/E06 QA gate | [publication.py: publish][gate], `publication_checks.py` | E; persisted QA objects and evidence checked before publication; B owns commit/rollback |
| C projection, Canonical and QA | [arsia_c/qa.py][c-qa]; QA03/04/05/07 | C; original work plus separately recorded B repairs |
| D dimensions, facts and reconciliation | [D04 reconciliation][d-qa], D02/D03 callbacks | D; QA06 and source/year checks |
| D reports and page | [D09 dashboard][dashboard] using D05–D08; pinned successful batch | D; real reader queries, HTTP response and pointer-switch checks |
| Official reader limits | [official_reader.py: query_official][official-reader] | B integration of D queries; source-specific outputs and explicit unavailable results |
| E04/E07/E08 expectations | `acceptance/e/expected.py` and `config/e-acceptance-s0-v1.json` | E acceptance responsibility; supplementary implementation and execution by B |
| E09 native expectations | `acceptance/e/official_expected.py` | Hash-checked earlier native-file scans, independent of the new platform output |

## Contribution history

- Aditya's original FP1: [`ac06a93`](https://github.com/A3939/advance-database-assignment-uts/commit/ac06a93cf85891ad875b98d9890680a693dda1eb).
  Original E05/E06 gate: [`2334444`](https://github.com/A3939/advance-database-assignment-uts/commit/2334444f39c3d60ea3c92d1a50044451d0a41a82).
  The E branch baseline is [`aec3b46`](https://github.com/A3939/advance-database-assignment-uts/commit/aec3b4692382e48ea4f778f04a31a4ca5ba5fa57),
  including Peixian's [PR #30](https://github.com/A3939/advance-database-assignment-uts/pull/30) repairs.
- C's original QA implementation includes
  [`7bfb08e`](https://github.com/A3939/advance-database-assignment-uts/commit/7bfb08ee4b3b0740e554ae89c6286c39db17ead2).
  Peixian's completion and database validation are
  [`3f6c947`](https://github.com/A3939/advance-database-assignment-uts/commit/3f6c94795ee0fc8ec0f17903f23fd4a85b5646ac).
- D's original D09 implementation is
  [`d468cec`](https://github.com/A3939/advance-database-assignment-uts/commit/d468cec2392a10a10b83c2ae8d6a5caac0516995).
  Peixian's [PR #46](https://github.com/A3939/advance-database-assignment-uts/pull/46)
  fixes were merged by D as
  [`85f830e`](https://github.com/A3939/advance-database-assignment-uts/commit/85f830ef1a909050af35d9036840dd4c6bfcd751).
- A's fixed schema is
  [`c0824da`](https://github.com/A3939/advance-database-assignment-uts/commit/c0824da06b6e7b3f73c4ddeab2114d10b7156913).
  A's cold-start handoff is
  [`8f91a6b`](https://github.com/A3939/advance-database-assignment-uts/commit/8f91a6b41dc0777d5873d2151f71e9f1cbe05501),
  including B's [PR #42](https://github.com/A3939/advance-database-assignment-uts/pull/42) assistance.

Integration does not transfer ownership of another member's module. New fixes
remain separate commits with their real author. The replay manifest and receipt
record any runtime changes made after these baseline revisions.

The later B merge `06d6f2e` records the original D02/D03 history from PRs #47/#48;
its file tree matches `85f830e`. The acceptance runtime `1765269` adds the AT10
synthetic-rule and official-dashboard corrections in
[PR #49](https://github.com/A3939/advance-database-assignment-uts/pull/49).
This acceptance delivery depends on that runtime revision. The full replay pin remains
in the version file, so a history-only merge is not mistaken for new code.

[build]: https://github.com/A3939/advance-database-assignment-uts/blob/1765269507d7cf0b9cb76eef7b9ccf97de7f1cc5/src/arsia_ingest/build.py
[inventory]: https://github.com/A3939/advance-database-assignment-uts/blob/1765269507d7cf0b9cb76eef7b9ccf97de7f1cc5/config/build-inventory.json
[runner]: https://github.com/A3939/advance-database-assignment-uts/blob/1765269507d7cf0b9cb76eef7b9ccf97de7f1cc5/src/arsia_ingest/runner.py
[recovery]: https://github.com/A3939/advance-database-assignment-uts/blob/1765269507d7cf0b9cb76eef7b9ccf97de7f1cc5/src/arsia_ingest/recovery.py
[fp1]: https://github.com/A3939/advance-database-assignment-uts/blob/1765269507d7cf0b9cb76eef7b9ccf97de7f1cc5/sql/e/fp1.sql
[gate]: https://github.com/A3939/advance-database-assignment-uts/blob/1765269507d7cf0b9cb76eef7b9ccf97de7f1cc5/src/arsia_ingest/publication.py
[c-qa]: https://github.com/A3939/advance-database-assignment-uts/blob/1765269507d7cf0b9cb76eef7b9ccf97de7f1cc5/src/arsia_c/qa.py
[d-qa]: https://github.com/A3939/advance-database-assignment-uts/blob/1765269507d7cf0b9cb76eef7b9ccf97de7f1cc5/src/arsia_d04/reconciliation.py
[dashboard]: https://github.com/A3939/advance-database-assignment-uts/blob/1765269507d7cf0b9cb76eef7b9ccf97de7f1cc5/src/arsia_d09/dashboard.py
[official-reader]: https://github.com/A3939/advance-database-assignment-uts/blob/1765269507d7cf0b9cb76eef7b9ccf97de7f1cc5/src/arsia_ingest/official_reader.py
