# B06: VIC Accident / Vehicle source review

B reviewed the files on 2026-09-17 against team v1.1: [05 sections 1-5 and 7](../../../F/ARSIA-Team-Handoff/05-来源与映射说明.md) and [04 sections 2-3](../../../F/ARSIA-Team-Handoff/04-团队分工与验收.md). These notes support C02 and later QA01/QA05 checks. C02 is pending; the original files are unchanged.

**The four local files are not ready for an official release.** Checks found 39 unmatched nonempty Person vehicle references, declared vehicle/person count differences, and undocumented vehicle type `21`. Most field definitions have official support, but the source contract remains `status=draft` with `bundle_confirmed=false`.

## 1. Files and versions

The Victoria Department of Transport and Planning publishes the data under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The [dataset page](https://opendata.transport.vic.gov.au/dataset/victoria-road-crash-data) describes police and hospital records, updated monthly with about seven months' delay. Historical records may be revised. Coverage is limited to reported crashes.

Saved metadata is in [victoria_package.json](../../../Resources/source/metadata/victoria_package.json), with download details in [resources.json](../../../Resources/source/resources.json). These links and the F/ references above need the shared course workspace. The SHA256 values below identify the v1.1 local originals; they are separate from the portal's shorter `hash` field.

| Contract resource / current resource_id | Original file | SHA256 |
|---|---|---|
| T3 / `official_vic_accident` | [vic_accident.csv](../../raw_datasource/vic_accident.csv) | `a148c00601fab10d44368df80492c594123700a7f9e334ff896fd215295e91d9` |
| T4 / `official_vic_vehicle` | [vic_vehicle.csv](../../raw_datasource/vic_vehicle.csv) | `05a7a1b9171abaeb5c188df549dee38edde6e76d5a03553988305a8280dccd12` |
| T5 / `official_vic_person` | [vic_person.csv](../../raw_datasource/vic_person.csv) | `71ca8fec01370e301f282fc83e8f11e4cde16a535ee421cbbb72512ceb7194f9` |
| T6 / `official_vic_node` | [vic_node.csv](../../raw_datasource/vic_node.csv) | `b0bdbec22ac33df66e15cff9b531ba3203320ec5fbe20076a2820b8fec966ed4` |

All four resources use `source_id=official_vic`, UTF-8 CSV, row 1 headers and no worksheet. They have 23/37/14/11 columns; ordered headers are in [native-inputs.json](../../config/native-inputs.json). Parser and locator versions are `csv-native-v1` and `csv-logical-v1`. T3 is crash, T4 is unit, and T5/T6 are person_raw/node_raw.

Publisher details and URLs are in the saved metadata. For T3/T4/T5/T6, `result.resources[i].url` uses indices 0/1/2/4. Resource UUIDs are unchanged. The current DTP package is `bb77800e-1857-4edc-bf9e-e188437a1c8e`; the DataVic mirror is `e0880296-585d-47bd-8e72-fc1b2045f53d`. Both entries point to the same DTP resources.

The review fetched metadata only. The [API response](evidence/vic/official-package-2026-09-17.json) and [retrieval receipt](evidence/vic/official-package-retrieval-2026-09-17.json) retain the URL, UTC time, response SHA256, byte count and resource versions. All four resources' `attributes` match the saved metadata.

| Resource | Saved metadata | Live metadata retrieved on 2026-09-17 |
|---|---|---|
| Accident | Updated 2026-08-10; covers 2012-01-01 to 2025-12-31 | Updated 2026-09-14; covers 2012-01-01 to 2026-01-31 |
| Vehicle / Person / Node | Updated 2026-08-10; covers 2012-01-01 to 2025-12-31 | Still dated 2026-08-10; covers 2012-01-01 to 2025-12-31 |

Compare the saved `result.resources[i].dataset_last_updated_date / period_start / period_end` with the live `dataset_last_updated_date / reporting_period_start / reporting_period_end / update_method` at the same indices. Only Accident shows a September update. The page's latest date cannot establish a shared version for all four CSVs or identify the older local files.

A descriptive `release_label` is "locally saved 2026-08 metadata snapshot". No official `release_scope` is assigned while compatibility is unconfirmed. There is no earlier comparable joint snapshot to check for deletions or reduced coverage. Store replacement inputs separately and compare their coverage and counts with this record.

## 2. Accident field definitions

The `AT-*` references come from decoded `result.resources[0].attributes` in the [Accident data dictionary](https://opendata.transport.vic.gov.au/dataset/victoria-road-crash-data/resource/20772c1a-8b19-424a-a733-eb84f725f611).

| Field / official entry | Published meaning | Project use |
|---|---|---|
| `ACCIDENT_NO` / AT-14411 | Non-NULL crash primary key; the year in the number usually refers to when the record was created in the system | Keep the full text. Derive occurrence year from the date. |
| `ACCIDENT_DATE` / AT-14412 (listed as `ACCIDENT DATE`) | Crash occurrence date, with NULL allowed; the description discusses database and application display formats | Check the actual CSV format separately. Parse `YYYY-MM-DD` at day precision under 05, leaving the original file unchanged. |
| `NO_OF_VEHICLES` / AT-14428 | Vehicles involved, including bicycles but excluding objects, property and toys such as skateboards | Reconcile counts using the published scope. The definition alone does not establish that every Vehicle row should be counted. |
| `NO_PERSONS_KILLED` / AT-14423 | People killed in the crash | Maps to `fatality_count`, measured in people. |
| `NO_PERSONS_INJ_2` / AT-14427 | People seriously injured | Second component of the casualty count. |
| `NO_PERSONS_INJ_3` / AT-14417 | People with other injuries | Third component of the casualty count. |
| `NO_PERSONS_NOT_INJ` / AT-14415 | People who were not injured | Excluded from the casualty count. |
| `NO_PERSONS` / AT-14416 | Total people involved, with NULL allowed | Compare with Person detail under the same scope. This is a participant count. |
| `SEVERITY` / AT-14419 | `1` fatal, `2` serious injury, `3` other injury, `4` non-injury | `1` maps to fatal=true; `2/3/4` map to false. An undefined nonempty code blocks processing. |
| `NODE_ID` / AT-14418 | Node identifier for the crash location | Keep the original text and match Node observations using it with `ACCIDENT_NO`. |

The VIC casualty formula in 05 is supported by these definitions: `NO_PERSONS_KILLED + NO_PERSONS_INJ_2 + NO_PERSONS_INJ_3`. It excludes uninjured people. An unknown component makes the sum NULL; a valid zero stays zero.

The glossary in [Road Trauma in Victoria 2024 Statistical Summary](https://www.vic.gov.au/sites/default/files/2025-08/Road-Trauma-in-Victoria-2024-Summary.pdf), printed pages iii and v (PDF pages 4 and 6), defines casualty as someone killed or injured and fatality as death from crash injuries within 30 days. Serious injury involves hospital admission within seven days without death within thirty days. Section 1.2 uses a different scope and data version from the local CSVs. Its totals cannot serve as expected file counts, and the definitions alone do not establish cross-state comparability.

`ACCIDENT_TIME` may be rounded (AT-14432); the initial model has no exact time-of-day measure. Accident has 23 columns but only 22 dictionary entries. The extra `RMA` column stays in Raw without a mapping.

## 3. Vehicle field definitions

The evidence comes from `result.resources[1].description` and its decoded `attributes`, also available in the [official Vehicle data dictionary](https://opendata.transport.vic.gov.au/dataset/victoria-road-crash-data/resource/6d0b21f7-583a-4991-a168-f15a70c13ec4).

| Item | Evidence and remaining questions |
|---|---|
| Primary and parent keys | The resource description defines `ACCIDENT_NO + VEHICLE_ID` as the primary key, with many vehicles belonging to one crash. AT-7382 defines the vehicle identifier as non-NULL character data. `VEHICLE_ID` is only unique within its crash. |
| Vehicle type | AT-7372/AT-7385 define `VEHICLE_TYPE` and its description. Retain both: the original code text goes to `unit_type_code`, and the description goes to `source_extra`. |
| Statistical scope | Published categories include bicycles, horses, rail vehicles, other vehicles and parked trailers. They need their own scope rather than inheriting the NSW traffic unit definition. The `NO_OF_VEHICLES` rule does not list inclusion rules for each type code. |
| `TOTAL_NO_OCCUPANTS` | AT-7386 counts people in the vehicle at the time of the crash and allows NULL. It is distinct from the total people involved in the crash and from the casualty count. |
| Unknown categories | The dictionary lists `99` (unknown type) and `18` (not applicable). Keep them as separate codes, distinct from blank values or numeric zero. Their count eligibility needs to be defined in the statistical scope. |

Keep leading zeros in codes such as `01` and `02`. The dictionary text for `71/72` contains leftover HTML and damaged characters, which need review before the definitions can be used in code.

There are **454 rows with `VEHICLE_TYPE=21`**, all labelled `Electric Device`. Both dictionaries omit this code. The label leaves its scope and counting rules unresolved, including whether it covers electric scooters or other devices.

## 4. Coverage and checks across the four files

Raw keeps every native row; analysis uses occurrence years 2020-2024. Match parent keys against the full crash file before filtering. Vehicle, Person and Node inherit the matched crash's date. A missing parent is an orphan, not an out-of-range row.

CSV empty strings pass into Raw unchanged; empty or all-whitespace primary keys block processing. NULL is documented for `NO_PERSONS` and `TOTAL_NO_OCCUPANTS`. Other blanks, `NA` or `Unknown` tokens need field-specific rules, including any that appear in later snapshots. Update the contract when these rules change. Unconfirmed definitions must not be bypassed by setting every eligibility flag to false.

C can use the same saved metadata for Person and Node:

- `result.resources[2].description` defines the Person composite key. AT-7293 lists injury codes 1/2/3/4. AT-7298 describes the vehicle identifier but does not say which empty references are valid, so blank references need a separate check from nonempty unmatched ones.
- `result.resources[4].description` names `NODE_ID` as the primary key, while the exported CSV also contains a crash number. This review could not establish which level of the source the description refers to. Under the current 05 contract, `ACCIDENT_NO + NODE_ID` is an observation matching key, with no uniqueness constraint or early deduplication.
- AT-7280/AT-7277 describe latitude and longitude without establishing an EPSG code. CRS remains unconfirmed. C02 still needs to review that basis, empty references, and repeated or conflicting observations.

[local-profile-2026-09-17-final.json](evidence/vic/local-profile-2026-09-17-final.json) records script, configuration and source hashes, headers, year/month distributions, native tokens and anomaly locations. It includes every location for the 39/5/2/85 findings (`examples_complete=true`). Empty vehicle references (18,776) and type 21 have totals, year distributions and sample locations.

All four SHA256 values were unchanged before and after the scan. File sizes also match the saved metadata's `filesize`, confirming that the scan used the registered local bytes.

| Check | Result | Interpretation |
|---|---:|---|
| Accident / Vehicle / Person / Node native rows | 200,352 / 365,470 / 467,730 / 405,918 | All original rows retained; source files unchanged. |
| Empty or duplicate Accident / Vehicle / Person primary keys | 0 for each | The full keys hold in these local files. |
| Vehicle / Person / Node rows without a parent crash | 0 for each | Checked against the full crash file before year filtering. |
| Person rows with an empty vehicle reference | 18,776 | C02 needs to distinguish valid blanks from errors using person types. |
| Person rows with an unmatched nonempty vehicle reference | 39 | Blocks under 05 section 4. Keep the original references; do not invent vehicles or replace them with blanks. |
| Crashes where native Vehicle row count differs from `NO_OF_VEHICLES` | 5 | The comparison counts native rows. The intended statistical scope still needs an explanation, rather than a tolerance of five. |
| Crashes where native Person row count differs from `NO_PERSONS` | 2 | Both declare 2 people but contain 1 Person row. This compares participant totals, not casualties with participants. |
| Node matching-key groups / groups with repeated observations | 200,267 / 199,359 | Repeated groups contain 205,651 extra observations, all retained in Raw. |
| Node groups with conflicting exact coordinates / invalid coordinates | 0 / 0 | Checks cover numeric values and ranges; CRS and map eligibility remain unconfirmed. |
| Crashes with no matching Node observation | 85 | Keep the crashes and apply the location rules in 05. Do not invent Node rows. |

Every Accident date parses as `YYYY-MM-DD`. Dates range from 2012-01-01 to 2025-12-31, with records in all 168 months. Counts for 2020 through 2024 are 12,170 / 14,013 / 15,043 / 15,558 / 15,386, totalling 72,170. The other 128,182 rows remain in Raw, outside the default analysis years. All six declared count fields contain nonnegative integers with no empty strings. The sum of the four person components matches `NO_PERSONS` in every row.

The only severity tokens are `1/2/3/4`, with counts of 3,352 / 72,054 / 124,942 / 4. The four non-injury crashes stay in the data even though the portal introduction focuses on fatal and injury crashes. Vehicle contains 29 type tokens, including the undocumented `21`.

For example, Person locator `csv:24271` is crash `T20240016732`, person `01`, with vehicle reference `B`; that composite vehicle key does not exist. Accident locator `csv:183745`, crash `T20210022607`, declares 1 vehicle but has no Vehicle rows. Both examples affect the default analysis years.

Filtering by the parent's actual occurrence date to 2020-2024 leaves all 39 unmatched nonempty vehicle references, 3 vehicle count differences, 7 crashes without a matching Node, and 149 rows with type `21`. Both person count differences occurred in 2015. These year distributions use `ACCIDENT_DATE`, not the year embedded in the crash number.

These are file checks, not database QA results. Unmatched references and the undefined vehicle code block official approval; declared count differences need a scope explanation or corrected release. Repeated Node observations are allowed. Missing or unconfirmed locations affect map eligibility without removing the crash.

To repeat the scan, run `python tools/profile_vic_inputs.py --output /tmp/vic-profile-new.json` from the repository root. The [script](../../tools/profile_vic_inputs.py) requires a new output filename so earlier receipts are preserved.

## 5. Follow-up with C

| Item | Evidence still needed | Current position |
|---|---|---|
| Compatibility of the local release | Explain the 39 unmatched references and the 5/2 declared count differences. If versions are the cause, obtain a compatible set from the publisher. | Keep `bundle_confirmed=false`. |
| Person / Node | C02 review of empty vehicle references, Node relationships, CRS and the local anomalies. | B's files and findings are available here for C to review. |
| Vehicle counts and new codes | Rules for which categories count towards `NO_OF_VEHICLES`, plus definitions for nonempty codes missing from the dictionary. | B and C can use the same evidence. Undefined categories block under QA05. |
| Final source contract | C reviews the initial mappings, missing-value rules and scope; D reviews their analytical meaning. | The official contract stays draft. Synthetic development can continue. |

B and C can update the contract once the findings are explained or a corrected release is available. No anomaly tolerance has been added.
