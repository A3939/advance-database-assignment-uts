# D01 · Queensland source contract and verification record (draft)

**Version:** `qld-d01-draft-0.1`  
**Reviewed on:** 2026-09-18  
**Owner:** D; **semantic reviewer:** C (pending); **report reviewer:** D (pending)  
**Status:** `draft`. This is an internal source investigation and local file check. It is not approval for official publication or evidence of a successful database run.

## 1. Source and local snapshot

| Item | Verified information and handling |
|---|---|
| Publisher and licence | Queensland Department of Transport and Main Roads; Creative Commons Attribution 4.0. [Official dataset page](https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads). |
| Official resource | [Road crash locations resource and data dictionary](https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads/resource/e88943c0-5968-4972-a15f-38e120d72ec0); resource ID `e88943c0-5968-4972-a15f-38e120d72ec0`. The team handoff document 05 records this original download URL: `https://www.data.qld.gov.au/dataset/f3e0ca94-2d7b-44ee-abef-d6b06e9b0729/resource/e88943c0-5968-4972-a15f-38e120d72ec0/download/_1_crash_locations.csv`. The resource metadata hash is `19a17cdddde8f70e7121e677fcd0cba9`, matching the local file's MD5. The current download has not been independently compared byte for byte. |
| Local original | `raw/qld_crash_locations.csv` inside `raw.zip`; UTF-8 CSV, 52 columns and 415,407 logical data records. File SHA-256: `975be4b02a235d06589de9b486f73bafe22d0f2007f0c07abb84f54cb926c704`; MD5: `19a17cdddde8f70e7121e677fcd0cba9`. |
| Release label and identity scope | **Pending team confirmation.** The official dataset page currently shows version `rqC45037- June 2025` and a last update of 24 April 2026. The local hash matches the official resource metadata. The specific `release_label`, `release_scope` and archive time still need to be recorded and confirmed. Until then, do not merge crash IDs across releases. |
| Native grain and key | The data dictionary describes one row per crash. `Crash_Ref_Number` is a deidentified crash identifier that may change between releases. The local file has no blank or duplicate crash keys. Preserve the key as text; do not convert it to an integer. |
| Observed local coverage | Records with years and months from January 2001 through June 2025 were observed. Only January–June were observed for 2025. Counts for 2020–2024 are 12,147; 13,476; 13,021; 13,622; and 14,358 respectively, totalling 66,624. Observing records does not prove officially guaranteed complete coverage of every month. |
| Target analysis range | The team default is occurrence years 2020–2024, inclusive. Filter on `Crash_Year`. `Crash_Month` provides month precision only; do not invent a crash day. Keep out-of-range source records in raw storage. |

**Identifier-description discrepancy to investigate:** The official data dictionary says the first four digits of the crash ID *currently* identify the crash year, but the first five IDs in the local file are `1`, `2`, `3`, `4` and `5`. The local file's MD5 matches the official resource metadata hash. The reason for this discrepancy is not established. Use `Crash_Year` to determine the occurrence year, preserve `Crash_Ref_Number` as the key text, and do not derive the year from the ID.

## 2. Field semantics and candidate mappings

| Target | Native field and available evidence | D01 handling |
|---|---|---|
| Crash identity | `Crash_Ref_Number`; the [official data dictionary](https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads/resource/e88943c0-5968-4972-a15f-38e120d72ec0) describes it as a unique, deidentified crash identifier that may not persist between releases. | Use source, release scope and the native key together as the identity. Local uniqueness has been checked. |
| Occurrence time | The official definitions of `Crash_Year` and `Crash_Month` are the year and month when the crash occurred. | Convert the year to an integer and map English month names to 1–12 under the contract. Set `occurrence_date=NULL` and `date_precision=month`; do not infer a day. |
| Crash severity | The official five `Crash_Severity` categories are Fatal, Hospitalisation, Medical treatment, Minor injury and Property damage only. Severity reflects the highest severity among units involved in the crash. | Preserve the source category and its definition version. Fatal → fatal crash is a candidate mapping for C to review. Do not directly merge equally named NSW or VIC categories. |
| Fatality count | `Count_Casualty_Fatality`; the official definition includes road users who died within 30 days from injuries sustained in the crash. | Candidate `fatality_count`. Compare definitions with the other states before approving cross-state totals. |
| Casualty count | `Count_Casualty_Total`; the official definition counts road users killed or injured in the crash. The four components are Fatality, Hospitalised, MedicallyTreated and MinorInjury. | Candidate `casualty_count`. In all 415,407 local rows, the four components sum to Total. C must review final eligibility and cross-state comparability. Preserve unknown values as NULL; do not replace them with zero. |
| Unit-category counts | Seven `Count_Unit_*` fields describe counts of participant or vehicle categories within a crash. | Preserve these as native aggregate attributes of the crash row. Do not create individual vehicle or person records from them. |
| Coordinates | `Crash_Latitude` and `Crash_Longitude`; the [official dataset page](https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads) and data dictionary identify the source datum as **GDA2020**. | The source CRS is known. The method for meeting the team's Canonical map requirement of EPSG:4326 remains to be agreed. C must choose and test a transformation or document a decision to exclude QLD map points for now. Preserve source coordinates and do not relabel them as EPSG:4326. Choose the quality reason code during implementation under the agreed contract. |

## 3. Read-only checks of the local file

The original CSV inside `raw.zip` was parsed as UTF-8 using logical CSV records. The source file was not modified.

| Check | Result |
|---|---:|
| Data rows / columns | 415,407 / 52 |
| Blank `Crash_Ref_Number` / duplicate keys in this file | 0 / 0 |
| Rows for 2020–2024 | 66,624 |
| Severity for 2020–2024 | Fatal 1,304; Hospitalisation 31,922; Medical treatment 22,730; Minor injury 10,668; Property damage only 0 |
| Rows where four casualty components differ from Total | 0 |
| Blank or non-integer values in the five casualty fields | 0 |
| Blank latitude / blank longitude | 598 / 598, on the same records; 0 / 0 for 2020–2024 |
| Invalid nonblank coordinates or coordinates outside basic latitude/longitude ranges | 0 |

These checks establish only local parseability and observed values. They do not establish that the official file version is identical, that definitions are comparable, that coordinates have been transformed, that database QA has passed, or that publication is allowed.

## 4. Official coverage and version risks

The [official dataset overview](https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads) says the data come from the RoadCrash database and that records from the most recent 12 months may be preliminary. It also says Queensland Police stopped reporting or recording property-damage-only crashes after 31 December 2010. The absence of Property damage only rows in the local 2020–2024 slice is consistent with that statement, but unfiltered all-crash totals should not be assumed comparable across the three states. The relationship between the website's current reporting cut-offs and update date and the local snapshot still needs to be recorded.

## 5. Open issues and decisions for C's review

1. **Local release identity:** The local MD5 matches the official resource metadata hash, which is strong evidence that they correspond. Record the original download time and archive evidence, and agree on `release_label` and `release_scope`. Do not merge crash keys across releases before this is resolved. A resource page can be updated, so its URL alone is insufficient.
2. **Coordinate handling:** The official source datum is GDA2020. The open issue is how to meet the team's EPSG:4326 map requirement. C should choose and test a transformation or document a decision not to use QLD map points initially. Preserve source coordinates and do not merely change the CRS label. Choose a quality reason code under the agreed implementation contract. The [ICSM technical manual](https://www.icsm.gov.au/sites/default/files/GDA2020%20Technical%20Manual%20V1.8_published_0.pdf) can inform the transformation choice.
3. **Measure comparability:** C should compare QLD's 30-day fatality definition and its four casualty categories with NSW and VIC definitions. Report results by source until a cross-state total is justified.
4. **Coverage declaration:** Decide whether each month in the local 2020–2024 period can be declared completely covered, and how expected snapshot revisions or removals will be handled. Records observed in a month do not prove that zero-crash periods are completely covered.
5. **Missing-value rules:** No blank or non-integer values were observed in the five local casualty fields. This does not establish that the official source has no other missing-value tokens. Block any unregistered token in a new file and add a rule backed by evidence; do not automatically turn it into 0 or NULL. Block newly encountered severity categories and update the definition as well.

**Handoff:** The **QLD official source contract** remains `draft`. Submit the Section 5 issues to C and the relevant owners for review. Change the contract to `confirmed` only after versioned confirmation is recorded. Synthetic development uses a separate fictional contract; completion of D01 does not approve official publication.
