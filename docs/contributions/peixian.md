# Peixian's contribution record

Role B: Peixian Zheng (`JohnCoffey-commits`; commits also use `ZHENG PEIXIAN`).
This index links the work and its evidence. It does not estimate hours or a contribution percentage.

## B implementation

| Work | Evidence |
|---|---|
| Native CSV/XLSX readers, archives, L1 output and S0 inputs | [Intake guide](../native-intake.md), [S0 guide](../s0-inputs.md), commit `2aa2518` |
| VIC Person/Node source checks and four-file compatibility evidence | [VIC review](../sources/vic-accident-vehicle.md), commit `ed50938` |
| Source/resource registration, repeat-safe Raw loading and payload checks | [Raw loading](../raw-loading.md), commit `96cf67a` |
| Manifest validation, frozen definitions, file hashes and the FP1 call adapter | [Manifest guide](../manifest.md), commit `035188e`; E owns the FP1 SQL |
| QA01/QA02, shared-transaction runner, evidence and S8 fixtures | [Input QA](../input-qa.md), [Runner](../runner.md), commit `cbb548e` |
| Uncertain-commit recovery and abandoned-run handling | [Recovery](../recovery.md), commit `3185b84` |
| VIC restricted-use rules in B09/B11 | [Restricted inputs](../vic-restricted-inputs.md), commit `bc4ed6b` |
| B10 isolation, failure diagnostics and recovery fingerprint fixes | [Validation and receipt](../b10-local-validation.md), commit `a469dda` |

## Review and fixes for other roles

| PR | B's change | Original module owner |
|---|---|---|
| [#4](https://github.com/A3939/advance-database-assignment-uts/pull/4) | Clarified VIC unit projection and count restrictions in the policy | C |
| [#5](https://github.com/A3939/advance-database-assignment-uts/pull/5) | Fixed NULL CRS and blank business-key constraints; added database regression checks | A |
| [#6](https://github.com/A3939/advance-database-assignment-uts/pull/6) | Fixed severity comparison ordering; added real PostgreSQL and B-interface validation | D |
| [#7](https://github.com/A3939/advance-database-assignment-uts/pull/7) | Fixed C03 contract, mapping, scope and Raw checks; added regressions | C |
| [#9](https://github.com/A3939/advance-database-assignment-uts/pull/9) | Added C09 lineage, link, type and stored-value validation | C |
| [#11](https://github.com/A3939/advance-database-assignment-uts/pull/11) | Fixed C07 CRS, rounding and installed SQL resources | C |
| [#12](https://github.com/A3939/advance-database-assignment-uts/pull/12) | Fixed the QLD synthetic unknown-CRS reason and added regression tests | C |
| [#24](https://github.com/A3939/advance-database-assignment-uts/pull/24) | Returned B's C03 resource-loading fix to C and added a clean-wheel installation regression | C |
| [#25](https://github.com/A3939/advance-database-assignment-uts/pull/25) | Completed the C11 handoff and ran 12 PostgreSQL queries over the four full VIC originals | C |
| [#26](https://github.com/A3939/advance-database-assignment-uts/pull/26) | Extended C's initial C10 with QA03/04/05/07, persistence, resources and database checks | C |
| [#28](https://github.com/A3939/advance-database-assignment-uts/pull/28) | Reproduced QA07's year-coverage gap, fixed Raw year attribution, added blocking objects/evidence and sixteen database regressions; merged into C | C |

PR #5 has JJ's Approved review. PR #6 has D's Approved review, submitted after its merge.
PRs #4–#26 listed above and PR #28 were merged. Peixian merged PR #28 with C's agreement, as confirmed by Peixian; no formal GitHub Approved review was submitted for it. This record does not claim other formal approvals.

## Integration and validation

| Delivery | B's work |
|---|---|
| [PR #8](https://github.com/A3939/advance-database-assignment-uts/pull/8) | Installed D02 in B; checked genuine FrozenManifest, context, evidence and database behavior |
| [PR #10](https://github.com/A3939/advance-database-assignment-uts/pull/10) | Integrated A06, C03, C09 and D02; fixed package resources and validated the NSW component chain |
| [PR #17](https://github.com/A3939/advance-database-assignment-uts/pull/17) | Prepared the tested shared main baseline and documented module ownership |
| [PR #19](https://github.com/A3939/advance-database-assignment-uts/pull/19) | Added real PostgreSQL recovery tests and a verifier pinned to A's fixed migrations; see the [B14 record](b14-postgres.md) |
| [Three-source C/D integration](../cd-integration.md) | Added the source dispatcher, real bindings, inventory and installed-package PostgreSQL validation in B |
| [PR18 D04 lineage acceptance](../d04-lineage-review.md) | Reproduced six missed checks, added controls, then imported D's PR #23 fix and updated B's inventory. All 31 focused checks and 619 broader checks passed; totals overlap. D owns the runtime fix. |
| [C10 integration](../c10-integration.md) | Connected C's merged QA callback to B, included C06 resources, updated inventory and added clean-wheel and real PostgreSQL interface tests |
| [S0 QA01–QA07 joint validation](../qa-joint-validation.md) | Added 23 real database cases across all seven producers, verified 56 concrete results and seven summaries, and preserved rollback/history evidence; 125 focused checks passed |
| [PR #16 review](https://github.com/A3939/advance-database-assignment-uts/pull/16#pullrequestreview-5312480114) | Reproduced E's FP1 deployment, permission and publication-gate defects and published a request-changes review; E owns the follow-up fixes |

A's migrations/A06, C's projection/Canonical modules and D's dimensions/facts/reconciliation remain their work.
Importing those files into B is integration, not original authorship. Test totals in different receipts overlap.
PRs #24–#26 are merged into C's branch. C10 and the QA07 fix are included in B PR #27. S0 QA01–QA07 joint validation passes; official-scope validation remains separate. E FP1, publication and the final inventory still need full-build acceptance. The contribution records distinguish original module work, B's additions and integration; they do not claim team-wide completion.
