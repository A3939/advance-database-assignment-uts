# B06 / C02: VIC four-file source review

We checked the four VIC files against team v1.1: [05 sections 1-5 and 7](../../../F/ARSIA-Team-Handoff/05-来源与映射说明.md) and [04 sections 2-3](../../../F/ARSIA-Team-Handoff/04-团队分工与验收.md). B added the Person/Node findings on 2026-09-18 (Sydney); the API receipts use 2026-09-17 UTC. C02 still needs C's review.

**The files do not yet meet the team's compatibility requirements.** The 39 unmatched nonempty Person vehicle references also exist in the current official API. Count differences, category definitions and Node CRS remain unresolved, so the source contract stays `status=draft`, `bundle_confirmed=false`. Original files and earlier receipts are unchanged.

## 1. Files and versions

The [DTP dataset](https://opendata.transport.vic.gov.au/dataset/victoria-road-crash-data) covers reported crashes from police and hospital records. It is published monthly under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), with about seven months' delay; historical records can change.

Saved metadata and download details are in [victoria_package.json](../../../Resources/source/metadata/victoria_package.json) and [resources.json](../../../Resources/source/resources.json). These and the F/ links require the shared course workspace. The SHA256 values below identify our originals, separately from the portal's shorter `hash` field.

| Resource | Original | SHA256 |
|---|---|---|
| T3 / `official_vic_accident` | [vic_accident.csv](../../raw_datasource/vic_accident.csv) | `a148c00601fab10d44368df80492c594123700a7f9e334ff896fd215295e91d9` |
| T4 / `official_vic_vehicle` | [vic_vehicle.csv](../../raw_datasource/vic_vehicle.csv) | `05a7a1b9171abaeb5c188df549dee38edde6e76d5a03553988305a8280dccd12` |
| T5 / `official_vic_person` | [vic_person.csv](../../raw_datasource/vic_person.csv) | `71ca8fec01370e301f282fc83e8f11e4cde16a535ee421cbbb72512ceb7194f9` |
| T6 / `official_vic_node` | [vic_node.csv](../../raw_datasource/vic_node.csv) | `b0bdbec22ac33df66e15cff9b531ba3203320ec5fbe20076a2820b8fec966ed4` |

All use `source_id=official_vic`, UTF-8 CSV, row 1 headers and no worksheet. Their 23/37/14/11 ordered columns are pinned in [native-inputs.json](../../config/native-inputs.json). Parser/locator versions are `csv-native-v1` / `csv-logical-v1`; T3/T4 are crash/unit and T5/T6 are person_raw/node_raw.

Metadata indices `result.resources[0/1/2/4]` identify Accident/Vehicle/Person/Node, including URLs and dictionary `attributes`. Resource UUIDs are unchanged. DTP package `bb77800e-1857-4edc-bf9e-e188437a1c8e` and DataVic mirror `e0880296-585d-47bd-8e72-fc1b2045f53d` point to the same resources.

| Resource | Saved metadata | Live metadata checked on 2026-09-17 UTC |
|---|---|---|
| Accident | Updated 2026-08-10; 2012-01-01 to 2025-12-31 | Updated 2026-09-14; 2012-01-01 to 2026-01-31 |
| Vehicle / Person / Node | Updated 2026-08-10; 2012-01-01 to 2025-12-31 | Same dates and coverage |

The [metadata response](evidence/vic/official-package-2026-09-17.json) and [retrieval receipt](evidence/vic/official-package-retrieval-2026-09-17.json) record URLs, UTC time, SHA256, size and versions. All four dictionaries match the saved metadata. Compare `dataset_last_updated_date`, saved `period_start/end`, and live `reporting_period_start/end` and `update_method`. The page's latest date does not establish a joint release.

Use the descriptive `release_label` “locally saved 2026-08 metadata snapshot”; no official `release_scope` is assigned yet. There is no earlier joint snapshot to check deletions or reduced coverage. Any replacement files must be saved separately and compared. This review downloaded metadata and selected API records, not replacement CSVs.

## 2. Accident definitions

References below are from the [Accident dictionary](https://opendata.transport.vic.gov.au/dataset/victoria-road-crash-data/resource/20772c1a-8b19-424a-a733-eb84f725f611), `resources[0].attributes`.

| Field / reference | Meaning and use |
|---|---|
| `ACCIDENT_NO` / AT-14411 | Non-NULL crash key. Keep the full text; its embedded year usually refers to record creation, not occurrence. |
| `ACCIDENT_DATE` / AT-14412, listed as `ACCIDENT DATE` | Occurrence date; NULL allowed. Our CSV uses `YYYY-MM-DD`, parsed at day precision under 05. |
| `NO_OF_VEHICLES` / AT-14428 | Includes bicycles; excludes objects, property and toys such as skateboards. This does not prove every Vehicle row counts. |
| `NO_PERSONS_KILLED` / AT-14423 | People killed; maps to `fatality_count`. |
| `NO_PERSONS_INJ_2` / AT-14427 | Seriously injured people. |
| `NO_PERSONS_INJ_3` / AT-14417 | People with other injuries. |
| `NO_PERSONS_NOT_INJ` / AT-14415 | Uninjured people; excluded from casualties. |
| `NO_PERSONS` / AT-14416 | Total participants, including uninjured people; NULL allowed. Reconcile with Person only under a confirmed common scope. |
| `SEVERITY` / AT-14419 | `1` fatal, `2` serious, `3` other injury, `4` non-injury. Only `1` maps to fatal=true; undefined nonempty codes block. |
| `NODE_ID` / AT-14418 | Crash location ID; match observations using both `ACCIDENT_NO` and `NODE_ID`. |

Casualties = `NO_PERSONS_KILLED + NO_PERSONS_INJ_2 + NO_PERSONS_INJ_3`. Unknown components produce NULL; valid zeros stay zero.

The [2024 Statistical Summary](https://www.vic.gov.au/sites/default/files/2025-08/Road-Trauma-in-Victoria-2024-Summary.pdf), printed pages iii/v (PDF 4/6), defines casualties as killed or injured, fatalities as death within 30 days, and serious injury as hospital admission within seven days without death within thirty days. Its section 1.2 uses a different scope/version, so report totals are not expected CSV counts or proof of cross-state comparability.

`ACCIDENT_TIME` may be rounded (AT-14432); our initial model has no exact time-of-day measure. The extra `RMA` column has no entry in the 22-field dictionary and stays in Raw.

## 3. Vehicle definitions

The [Vehicle description and dictionary](https://opendata.transport.vic.gov.au/dataset/victoria-road-crash-data/resource/6d0b21f7-583a-4991-a168-f15a70c13ec4), `resources[1]`, support these rules:

| Item | Definition / remaining limit |
|---|---|
| Keys | `(ACCIDENT_NO, VEHICLE_ID)` is the composite key; many vehicles belong to one crash. AT-7382 makes VEHICLE_ID non-NULL and unique within its crash. |
| Type | AT-7372/AT-7385 define code and description. Keep original text, including `01`/`02`: code → `unit_type_code`, description → `source_extra`. |
| Count scope | Categories include bicycles, horses, rail vehicles, other vehicles and parked trailers. Per-code inclusion rules are incomplete; VIC vehicles cannot inherit NSW traffic-unit scope. |
| `TOTAL_NO_OCCUPANTS` / AT-7386 | Occupants at crash time; NULL allowed. This differs from crash participants and casualties. |
| Missing/category rules | `99` unknown and `18` not applicable remain distinct from blanks and zero. Their count eligibility still needs a rule. |

Dictionary text for `71/72` contains damaged HTML/characters. Code `21` is absent from both saved and current dictionaries, although 454 Vehicle rows label it `Electric Device`. Section 5 compares it with Person role `16`.

## 4. Local coverage and checks

Raw retains every row and original empty string. Match parents against the full Accident file before filtering by occurrence year 2020-2024; children inherit the parent's date. Missing parents are orphans, not out-of-range rows. Blank/whitespace primary keys block. Other blanks, `NA` and `Unknown` need field-specific rules; unconfirmed definitions cannot be bypassed by setting all eligibility flags false.

The [original profile](evidence/vic/local-profile-2026-09-17-final.json) records hashes, headers, native tokens, year/month counts and all 39/5/2/85 anomaly locations (`examples_complete=true`). All source hashes were unchanged before/after scanning, and file sizes match saved metadata.

| Check | Local result |
|---|---|
| Accident / Vehicle / Person / Node rows | 200,352 / 365,470 / 467,730 / 405,918 |
| Blank or duplicate Accident / Vehicle / Person keys | 0 each |
| Vehicle / Person / Node rows without an Accident parent | 0 each |
| Accident dates | All parse as `YYYY-MM-DD`; 2012-01-01 to 2025-12-31, all 168 months present |
| 2020 / 2021 / 2022 / 2023 / 2024 accidents | 12,170 / 14,013 / 15,043 / 15,558 / 15,386; total 72,170. Other 128,182 remain in Raw. |
| Six declared count fields | Nonnegative integers, no blanks; the four injury components sum to NO_PERSONS in every Accident row |
| Severity `1/2/3/4` | 3,352 / 72,054 / 124,942 / 4. Keep the four non-injury crashes despite the portal's injury-focused introduction. |
| Vehicle categories | 29 tokens, including unlisted `21` |

Sections 5-7 explain the anomalies and compare full-file results with the default years. These are source-file checks, not executed database QA.

## 5. Person: references and counts

The [Person description](https://opendata.transport.vic.gov.au/dataset/victoria-road-crash-data/resource/60c8fc0c-2806-40f3-bb33-5c52691120e8), `resources[2]`, defines a many-to-one Accident relationship and key `(ACCIDENT_NO, PERSON_ID)`. AT-7290/7299/7298 define crash/person/vehicle identifiers. Match vehicles on the full accident/vehicle key within the same source and release.

AT-7297/7291 derive road-user role from person status and vehicle type; AT-7295 distinguishes seating `NA` (not applicable) from `NK` (not known). None gives a rule allowing empty VEHICLE_ID. AT-7299 describes letter IDs for drivers, but 225 type-2 drivers have numeric IDs locally, so ID format cannot determine role.

### References observed in the files

Full cases and locators are in the [Person/Node local review](evidence/vic/person-node-local-review-2026-09-17.json), under `person`.

| Observation | Full file | 2020-2024 | Detail |
|---|---:|---:|---|
| Empty VEHICLE_ID, pedestrian `1` | 18,752 | 6,186 | All seating NA |
| Empty VEHICLE_ID, unknown role `9` | 24 | 6 | Full-file seating LF:11, LR:5, NA:8; all six in scope are NA |
| Empty VEHICLE_ID, other roles | 0 | 0 | Does not establish an official nullability rule |
| Nonempty unmatched VEHICLE_ID | 39 | 39 | Drivers `2`:15, bicyclists `6`:15, motorcyclists `4`:4, passengers `3`:2, unknown `9`:3 |

The 18,776 empty references need separate treatment from unmatched nonempty ones. Pedestrian/NA is a plausible valid non-association, but remains a proposed rule. The 24 unknown-role cases still need an explanation, especially LF/LR. Examples: `T20180012395`, Person `csv:28458`, LF; `T20240001048`, `csv:33594`, NA. All are listed in `person.blank_nonpedestrians`. Another 31 pedestrians have matching nonempty references, which must be preserved.

The 39 unmatched references affect 39 crashes: 11 serious and 28 other injuries. Three crashes have no Vehicle rows; the other 36 lack the referenced vehicle key. Example: `T20240016732`, Person `csv:24271`, person `01` references missing vehicle B. Every case's vehicles, people and locators are in `person.unmatched_crash_context`. All 39 persist in the API; neither pedestrian rules nor year filtering explains them. Under 05 section 4 they block, without blanking references or inventing vehicles.

### Person totals

AT-14416 covers all participants; Person INJ_LEVEL includes `1/2/3/4` (AT-7293), including uninjured people. These support total/component comparisons, but do not guarantee complete publication of every uninjured participant.

Only two local crashes differ in Person totals or injury components. Each declares two people—one other injury and one uninjured—but has one injured Person row. Fatal/serious/other injury components match; one uninjured person is absent relative to Accident. All totals and components reconcile in 2020-2024.

| Crash / Accident locator | Detail |
|---|---|
| `T20150023069`, `csv:63102`, 2015-11-07 | Person `csv:294959`: injured pedestrian. Vehicle A, `csv:200364`: one occupant, no linked Person. |
| `T20150025312`, `csv:130238`, 2015-12-04 | Person `csv:54095`: injured bicyclist A/A. Bicycle A and station wagon B each declare one occupant; B has no Person. |

Missing uninjured occupant detail is a possible explanation, not a confirmed exclusion rule. Both have `POLICE_ATTEND=2` (No), without evidence that this caused the gaps. Both discrepancies persist in the API. Person contains many uninjured rows, so it does not generally exclude them. Do not add people or turn these two exceptions into an allowed tolerance.

### Vehicle 21 and Person 16

Person contains 425 rows labelled `16 / E-scooter Rider` (129 in scope), while both dictionaries list only roles 1-9. All references match; linked Vehicle types are `21`:412, `13`:7, `12`:2, `10`:3, `17`:1.

The 454 type-21 vehicles (149 in scope) have 475 linked **people**: role `16`:412, `9`:62, `4`:1. The codes are associated but not interchangeable. Their published labels are known; full definitions, historical recoding and count eligibility remain undocumented in the sources checked.

## 6. Node: observations and CRS

The [Node description](https://opendata.transport.vic.gov.au/dataset/victoria-road-crash-data/resource/466fd3b5-201b-42b5-b10d-e926324fa215), `resources[4]`, calls NODE_ID a primary location key shared by multiple accidents. AT-7281 describes assigning a new ID for a new location. It does not explain the crash-specific export or establish CSV uniqueness.

### Repeated observations

There are 143,808 distinct Node IDs; 15,642 appear under multiple accidents. Every row has a parent Accident and matches its Node ID. The `(ACCIDENT_NO, NODE_ID)` matching key has 200,267 groups, including 199,359 repeated groups:

| Rows per group | 1 | 2 | 4 | 6 |
|---|---:|---:|---:|---:|
| Groups | 908 | 196,222 | 3,128 | 9 |

There are 205,651 extra observations, including 202,505 exact duplicates across all 11 columns. In 3,137 groups only DEG_URBAN_NAME varies. Each group's coordinate pairs are equal as exact decimals; no non-finite, out-of-range or conflicting pairs were found.

Example: `T20140014662` / Node `273173`, at `csv:140`, `csv:1430`, `csv:398965`, `csv:400622`. MELB_URBAN and MELBOURNE_CBD each occur twice, all at `(-37.81004, 144.96231)`. The API repeats the same payloads; all five saved example groups match, including multiplicity.

A source location key can coexist with repeated export observations. Urban-classification joins could explain some repetition, but no export query or release note establishes the cause of either the differing classifications or exact duplicates.

Under 05, keep every observation and compare unrounded decimal coordinates. A map location requires all matching observations to be valid and complete, one exact coordinate pair, and supported CRS/relationships. Only then select a representative by file hash, parser version and numeric locator for `location_record_id`. Missing, conflicting, partly invalid or unconfirmed locations stay map-ineligible with reasons; keep the crash and do not average or take the first pair.

### Missing matches

All 85 missing matches use negative Accident Node IDs: `-1`:48, `-10`:36, `-3`:1. None appears in Node, and all 85 still return no Node rows in the API. These look like unresolved-location markers, but their official meanings are unknown. They are missing candidates, not Node rows with orphan Accident parents; keep the crashes and handle location availability under QA07.

All seven in-scope cases use `-1`: `T20200004272`, `T20210006755`, `T20210009023`, `T20210011134`, `T20210011215`, `T20220001453`, `T20220007387`. Full locators are in `node.missing_matches`. Do not create negative-ID Node records or replacement coordinates.

### CRS evidence and limit

Node AT-7280/7277 describes latitude/longitude without a datum. AT-7283/7282 calls AMG_X/Y projected coordinates and defines zero for unknown locations; this does not define latitude/longitude missing values.

The current [flat crash resource](https://opendata.transport.vic.gov.au/dataset/victoria-road-crash-data/resource/5df1f373-0c90-48f5-80e1-7b2a35507134) combines attributes from the crash CSVs and explicitly declares `geographic_coordinate_system=WGS84`; AT-14381/14389 labels its projected fields VicGrid94. The shared August metadata and the Node resource have no such CRS declaration.

For 12 crashes—the seven count cases plus five repeated-Node examples—all matching local Node latitude/longitude pairs equal the flat API values as decimals. Node AMG_X/Y also equals flat VICGRID_X/Y numerically. This supports investigating common coordinate lineage, but proves neither a transformation nor the complete August Node datum. The projected-field labels also disagree.

We still need a release-specific Node CRS statement or documented lineage/coordinate operation to WGS84. No EPSG code has been assigned. Valid coordinate numbers alone cannot establish map eligibility, so the seven missing matches are not the only location issue.

## 7. API comparison and compatibility

The [API receipt](evidence/vic/person-node-api-check-2026-09-17.json) saves exact responses, URLs/filters, UTC times, sizes and hashes. The [offline comparison](evidence/vic/person-node-comparison-2026-09-17.json) compares all native fields and multiplicities, treating API null as CSV empty text only for comparison. API `_id` is separate from a CSV locator.

The 39 reference cases and seven count cases cover 43 accidents, 49 vehicles and 89 people. Selected Vehicle/Person payloads match locally. Node queries cover 91 accidents: 85 missing, five repeated groups and one person-count case. All 22 returned Node payloads match. Each filtered response was complete; the current full release was not validated.

One of the 43 Accident records changed: `T20250032463`, local `csv:145593`, API `_id=145801`. September changes DAY_OF_WEEK 4→5, NO_PERSONS_INJ_2 0→1, NO_PERSONS_INJ_3 1→0 and SEVERITY 3→2. Person still lists the passenger's injury as 3. This confirms a historical revision and a new component disagreement between current resources. It is outside 2020-2024 and does not explain the 39 references.

All five vehicle-count differences persist in the API:

| Crash / Accident locator | Declared / native vehicles | Detail |
|---|---:|---|
| `T20210022607` / `csv:183745` | 1 / 0 | Person references A; no Vehicle row. |
| `T20210022263` / `csv:184156` | 1 / 0 | Same pattern. |
| `T20230009098` / `csv:148970` | 1 / 0 | Same pattern. These three are in scope and overlap the 39 unmatched references. |
| `T20250032463` / `csv:145593` | 1 / 2 | Station wagon A plus type-19 parked trailer B (`csv:355100`), zero occupants. A count-scope exclusion is possible but unproven. |
| `T20250030921` / `csv:195478` | 2 / 3 | Taxi A, motor scooter B, type-21 device C (`csv:311204`). A/B link to four people; C declares one occupant with no Person. Classification, missing detail or update timing could explain this; none is confirmed. |

| Measure | Full local files | 2020-2024 |
|---|---:|---:|
| Accident rows | 200,352 | 72,170 |
| Nonempty unmatched Person vehicle references | 39 | 39 |
| Vehicle count differences | 5 | 3 |
| Person total / injury-component difference cases | 2 / 2 | 0 / 0 |
| Unknown-role empty vehicle references | 24 | 6 |
| Vehicle `21` / Person `16` rows | 454 / 425 | 149 / 129 |
| Accidents without matching Node | 85 | 7 |
| Node rows / conflicting groups / invalid coordinates | 405,918 / 0 / 0 | 145,709 / 0 / 0 |

Shared August dates suggest a common release, but do not prove a consistent snapshot. API checks show the anomalies are in the published data, not introduced by our reader or year filter. We have not identified a compatible replacement or established whether collection, export or publication caused the gaps.

Under the team contract, the 39 references block QA04; missing definitions/count scope affect QA05, and draft or unconfirmed inputs cannot pass QA01. Repeated Node observations are allowed; correctly isolated locations can be QA07 limited. These are contract implications, not database QA results. They apply to the default years as well as the full files.

## 8. What C still needs to review

C can use the existing cases and evidence directly. The remaining questions are:

| Question | Missing evidence |
|---|---|
| Which empty Person references are valid? | Role/seating-specific rules, especially for the 24 unknown-role cases. Pedestrian/NA remains a candidate rule. |
| Why are vehicle targets and uninjured details missing? | An explanation for the 39 references and two Person differences, or a corrected compatible release. |
| Which vehicle records count? | Inclusion rules for trailers/electric devices and other categories, plus full Vehicle 21 / Person 16 definitions. |
| Why does Node repeat, and what do negative IDs mean? | Export/schema details and definitions for -1/-10/-3. |
| Is this Node release WGS84? | Node-specific CRS or documented coordinate lineage/operation; 12 matching examples are supporting evidence only. |

We checked portal dictionaries, metadata and official-site searches. The [old CrashStats guide](https://data.vicroads.vic.gov.au/metadata/crashstats_user_guide_and_appendices.pdf) failed hostname resolution; the [legacy extract page](https://discover.data.vic.gov.au/dataset/crash-stats-data-extract) had a redirect loop. Neither was used as evidence. [Research notes](evidence/vic/person-node-research-2026-09-18.json) record the search limits and separate official statements, file observations and possible explanations.

C reviews Person/Node semantics and the combined source contract; D reviews analytical meaning. Neither has signed off through this investigation, and no publisher, teacher or teammate was contacted.

## 9. Evidence and reproduction

Receipts retain source/code hashes, full case lists and locators. `csv:N` means the parser's logical record after the header, not a text-editor line; use it with the pinned hash and parser version.

Run from the repository root with fresh outputs:

```sh
review_dir=$(mktemp -d /tmp/arsia-vic-review.XXXXXX)
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/profile_vic_inputs.py \
  --output "$review_dir/profile.json"
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/review_vic_links.py \
  --output "$review_dir/local-review.json"
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/compare_vic_evidence.py \
  --review docs/sources/evidence/vic/person-node-local-review-2026-09-17.json \
  --api-evidence docs/sources/evidence/vic/person-node-api-check-2026-09-17.json \
  --output "$review_dir/api-comparison.json"
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
```

The [original profiler](../../tools/profile_vic_inputs.py) and follow-up tools refuse existing output files. The comparison deliberately uses the saved local receipt because its hash is bound to the API selection; it checks the CSVs and saved response hashes offline. To fetch a case again, use `requests[].url` with `curl --fail --location`, save separately and record UTC time/SHA256. New responses may differ.

[Recorded validation](evidence/vic/person-node-validation-2026-09-18.json): 153 tests passed, including seven new cases covering reference/count errors, duplicates versus decimal equality, invalid/conflicting coordinates, input preservation, hash/key failures and damaged/incomplete API receipts. These test the investigation tools, not C's SQL QA. Receipt hashes refer to files at that run, before this wording-only edit.
