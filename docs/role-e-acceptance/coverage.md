# E07–E09 acceptance coverage

The acceptance entry point is `tools/verify_e_acceptance.py`. New E tests are
copied into the pinned runtime's `tests/` directory. Existing module tests are
rerun as supporting evidence; their original author is unchanged. This table
maps checks to requirements. Results come from the current run's XML and receipts.

| AT | Main checks | Test and evidence location |
| --- | --- | --- |
| 01 | Empty schema, 17 tables/129 fields/30 FKs, original role audit, invalid map without CRS, reader isolation | A `verify_a09_cold_start.py`; E07 `test_e07_at01_schema_and_unchanged_reader_boundary`; `cold-start.json`, A03 logs, `e07/at01.json` |
| 02 | Seven files, Raw 19, fields and stable locators; missing file/header/hash and payload conflict rejected; B0 retained | E07 `test_e07_at02_bad_native_preparation_preserves_real_b0`; `test_raw_load_postgres.py`, `test_input_qa_postgres.py`; E07 admission receipts. Failed native preparation stops before constructing B10. |
| 03 | Same native IDs remain distinct by source; valid parents; duplicate/orphan faults cannot publish | E07 `test_e07_full_s0_layers_rows_lineage_and_independent_qa`; B `test_invalid_native_values_cannot_publish`; Canonical/fact/parent observations |
| 04 | Blank Person vehicle reference passes, nonexistent 99 fails; all four Node observations remain and V2 stays unmapped | The complete S0 build and independent row checks; B's `person_vehicle_99` variant; C's stored QA04/QA07 evidence |
| 05 | NULL stays unknown, dates keep their precision, fatal crashes differ from people; invalid date/count/category fail | E07 row/query oracle; B's `invalid_date`, `negative_count`, `undefined_category` variants |
| 06 | Exact Canonical/fact values, source/year coverage, lineage; missing fact, compensating counts and eligibility errors block | E07 `test_e07_at06_real_reconciliation_rejects_damaged_candidate`; `test_d04_lineage_postgres.py`; retained B0 and failure receipts |
| 07 | Six crashes retained, map 4/6; conflicting/missing locations are limited; forced invalid eligibility fails | E07 `test_e07_at07_forced_invalid_location_rolls_back_real_candidate`; B's invalid-coordinate/unknown-CRS variants |
| 08 | Same files/rules, moved archive and reordered JSON give the same FP1/batch/pointer timestamp | E08 `test_at08_provenance_and_object_order_keep_exact_pointer`; B's normal `no_change` test |
| 09 | N1 change gives 6 crashes/4 deaths/8 casualties; explained Q2 deletion gives 5/3/7; old batch retained | B `test_real_snapshot_change_keeps_successful_history`; unexplained shrinkage rejection; independent scenario values in the E oracle |
| 10 | Declared synthetic N2 rule makes fatal-known count 6 while people-known counts stay 5; real SQL-byte change rebuilds | E08 `test_at10_rule_matches_independent_expected_known_counts` and `test_at10_real_sql_byte_change_rebuilds_without_changing_inputs`; actual changed rule/SQL and frozen hashes |
| 11 | Missing concrete object in each QA group blocks despite seven summaries; invalid block/limited/evidence also fails | E08 `test_at11_missing_object_preserves_published_baseline`; B/E gate fault tests; omitted object and preserved pointer recorded |
| 12 | Faults after Vault/DW/publication roll back; lost acknowledgement and disconnect reconcile without rewriting success | B full-build tests; E08 disconnect and superseded-commit tests; B14 replay. Fault type is recorded; a client disconnect is not a server outage. |
| 13 | Second session is busy without registration; first session retains its lock through registration and releases it on exit | B `test_concurrent_real_build_is_busy_then_no_change`; B14/runner PostgreSQL tests |
| 14 | Queries retain the page's original successful batch after a pointer switch; refresh changes it; invalid mode/status rejected | `test_d09_full_build_postgres.py`; actual B10/E06 publications and reader queries, not an empty callback |
| 15 | S8 uses the shared schema and pipeline: Raw20/crashes7/units6, fatal/death/casualty3/4/8, map5/7, QA77; bad key protects B0 | `test_s8_build_postgres.py`; E oracle's S8 row and totals. This synthetic extension approves no official SA contract. |
| 16 | Every S0 source/year/month, severity and map result; N2-only unknowns; empty 2024; first no-publication and month13 HTTP | E07 query and HTTP tests. N2-only is an explicitly labelled, rolled-back query-module fixture, not a page filter or published subset. |
| 17 | Fresh clone, venv, installed wheel, empty PostgreSQL, recorded permissions/cleanup; official costs separately measured | Replay receipt, A cold-start receipt and E09 official files. Human replay by a member uninvolved in setup is still separate. |

E07 covers AT01–07 and AT16. E08 covers AT08–15. E09 records technical cold-start
and real-scale evidence. An automated pass does not supply E's personal review,
teacher approval or final submission acceptance.

## Official scale

The official mode uses all seven pinned files and compares each source with
hash-checked earlier native observations. It records the real FP1, QA and E06
publication, loss of the publication acknowledgement, recovery and `no_change`
retry. PostgreSQL WAL growth, database bytes, elapsed times, callback times and
Python peak RSS are recorded with their measurement scope.

Official assertions independently check source/year crash counts, source metric
totals and the exact QA object set. They do not independently check every official
severity category or known-count field. S0 has the detailed six-row semantic
oracle; do not extend that claim to the full official data.

This is a private full-snapshot test, not a government update or public release.
VIC's restricted policy remains active. A separate official sample run and any
unmeasured performance item must be marked `NOT_RUN`; full input is not renamed
as sample evidence. No performance threshold is invented after the result.
