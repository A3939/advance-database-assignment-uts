# B07: S0 native input files

S0 follows team v1.1 [04 sections 4-5](../../F/ARSIA-Team-Handoff/04-团队分工与验收.md#4-共用手算样例s0设计预期尚未执行) and the headers in [05 section 7](../../F/ARSIA-Team-Handoff/05-来源与映射说明.md#7-本地快照与完整表头). These references are in the shared course workspace. The seven files contain 197 columns and 19 records, ready for the existing readers. `create_demo_inputs.py` is a separate reader demo.

## Files and usage

- Edit sample values and definitions in `config/synthetic-s0.json`.
- Generate files, intake configuration and the fixture contract with `tools/create_s0_inputs.py`.
- Use the shared baseline in `tests/fixtures/s0/`.

Each generated directory has `config.json` for `arsia_ingest` and `contract.json` for keys, counts, coverage, locations and the selected variant. The full manifest and FP1 call remain B09 work.

Run this from the repository root:

```bash
.venv/bin/python -m arsia_ingest --config tests/fixtures/s0/config.json --output artifacts/s0-intake
```

To regenerate the files, choose a new or empty directory. The generator refuses to overwrite existing files:

```bash
.venv/bin/python tools/create_s0_inputs.py --output artifacts/s0-inputs
.venv/bin/python tools/create_s0_inputs.py --output artifacts/s0-person-99 --variant person_vehicle_99
.venv/bin/python -m arsia_ingest --config artifacts/s0-person-99/config.json --output artifacts/s0-person-99-intake
```

`create_s0(output: Path, variant: str = "s0") -> Path` returns the generated `config.json` path. Each call starts from the baseline, so variants do not accumulate changes.

XLSX files use fixed document timestamps and ZIP metadata; CSV uses a UTF-8 BOM and CRLF. Bytes and hashes repeat with the same Python, openpyxl and compression library versions. Recheck after dependency upgrades. The existing configuration supplies headers, worksheet names and reading formats; sample values and classifications are synthetic.

## What S0 contains

The S1-S7 aliases in 04 use the repository's existing resource IDs:

| Alias in 04 | resource_id | Format and sheet / columns / rows |
|---|---|---|
| S1 | `syn_nsw_crash` | XLSX Sheet1 / 50 / 2 |
| S2 | `syn_nsw_traffic_unit` | XLSX Export / 10 / 3 |
| S3 | `syn_vic_accident` | CSV / 23 / 2 |
| S4 | `syn_vic_vehicle` | CSV / 37 / 3 |
| S5 | `syn_vic_person` | CSV / 14 / 3 |
| S6 | `syn_vic_node` | CSV / 11 / 4 |
| S7 | `syn_qld_crash` | CSV / 52 / 2 |

All sources use text crash IDs `0001/0002` and unit IDs `01/02`. With `dataset_kind=synthetic`, `syn_` source/resource IDs, `release_scope=s0` and release label `Synthetic S0 v1`, the fixture is kept separate from official inputs and their approval status.

The `syn-1` categories are F (fatal), I and N (nonfatal), and `__MISSING__` (unknown). Undefined nonempty categories block processing. These fictional person-count definitions are comparable across sources, with deaths included in casualties. Coverage is defined as every month in 2020-2024 for S0 only.

| Crash | Date | Category | Deaths / casualties | Units | Location |
|---|---|---|---|---:|---|
| N1 | 2020-01, month precision | F | 2 / 3 | 2 | -33.86, 151.20 |
| N2 | 2020, year precision | Native blank | Unknown / unknown | 1 | Missing |
| V1 | 2020-01-15 | F | 1 / 2 | 1 | Two equivalent Node observations |
| V2 | 2021-02-15 | I | 0 / 1 | 2 | Two conflicting Node observations |
| Q1 | 2020-01, month precision | I | 0 / 1 | No unit detail | -27.47, 153.02 |
| Q2 | 2021-02, month precision | N | 0 / 0 | No unit detail | -27.50, 153.05 |

All three indicator eligibility flags should be false for N2 and true for the other crashes. NSW has three CAR units under `synthetic_traffic_unit`; VIC has three CAR vehicles under `synthetic_vehicle`. QLD category counts stay on the crash row without creating unit records.

V1 persons P1/P2 both refer to vehicle 01. V2 person P1 has a blank vehicle reference, allowed by the fixture contract. Changing it to nonexistent vehicle 99 should block processing. VIC declares 1/2 vehicles and 2/1 people, matching the detail rows. Unused Person injury columns provide no injury information.

Keep all four Node observations. V1's `-37.8,144.9` and `-37.8000,144.9000` are equal as exact decimals; the first observation should supply its representative location. V2's coordinates conflict, so selecting the first or averaging them is invalid. The invented coordinates are defined as EPSG:4326 and need no transformation. Official CRS confirmation remains separate.

Contracts list `used_fields`; generated contracts also list `unused_fields`. Unused columns remain empty strings in CSV and NULL in XLSX. Python preserves native values; SQL handles business keys, date eligibility, casualty sums and Node decisions.

## Reproducible variants

Every variant has a seven-resource configuration; `missing_file` omits Node deliberately. `expected_prepare` and `expected_later_check` are expectations. `test_status=NOT_RUN` refers to downstream business acceptance.

| `--variant` | Change from S0 | Expected native preparation | Expected later check |
|---|---|---|---|
| `s0` | Baseline | prepared | Check against 04 section 4. |
| `missing_file` | Omit Node while the configuration still requires it. | failed | No publication. |
| `bad_header` | Rename Accident's first header and update the expected hash to match the changed bytes. | failed | No publication. |
| `bad_hash` | Set Accident's expected hash to all zeros; leave the file unchanged. | failed | No publication. |
| `duplicate_crash` | Append N1 at a new row locator. | prepared | QA03 blocks the duplicate business key. |
| `orphan_unit` | Change the parent crash number of V2 vehicle 02 to 9999. | prepared | QA03/04 blocks the orphan. |
| `person_vehicle_99` | Change V2 Person's empty vehicle reference to 99. | prepared | QA04 blocks. |
| `invalid_date` | Change V2's date to 2021-02-30. | prepared | QA03 blocks. |
| `negative_count` | Change V1's death count to -1. | prepared | QA03 blocks. |
| `undefined_category` | Change V2's category to the undefined X. | prepared | QA05 blocks. |
| `invalid_coordinate` | Change Q1's latitude to -91. | prepared | Keep all 6 crashes; Q1 loses map eligibility and QA07 is limited. |
| `unknown_crs` | Leave files unchanged and remove the QLD CRS declaration from the contract. | prepared | Q1/Q2 lose map eligibility and QA07 is limited. |
| `revised_n1` | Change N1 deaths from 2 to 3, keeping the other components at 1/0/0. Update the release label and correction note. | prepared | New batch: 4 deaths, 8 casualties, 2 fatal crashes. The old batch keeps its original values. |
| `delete_q2` | Remove Q2 and update the release label and deletion note. | prepared | New batch: 5 crashes. The previous successful batch still contains Q2. |
| `delete_q2_unexplained` | Remove Q2 and update the release label, but omit the deletion note. | prepared | QA01 blocks the unexplained reduction. |

Business-error variants should reach `prepared` with their values intact for SQL checks. An out-of-range coordinate must not cause the reader to drop the crash.

Later module tests cover same-locator replay with matching or changed payloads (AT02), wrong batch or release scope (AT03), fact tampering (AT06), forced map eligibility (AT07), locks, transactions and commit failures. These need a database or call context. Fourth-state S8 (AT15) is also later work.

Expected pipeline results are 19 Raw records, 6 crashes, 6 actual units, 2 fatal crashes, 3 deaths, 7 casualties, 4 map points and 63 QA rows. B07 supplies the inputs; an actual pipeline run and E's independent checks must verify these results.
