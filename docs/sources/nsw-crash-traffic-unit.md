# A04: NSW Crash and Traffic Unit source confirmation

Role A has confirmed this source decision under A04. The machine-readable contract is [official-nsw-v1.json](../../config/official-nsw-v1.json), the local scan is [nsw-source-validation-2026-09-23.json](evidence/nsw/nsw-source-validation-2026-09-23.json), and the downstream handoff is [nsw-source-confirmation-2026-09-23.json](evidence/nsw/nsw-source-confirmation-2026-09-23.json). `reviewed_by` is intentionally null because no Role C review is claimed or required for A04 completion.

## Selected official snapshot

| Item | Decision |
|---|---|
| Source | `official_nsw`; publisher Transport for NSW |
| Release | `nsw_pinned_2020_2024_v1`; “NSW 2020–2024 Crash/TU, pinned local snapshot” |
| Crash | `official_nsw_crash`; XLSX `Sheet1`; 92,189 rows; SHA256 `7345189f017d9c842429674ecf2196cee728de46c0572ce2a85220f9bef49aa9` |
| Traffic Unit | `official_nsw_traffic_unit`; XLSX `Export`; 170,962 rows; SHA256 `95349666f63952c580edb08973a8ac80be39db98ba289ec8533d61feb6d55f1b` |
| Licence | Creative Commons Attribution / `cc-by`; the portal does not state a version, so this review does not claim 4.0 |
| Official release ID | None stated by the publisher; the descriptive label and exact hashes identify this local snapshot |

The [official dataset page](https://www.data.nsw.gov.au/data/dataset/2-nsw-crash-data) places both 2020–2024 resources in the same package. This, the manual's Crash ID relationship, and the complete local reconciliation support `bundle_confirmed=true`. Hashes, joinability or download dates alone would not be enough.

## Keys, parent and coverage

- Crash key: exact text `Crash ID`; 0 blank keys and 0 duplicate key rows.
- Traffic Unit key: exact ordered text pair `Crash ID`, `Traffic unit ID`; parent is Crash `Crash ID`; 0 blank components, 0 duplicate pairs and 0 orphan rows.
- `No. of traffic units involved` reconciles with child rows for every Crash: 0 differences.
- Occurrence time uses `Year of crash` and `Month of crash`, not `Reporting year`. There are 488 rows where the two year fields differ.
- The analysis scope is occurrence years 2020–2024 and all 60 year-months are observed. The 107 Crash rows and 215 child rows whose occurrence year is 2019 stay in Raw only.

## Measures and categories

`Degree of crash - detailed` defines the seven registered states: Fatal, Serious Injury, Moderate Injury, Minor/Other Injury, Uncategorised Injury, Non-casualty (towaway), and `__MISSING__`. Uncategorised Injury is retained even though it is not observed in this snapshot. A new nonempty token is undefined and must block; it cannot be silently treated as nonfatal or missing.

- Fatal crash: `Degree of crash = Fatal`.
- Fatalities: `No. killed`.
- Casualties: `No. killed + No. seriously injured + No. moderately injured + No. minor-other injured`.
- Declared traffic units are a relationship check, not a casualty measure.

The 2020–2024 native observations are 92,082 crashes, 170,747 traffic units, 1,388 fatal crashes, 1,507 deaths and 78,154 casualties. They are reconciliation expectations, not proof that the database projection or publication has run.

All eleven observed `TU type group` values are frozen in the JSON contract. Pedestrians are directly involved traffic units. `Other or unknown` is a known publisher category, not a missing token. NSW traffic-unit counts must not be labelled motor-vehicle counts or pooled with VIC vehicles.

## Location, population and attribution limits

All 92,189 Crash rows contain latitude and longitude text, but no field-specific datum evidence was found for these exact files. Therefore `map_enabled=false` and the reason is `crs_unconfirmed`. Plausible coordinates and a mainland bounding box are not CRS proof, and island records must be preserved.

The data describes a revisable reported snapshot of police-reported public-road crashes involving a moving road vehicle and death, injury or motor-vehicle towaway. It does not claim all real crashes or final historical counts. Outputs must show Transport for NSW attribution, the pinned-snapshot label and a derived-processing note.

## Confirmation and Role C handoff

Role A confirms the exact hashes, inputs, keys, pairing basis, time rules, severity and count definitions, TU categories and no-map rule. The two source contracts are versioned `nsw-crash-contract-v1` and `nsw-traffic-unit-contract-v1`; their mappings are `nsw-crash-projection-v1` and `nsw-traffic-unit-projection-v1`; severity uses `nsw-crash-severity-v1`. These are ARSIA project rule versions, not publisher release versions.

- both contracts have `status=confirmed`;
- `confirmed_by` is `Role A / JJ`;
- `reviewed_by` remains `null` because no C review is claimed;
- `contract_confirmed` and `bundle_confirmed` are true;
- there are no unresolved blockers to the enabled NSW crash and traffic-unit products.

Role C receives these decisions as projection and QA inputs. C must keep maps disabled, preserve all Raw rows and report any implementation conflict rather than silently changing the source semantics. Database projection, downstream QA and publication remain separate tasks; their absence does not make the A04 source decision incomplete.
