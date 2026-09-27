# Official source decisions

23 September 2026 · Internal implementation plan

This is the shared decision list for all 55 tasks. The user has authorised the
project decisions below. It does not claim publisher approval, separate teammate
signatures, teacher approval or a successful official release.

**Use fixed snapshots, publish source-specific metrics, and disable outputs whose
meaning or location cannot be supported. Keep every original record.** Continue
S0/S8 development without waiting for disabled official features.

The decisions cover the fields and outputs in the current platform contract.
Other native attributes remain in Raw; retaining a field does not approve a new
metric based on it. This avoids making all 197 native columns a prerequisite
for the existing accident reports.

## 1. Authority and current status

Team [02](../../F/ARSIA-Team-Handoff/02-数据库字段字典.md),
[04](../../F/ARSIA-Team-Handoff/04-团队分工与验收.md) and
[05](../../F/ARSIA-Team-Handoff/05-来源与映射说明.md) remain the baseline.
The adopted [VIC decision](role-c/vic-restricted-use-decision.md) and its frozen
policy take precedence only for that profile. This plan fills the remaining
source decisions; it does not overwrite either baseline or historical evidence.

| Area | Decided use | Actual implementation status |
|---|---|---|
| NSW | Pinned Crash/TU pair; occurrence years 2020–2024; source-specific accident, casualty and traffic-unit metrics; no official map | Source facts and local-file checks support the decision. Executable source contracts, SQL mappings and release checks still need integration. |
| VIC | Existing `vic-accident-only-2020-2024-v1`, unchanged | C06 and B09/B11 support exist. Full projection, all applicable QA, report restrictions, FP1 and publication still need joint verification. |
| QLD | Pinned single crash resource; occurrence years 2020–2024; source-specific accident/casualty metrics; no unit detail or official map | Source facts and local-file checks support the decision. Executable source contract, SQL mapping and release checks still need integration. |
| Synthetic | Existing S0 and independent S8, including bad variants | Keep their own definitions and expected results. No official-source approval follows from their success. |

“Official” describes the provenance of a file. A confirmed **project source
contract** describes the permitted use of one pinned version. Neither means
the publisher has certified the project or that its database checks have run.

The previous B09/B11 receipt records 521 passed/16 skipped in its default run
and 686 passed/0 skipped in its combined B/C run. Those are historical results,
including unit tests and a 308-row PostgreSQL excerpt, not a full official build.
This review performed read-only source research and native-file checks; it did
not rerun database tests. See the [review index](sources/evidence/official-decisions-2026-09-23/review-index.json).

## 2. Shared decisions

These IDs are used in the complete task index in section 8.

| ID | Information to keep consistent | Decision |
|---|---|---|
| O01 | Source, resource and input identity | Keep existing source/resource IDs, direct resource URLs, publisher, exact licence wording, file SHA256, ordered headers, parser and locator versions. Use the existing seven files; do not silently replace them with current portal exports. New resources are configuration-driven. |
| O02 | Raw values, grain and business identity | Retain all native fields, empty strings, NULLs, codes and observations. Raw identity stays resource/hash/parser/locator. SQL encodes ordered text business-key components, then source/release/batch namespaces. No numeric ID coercion, invented relations or early Node deduplication. |
| O03 | Snapshot and compatible release | Confirm the specific file combination from source evidence and checks. A team snapshot label is not a publisher release ID. Treat these as full snapshots; any later replacement, deletion or coverage reduction needs exact before/after evidence and a new frozen version. |
| O04 | Time and coverage | Default analysis is occurrence years 2020–2024. Validate full parent files before filtering children. Raw keeps out-of-scope rows. Preserve day/month/year precision; never invent a day or use reporting year as occurrence year. Declared coverage supports a zero result; undeclared coverage is unavailable. |
| O05 | Classification, counts and missing values | Version definitions by source. Separate accidents, fatal accidents, fatalities, casualties, participants and units. Unknown values stay NULL with eligibility/reasons, not zero. Undeclared nonempty categories or malformed core values block. Register valid but unobserved categories and `__MISSING__`. |
| O06 | Relations and known findings | Check complete business keys, parents, nonempty references and applicable count scopes. Preserve known defects; never repair them to pass. Only VIC's exact adopted cases have restricted-use treatment. New cases, changed tokens or changed files are not covered by an error allowance. |
| O07 | Coordinates, CRS and location lineage | No official map in this first release. Preserve candidates in Raw; trusted latitude, longitude, CRS and location-record ID are NULL with map eligibility false and reasons. Re-enable a source only with evidence and a tested versioned mapping. Never relabel coordinates EPSG:4326. |
| O08 | Comparability and synthetic scope | Present official metrics separately by source and definition version. No pooled interstate accident, severity, casualty or unit totals; no common serious-injury mapping. S0/S8 can demonstrate combined results under their explicit synthetic definitions. SA remains synthetic only. |
| O09 | Approval and lifecycle | Distinguish prepared input, source evidence, adopted project rule, implemented mapping, executed QA and published batch. The plan adopts rules, not test outcomes. Official and synthetic remain separate namespaces and current releases. |
| O10 | QA and release conditions | Keep all seven QA groups, concrete objects and batch summaries. Only QA07 may be `limited`. Missing or unexecuted checks never become pass. Preserve VIC's exact amended expectations; all other checks retain the baseline. E independently checks completeness before publication. |
| O11 | Manifest, FP1 and history | Freeze the complete source contracts, enabled/disabled outputs, mappings, categories, QA version, analysis scope and actual code/schema inventory. B calls E's SQL FP1; no Python database fingerprint. Provenance is excluded from FP1, semantic restrictions are not. Never overwrite successful history or old receipts. |
| O12 | Queries and presentation | Read one successful batch per page, with mode, source, snapshot, years, definitions and restrictions visible. Unavailable output is not zero or an ordinary empty result. No candidate-batch reader access. Reports cannot reconstruct business rules or join raw children to count accidents. |
| O13 | Validation and scale claims | Label synthetic tests, native-file scans, real Raw tests, official excerpts and full builds separately. Official full-volume timing, WAL/disk and recovery remain NOT_RUN until measured. Reference existing evidence instead of creating another handoff process. |
| O14 | Course authority and delivery | Keep the current PostgreSQL prototype and three-model plan. Describe actual governance/metadata/lineage/quality work accurately; do not claim Microsoft Fabric deployment. Only the teacher can settle Lab/technology and source-schema acceptance or submission ambiguities. The working plan is in section 7. |

## 3. Source-specific rules

### NSW — A04, A08, C03 and their consumers

Use `official_nsw`, `official_nsw_crash` and `official_nsw_traffic_unit`.
The team release label is **NSW 2020–2024 Crash/TU, pinned local snapshot**;
the new contract's release scope is `nsw_pinned_2020_2024_v1`. This names the
project snapshot, not a new official edition.

The [official package](https://opendata.transport.nsw.gov.au/data/api/3/action/package_show?id=nsw-crash-data)
lists both 2020–2024 resources and explicitly describes their Crash ID join.
The [TfNSW manual](https://opendata.transport.nsw.gov.au/data/dataset/06f9cf3d-0a9d-4098-b0f0-fa9efbdd3921/resource/ceafc11f-49a9-441d-b0b4-f53019ee00e1/download/data-manual-static-for-open-data-20211020.pdf)
pp. 23–25 defines that relationship and traffic-unit scope. Together with the
full local checks, this supports compatibility of this pair. Matching hashes,
dates or successful joins alone would not. The package has no release-version
identifier. The resource label and manual body date differ; both are retained
in the [NSW receipt](sources/evidence/official-decisions-2026-09-23/nsw-review.json).

| ID | Adopted rule | Tasks using it |
|---|---|---|
| N01 | Freeze the existing two files and their 50/10-column headers. Keep the complete Crash→TU relationship. Full checks found 92,189 Crash and 170,962 TU rows, zero duplicate keys, orphan TUs or declared-TU differences. | A04/A08, B09/B11, C03/C10, E05/E09 |
| N02 | Use `Year of crash` and `Month of crash`; date stays NULL with month precision. There are 488 reporting/occurrence-year differences. Exclude the 107 accidents occurring in 2019 and their 215 TUs from analysis, keeping them in Raw. | C03/C08/C09, D02/D05, B09/B11 |
| N03 | Count accidents from unique Crash records, fatal accidents from `Fatal`, deaths from `No. killed`, casualties from the sum of `No. killed`, `No. seriously injured`, `No. moderately injured`, `No. minor-other injured`. An unknown required component makes the sum unknown. No child-join counting. | C03/C08/C10, D03–D06, E05 |
| N04 | Register six detailed severities: `Fatal`, `Serious Injury`, `Moderate Injury`, `Minor/Other Injury`, `Uncategorised Injury`, `Non-casualty (towaway)`, plus `__MISSING__`. Only `Fatal` is fatal; missing remains unknown. `Uncategorised Injury` is valid although absent in this snapshot; it is not a severity inferred from other states. | C08, D02/D06, B09, E05 |
| N05 | TU statistics mean directly involved NSW traffic units, including pedestrians. Register all 11 groups below. Known `Other or unknown` remains a valid group, not a missing value or a newly undefined category. Eligible NSW TU totals are allowed; interstate vehicle totals are not. | A04/A08, C03/C08, D08, E05 |
| N06 | No datum was found for these latitude/longitude fields. Map stays off, with `crs_unconfirmed`; do not infer CRS from plausible coordinates or another TfNSW dataset. Do not reject island observations using a mainland-only bounding box. | C03/C08/C10, D07/D09, E05/E06, DEC05 |
| N07 | Attribute Transport for NSW and preserve the published licence wording `Creative Commons Attribution / cc-by`. Its exact version is not specified in the checked metadata; do not invent “4.0”. Identify derived processing and the snapshot. | A04, B09, D09/D11, E10 |
| N08 | Describe these as police-reported crashes in the pinned export. Do not claim a complete, final count of all real crashes or that future late reports cannot revise history. | B09/B11/B12, D05/D09, E08/E09/E10 |

The 11 TU groups are `Car/car derivative`, `Light truck`, `Heavy rigid truck`,
`Articulated truck`, `Bus`, `Other motor vehicle`, `Motorcycle`, `Pedal cycle`,
`Non-motorised vehicle`, `Pedestrian`, and `Other or unknown`.

**Observed 2020–2024 file totals:** 92,082 accidents, 170,747 TUs, 1,388 fatal
accidents, 1,507 fatalities and 78,154 casualties. All 60 months have records.
These are independent file observations for later reconciliation, not database
or publication results. The manual's inclusion rules and linked injury
definitions remain source-specific; see pp. 2, 4–6 and 23–25.

### VIC — preserve the adopted B06/C02 decision

Use the existing four identities, release scope `vic_pinned_2020_2024_r1`,
profile `vic-accident-only-2020-2024-v1` and QA `team-v1.1-vic-r1`.
The [policy](../config/vic-restricted-use-v1.json),
[input definitions](../config/vic-restricted-inputs-v1.json),
[B source review](sources/vic-accident-vehicle.md) and
[C decision](role-c/vic-restricted-use-decision.md) are the shared evidence.
Their exact cases and hashes remain authoritative; this table is an index.

| ID | Existing decision retained | Tasks using it |
|---|---|---|
| V01 | Keep all four original files, 1,439,470 native records, and 72,170 in-range Accident rows. Allow source-specific trends, native severity, fatal-accident counts, fatalities and casualties directly from Accident. Severity is native `1/2/3/4`; casualties are killed + injury-2 + injury-3, not `NO_PERSONS`. | B06/B09/B11, C02/C04/C08–C10, D03–D06 |
| V02 | Preserve all 39 nonempty unmatched Person→Vehicle references. Exact pedestrian role `1` + seating `NA` + native empty Vehicle ID has the adopted non-association rule; 24 unknown-role empty links stay unresolved, six in scope. Keep valid nonempty pedestrian links. Do not broaden this to whitespace or new tokens. | B06/B09/B11, C02/C06/C10/C11, E05/E06 |
| V03 | Keep declared counts and detail rows separately. The two Person count differences are in 2015; five Vehicle differences include three in scope. Do not fill missing detail or change Accident counts. Detail export completeness is not established. | B06, C02/C06/C10, D04/D08, E05 |
| V04 | Preserve Vehicle `21` and Person `16`; do not equate them. Their definitions and special-vehicle eligibility remain unconfirmed. No Person/Vehicle-derived KPIs, classification or relationship reports under this profile. Keep valid in-range Vehicle projections with `count_eligible=false`; Person stays Raw-only. | C04/C06/C08–C10, A06, D08/D09, E05/E06 |
| V05 | Preserve all Node observations and inspect exact coordinates before any representative selection. There are 85 missing Accident–Node matches, seven in scope. Repetition does not establish duplicate accidents, and labels or joins cannot multiply counts. Negative codes and export multiplicity remain unresolved. | C02/C07/C10/C11, A06, D04/D07 |
| V06 | Node datum is still unconfirmed. The separate flat-crash resource's WGS84 description is not proof for these Node exports. No VIC official map; trusted fields NULL, map false, candidate evidence and reasons retained. | C02/C07/C10, D07/D09, E05/E06 |
| V07 | Preserve `restricted`, the ten unresolved definitions, `bundle_confirmed=false` and `contract_confirmed=false`. Project profile approval is separate. Apply exact amended QA01/04/05 and the normal QA02/03/06/07; no new-anomaly tolerance. | B09/B11, C06/C10, E05/E06 |

No new conclusion about official Person inclusion, nullability, Vehicle/Person
classification, Node datum or compatible publisher release is asserted here.
The project treatment is nevertheless settled. Future answers can support a
new policy version; they do not retroactively change this one.
Keep the existing Department of Transport and Planning attribution, CC BY 4.0
licence, resource URLs and acquisition evidence. Monthly publication and a
newer portal file do not change the approved local snapshot.

### QLD — D01, D10, C05 and their consumers

Use `official_qld` and `official_qld_crash`. The team release label is
**QLD Road crash locations, rqC45037 June 2025, pinned local snapshot**;
the new release scope is `qld_pinned_2020_2024_v1`. The scope names this project's
analysis contract; the native file covers more years. Preserve the publisher's
exact version string `rqC45037- June 2025` separately.

The [resource dictionary](https://www.data.qld.gov.au/dataset/f3e0ca94-2d7b-44ee-abef-d6b06e9b0729/resource/e88943c0-5968-4972-a15f-38e120d72ec0),
[dataset notes](https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads)
and [TMR explanatory notes](https://www.tmr.qld.gov.au/_/media/safety/transport-and-road-statistics/data-request-form-explanatory-notes.pdf?extension=pdf&hash=6AA5335F3AA5D7E6771472FBBC76F719&rev=9abfb681ff3348d487ef6d4f978a486b&sc_lang=en&size=93063)
support the enabled metrics. The live package metadata matches the saved copy;
its resource MD5 matches the local CSV. See the
[QLD receipt](sources/evidence/official-decisions-2026-09-23/qld-review.json).

| ID | Adopted rule | Tasks using it |
|---|---|---|
| Q01 | One 52-column accident resource; no cross-file bundle is required. Freeze its SHA256 and native coverage. Publisher is Queensland Department of Transport and Main Roads; licence CC-BY-4.0. Resource update date is not a promise of finality. | D01/D10, B09/B11, E09/E10 |
| Q02 | Treat `Crash_Ref_Number` as opaque text, using source/release namespaces. The dictionary's year-prefix statement conflicts with IDs such as `1` for 2006 and `2` for 2007. Do not infer year or cross-version identity from the ID. Use `Crash_Year`/`Crash_Month`; date NULL, precision month. | D01, C05/C08/C10, A05, B09/B12 |
| Q03 | Register `Fatal`, `Hospitalisation`, `Medical treatment`, `Minor injury`, `Property damage only`, plus `__MISSING__`. Only `Fatal` is fatal. “Non hospitalised casualty crash” is not a category in this file/dictionary and is not an accepted alias. Keep PDO in definitions even when absent in scope. | C05/C08, D02/D06, B09, E05 |
| Q04 | Fatalities use `Count_Casualty_Fatality`. Casualties use `Count_Casualty_Total`, checked against Fatality + Hospitalised + MedicallyTreated + MinorInjury. Preserve values; unknown required inputs give NULL/ineligible results, while invalid nonempty values, negatives or unexplained differences block. | C05/C08/C10, D03–D06, E05 |
| Q05 | “Hospitalisation” means taken to hospital in the explanatory notes, not verified admission or an interstate-equivalent serious injury. Deaths use the stated 30-day definition. Neither permits automatic harmonisation with NSW/VIC. | C08, D06/D11, E05/E10 |
| Q06 | `Count_Unit_*` are aggregate attributes, not people or vehicle records. Keep them in Raw/source evidence. Generate no QLD Canonical units, fabricated links or extra category fact table. | C05/C10, D08/D10, E04/E07 |
| Q07 | Source CRS is **GDA2020**, explicitly stated for the latitude/longitude fields. Conversion to the required EPSG:4326 target has not been implemented and validated. For this version use no-map semantics with `definition_unconfirmed` and a resolution explaining that the source datum is known but the target operation is unverified. This is a location limitation, not an unknown enabled business definition. | D01, C05/C08/C10, D07/D09, B09, E05/E06 |
| Q08 | Label 2020–2024 results reported casualty crashes in this snapshot. PDO collection ceased in 2011; no PDO rows does not mean no real property-only crashes. Preliminary/revision notices remain visible. Do not use API rows as a complete replacement when its metadata says the datastore may be incomplete. | D01/D05/D06/D09, B09/B11/B12, E09/E10 |

These decisions resolve the policy choices in the existing
[D01 draft](https://github.com/A3939/advance-database-assignment-uts/blob/4ba04d850b9ea5e83acc4df60e0886dddd524dca/docs/source-contracts/D01-QLD-source-contract-draft.md):
release identity, map exclusion, source-specific measures, snapshot coverage
and missing-value treatment. Its observations are reused, not replaced.

**Observed file totals:** 415,407 native rows; 66,624 in 2020–2024, including
1,304 fatal accidents, 1,424 fatalities and 88,609 casualties. All 60 analysis
months have records. There are no empty/duplicate crash keys or casualty-sum
differences. All 598 paired coordinate blanks are outside the analysis years.
Plausible coordinates are not validation of a target-CRS transformation.

For both new NSW/QLD contracts, declare all 60 analysis months as covered by
the selected published export, supported by its coverage metadata and observed
months. A zero then means zero qualifying records **in this snapshot**, not a
guarantee that no real crash occurred. Keep native coverage separately: NSW's
late-reported 2019 records are outside the analysis; QLD runs from January 2001
to June 2025. Record actual B preparation/archive times. If the original
download time is unavailable, say so in acquisition evidence; do not substitute
a portal update time or invent an extra mandatory manifest field.

## 4. Freeze and enforce the decisions

### Source contracts and confirmation

NSW/QLD rules above are **adopted for implementation**. They are not generated
runtime contracts or completed QA. Use the existing `content.input`, `identity`,
`semantics`, `snapshot` and `confirmation` structure. Put actual no-map and
eligibility operations in `semantics` and the versioned mapping, not only prose.

For these **new** NSW/QLD contract versions, define confirmation fields as follows:

| Field | Meaning |
|---|---|
| `unresolved` | Questions that still block an enabled transformation or metric. This can be empty only after those meanings and evidence are settled. |
| `publisher_questions` | Unknown external facts retained openly, such as NSW datum or the exact NSW licence version. This is not a claim that those facts were confirmed. |
| `limitations` | Hash/year-bound restrictions, linked to the executable semantic rule: no map, no interstate totals, fixed snapshot and the stated inclusion scope. |
| `implementation_prerequisites` | Work needed to enable an optional feature, such as a validated QLD target-CRS operation. Distinguish this from missing source evidence. |

The last three are descriptive keys within the existing extensible confirmation
object, not new root manifest fields. They are included in frozen rule content
and FP1. Current B validation supports that structure; no new adapter is needed
just to carry these fields. Do not move active business uncertainties into a
different list to make QA pass. **Do not reinterpret VIC's existing unresolved
list or confirmation flags this way.**

A/C record the NSW contract and D/C the QLD contract using these decisions and
the shared evidence. Actual review records must identify who performed the
work; do not invent signatures. B's legacy QA01 still needs a version/hash/
release-matched review with `status=confirmed`, `bundle_confirmed=true` and no
unresolved enabled semantics. NSW pairing has explicit official relational
evidence; QLD is a single resource. These flags confirm the selected project
input combination, not a publisher certificate. Final report availability
still depends on executed C/D/E checks.

### Protocol and gate matrix

| Build | Protocol | What must actually hold |
|---|---|---|
| S0/S8 | `team-v1.1`, synthetic definitions | Existing synthetic semantics and independent expectations; no borrowing official exceptions. |
| NSW and/or QLD without VIC | `team-v1.1` | Confirmed enabled semantics and matching reviews; normal QA01–06; correctly isolated locations under QA07. |
| VIC, or VIC plus confirmed NSW/QLD | `team-v1.1-vic-r1` | Only VIC gets its frozen amendment. Every other source keeps normal requirements. B already isolates the VIC profile by source. |

Root manifest version stays `team-v1.1`. Do not create a global official-r2,
new dataset kind or per-state core tables for these restrictions.

| Check | Enforcement for the selected official resources |
|---|---|
| QA01 | Recheck exact file identity, structure, parser, input reviews and full-snapshot changes. VIC has its existing eight metrics and exact policy evidence; NSW/QLD use the four normal confirmation metrics. |
| QA02 | Compare actual Raw with every native record: keys, locators, fields, values and counts. No semantic exception relaxes preservation. |
| QA03 | Independently check full-input and excluded counts, valid unique keys, types and parents. Keep accidents with unusable positions; no join amplification. |
| QA04 | NSW TU parent/count differences must be zero. VIC cases and restrictions must match the exact policy. QLD has no auxiliary resource; absence is derived from the manifest, not filled with a made-up pass row. |
| QA05 | Verify source-specific enabled definitions, categories, missing rules, eligibility and dispositions. NSW/QLD's disabled location feature is handled explicitly by QA07, not silently declared to have a known datum/transform. VIC retains all amended counts and its ten disclosed questions. |
| QA06 | Compare Canonical and facts by identity and field, including NULLs, qualification, versions and lineage. Equal grand totals alone do not pass. |
| QA07 | For these no-map versions: map_count=0, unmapped_count=all retained accidents, invalid_eligible_count=0, all trusted location fields NULL and every row reasoned. Nonzero accident groups are limited; zero-accident groups pass with coverage NULL. Expectations come from the policy and independent inputs. |

D must return **unavailable** for the disabled map product and restricted VIC
unit/person outputs. Internal QA07 still records real zero eligible points and
the full unmapped denominator; do not advertise this as a working official map
or hide it as an empty query. E checks every object and all seven summaries,
keeps extra blocks, and publishes only after the restrictions are enforced.
Use the existing L5 `quality_limits` and source/definition context to explain
unavailability; do not silently change the fixed SQL result shape. QLD's unit
query is also unavailable because there is no unit detail. Per-source internal
map summaries can still expose their real denominators for QA; they are not
approved interstate accident KPIs.

B freezes the full contract/mapping/QA content and actual executed modules and
migrations. Missing code cannot be replaced by test stubs or invented digests.
E03 calculates FP1 in PostgreSQL. B alone manages the shared connection,
lock, Raw short transaction, build transaction and final commit. An uncertain
commit is investigated, not marked failed or automatically repeated.

## 5. Unknown facts: the decision is already made

These are narrow conditions for expanding functionality, not a reason to pause
all tasks or ask C/E to choose the same policy again.

| Remaining fact or implementation | Current decision | Evidence needed to change it | Owner / consumers |
|---|---|---|---|
| NSW datum for these exact fields | No official NSW map | Dataset-specific CRS evidence; if needed, a validated transformation and new mapping/version | A04 + C03/C10; D07, B09, E05/E06 |
| NSW exact licence version and future late-report completeness | Keep stated attribution wording; fixed reported snapshot; no finality claim | An authoritative licence/version or revised coverage statement; do not delay existing attribution or local development | A04; B09/B11, E10 |
| VIC blank-link/count/category/Node/release definitions | Existing exact restricted policy, with every unresolved fact preserved | Definition evidence tied to the selected resources, revised cases and an explicitly versioned policy if outputs change | B06/C02/C06/C07/C08; D/E/B consumers |
| QLD target operation | Source GDA2020 confirmed; official map off | Source/target CRS, axis order, operation, accuracy, parameters/code and independent reference-point tests; then actual QA07 | C05/C10; D07, B09, E05/E06 |
| Interstate comparability | No pooled official totals or shared injury severity | A versioned study of inclusion, dates, definitions and units plus independent expected results, before a future contract change | C08 + A04/B06/D01; D05/D06/D08, E05 |
| Source freshness or future anomalous rows | Keep current pinned files; new bytes are a new review/build | Full key/coverage/change comparison, source evidence and exact explanations; no exception-count threshold | B09/B11/B12, source owners, C10, E08 |

Do not swap in VIC's separate flat-crash dataset or import real SA data to
avoid current limitations. That would introduce a new source decision and new
validation work. A later QLD map implementation can use the existing SQL
mapping boundary; this plan does not require PostGIS or new tables. A GDA94↔
GDA2020 conversion is not evidence for a GDA2020→WGS84 operation.

## 6. Work order without new handoff tasks

1. **A04/C03/C08 and D01/C05:** turn N/Q rules into the existing source-contract
   and SQL interfaces. Use the receipts here and existing metadata, not another
   request to B for the same evidence. Deliver each usable source independently.
2. **C04/C07/C09/C10:** finish the VIC projection, location isolation, Vault-to-
   Canonical path and remaining QA. Reuse C06 and the frozen restricted decision.
   C06 alone does not cover all Vehicle/Node/semantic checks.
3. **B09/B11:** consume the actual confirmed NSW/QLD contracts and supported
   mappings, preserving existing VIC support. Exercise mixed-source manifests,
   missing reviews, altered hashes, unexpected categories and no-map rules.
   B does not replace C's SQL or E's FP1.
4. **D02–D09 and E03/E05/E06:** enforce source definitions, unavailable outputs,
   complete QA and the real fingerprint/release gate. First use S0/S8; then
   validate enabled official sources independently before the combined build.
5. **A/B/C/D/E integration:** follow Raw → complete C projection → A Vault →
   C Canonical → D facts → applicable QA → E publish → B commit. Reuse the same
   interfaces for reliability tests and official scale tests. Record sample
   selection, actual full-file checks and NOT_RUN items accurately.

Existing modules stay reusable: 17 common tables, current L1 and projection
shapes, immutable histories, the existing runner, and a source-specific rule
inventory. There is no new approval spreadsheet, duplicate source model, bulk
reference-SQL import or requirement to wait for a teammate's entire module.

## 7. Course requirements and external authority

The local [Assignment 2 brief](../../Resources/32113_Assignment_2_2026.pdf)
pp. 2–4 asks for a working prototype, at least three source database schemas,
an integrated warehouse, executable commented SQL with synthetic data, three
synthetic reports, a recorded demonstration, team presentation and at least
three teacher-signed meeting records. These are deliverables, not evidence that
the current implementation has met them.

| Decision | Working plan | What remains external | Tasks |
|---|---|---|---|
| DEC01: three source systems | Prepare three real logical source schemas/views and executed source queries over the preserved input. NSW shows Crash→TU; VIC shows four resources and relationship defects; QLD shows one accident relation with aggregate attributes. Keep additional source views separate from the 17 core tables. | Teacher acceptance of this presentation; three files or source rows are not three database schemas. If separate physical source databases are required, add a bounded source-export/demo layer without changing core business grain. | E01, A08, C11, D10, E10 |
| DEC02: Lab and technology | Continue PostgreSQL 16/Python 3.12 and reproducible Lab deployment. Show actual metadata, lineage, quality and governance work as Data Fabric principles. Keep Microsoft Fabric explicitly not deployed. | Teacher acceptance of the Lab setup and principles-based technology demonstration; whether the selected Fabric product is mandatory. Ask this specific question early. | E01, A01/A09, B10, E09/E10 |
| DEC03: submission, tools and meetings | Treat the current assignment brief as the checklist, but verify the actual Canvas item/template. Team members write the final report and personal contributions; this document is internal engineering material. Obtain real teacher signatures, not reconstructed meetings. | Brief p. 1 names an Assignment 1 link/filename despite its Assignment 2 title; verify before submitting. Its p. 5 prohibits GenAI-produced final reports. Confirm any ambiguous permitted tool use with the teacher. | E01/E10, A09, D11, all personal contributions |

The submitted [Assignment 1 report](../../Resources/Assignment_1-Wrk3-05-14603450.pdf),
PDF pp. 23–24 (printed pp. 19–20), selects a Fabric Lakehouse and PostgreSQL/
PostGIS, while also proposing a PostgreSQL-only proof-of-concept benchmark.
The current team baseline is that smaller PostgreSQL prototype. Document this
scope difference; do not present it as the whole original deployment being
implemented. If the teacher requires Fabric, agree a bounded demonstration
against existing outputs instead of silently redesigning the project.

[IBM's Data Fabric description](https://www.ibm.com/think/topics/data-fabric)
and [Microsoft's Fabric overview](https://learn.microsoft.com/en-us/fabric/fundamentals/microsoft-fabric-overview)
support the distinction between architectural principles and a deployed SaaS
product. They do not establish course acceptance. The recorded teaching
decision must be quoted accurately with its date when E obtains it. No contact
with the teacher or publisher was made in this review.

## 8. Complete task index

This maps every current task to the shared decisions in section 2. The source
tables above add the concrete N/V/Q rules and their direct consumers.

| Task | Work | Shared decisions |
|---|---|---|
| A01 | Reproducible environment | O11, O13, O14 |
| A02 | Migrations and constraints | O02, O07, O09, O10 |
| A03 | Roles and reader access | O09, O12 |
| A04 | NSW source confirmation | O01, O03, O04, O05, O06, O07 |
| A05 | SQL business keys | O02, O03 |
| A06 | Vault loading | O02, O05, O06, O07 |
| A07 | Append-only history and lineage | O03, O11 |
| A08 | NSW source model and queries | O01, O05, O06, O14 |
| A09 | Cold start and structure guide | O11, O13, O14 |
| B01 | Native CSV reader | O01, O02 |
| B02 | Native Excel reader | O01, O02 |
| B03 | Hashing and archive | O01, O11 |
| B04 | L1 and file metadata | O01, O02 |
| B05 | Reader tests and run guide | O02, O13 |
| B06 | VIC Accident/Vehicle review | O01, O03, O04, O05, O06 |
| B07 | Complete S0 files | O08, O09 |
| B08 | Registration and Raw loading | O01, O02, O09 |
| B09 | Manifest and FP1 call | O01, O02, O03, O04, O05, O06, O07, O08, O09, O10, O11 |
| B10 | Runner and transactions | O09, O10, O11 |
| B11 | QA01 and QA02 | O01, O02, O03, O09, O10 |
| B12 | Repeat and concurrent runs | O03, O11 |
| B13 | Rollback and evidence | O10, O11, O13 |
| B14 | Uncertain commits and recovery | O09, O11 |
| C01 | Projection contract and samples | O02, O04, O05, O07 |
| C02 | VIC Person/Node review | O03, O05, O06, O07 |
| C03 | NSW SQL projection | O02, O04, O05, O06, O07 |
| C04 | VIC SQL projection | O02, O04, O05, O06 |
| C05 | QLD SQL projection | O02, O04, O05, O07 |
| C06 | Person relations and counts | O05, O06, O09, O10 |
| C07 | Node observations and map eligibility | O06, O07, O09 |
| C08 | Categories, missingness and eligibility | O04, O05, O08, O09 |
| C09 | Canonical from Satellite | O02, O05, O07, O11 |
| C10 | QA03/04/05/07 | O05, O06, O07, O09, O10 |
| C11 | VIC source model and queries | O01, O06, O07, O14 |
| D01 | QLD source confirmation | O01, O03, O04, O05, O07 |
| D02 | Source, month and severity dimensions | O01, O04, O05, O11 |
| D03 | Accident facts | O02, O05, O07, O09 |
| D04 | QA06 reconciliation | O05, O07, O10 |
| D05 | Trend queries | O04, O05, O08, O12 |
| D06 | Severity queries | O05, O08, O12 |
| D07 | Map and coverage queries | O07, O09, O12 |
| D08 | Unit queries | O05, O06, O08, O09, O12 |
| D09 | Interface and fixed-batch reads | O09, O12 |
| D10 | QLD source model and queries | O01, O05, O14 |
| D11 | Synthetic reports and demonstration | O08, O09, O12, O13, O14 |
| E01 | Course decisions | O14 |
| E02 | Shared interface index | O01, O09, O11 |
| E03 | SQL FP1 and tests | O11 |
| E04 | Independent S0 expectations | O08, O09, O10 |
| E05 | QA protocol and completeness | O06, O09, O10 |
| E06 | Publication and current pointer | O09, O10, O11, O12 |
| E07 | Complete S0 acceptance | O08, O09, O10, O13 |
| E08 | Reliability and fourth state | O03, O08, O09, O11 |
| E09 | Cold start and real scale | O09, O13 |
| E10 | Course evidence and submission | O01, O09, O12, O13, O14 |

Acceptance scenarios also keep their original meaning:

| Scenarios | Source-related application |
|---|---|
| AT01–AT07 | Use the fixed S0 definitions and independent expected results; official scans cannot stand in for these checks. |
| AT08–AT10 | Freeze complete rules and inputs; no-change, revised input, deletion and rule changes must use the correct namespace and version. |
| AT11 | Missing checks, ordinary blocks or non-QA07 limited results must prevent publication, including restricted official builds. |
| AT12–AT14 | Rollback, concurrency and fixed-batch reads preserve successful history and official/synthetic isolation. |
| AT15 | SA is the existing independent synthetic S8 (`syn_sa`, 2020-01, F, deaths/casualties 1/1, -34.92/138.60, no units). Keep S0 unchanged; normal input is four sources/eight resources/20 L1 rows. Preserve bad-key variants for C/E checks. This approves no real SA dataset. |
| AT16 | Real queries/page must obey source definitions, batch binding and unavailable outputs. Synthetic expected totals are not official expectations. |
| AT17 | Reproduce the synthetic cold start; official sample/full-scale measurements are separate and cannot be inferred from it. |

## 9. Evidence and completion boundary

- [NSW review](sources/evidence/official-decisions-2026-09-23/nsw-review.json): official references, paired-resource basis, exact categories and full-file observations.
- [QLD review](sources/evidence/official-decisions-2026-09-23/qld-review.json): metadata identity, definitions, source CRS and full-file observations.
- [VIC shared review](sources/vic-accident-vehicle.md) and [adopted policy](../config/vic-restricted-use-v1.json): existing findings, exact cases and permitted use.
- [Review index](sources/evidence/official-decisions-2026-09-23/review-index.json): current inputs, document hashes, 55-task coverage and preservation checks.

The information decisions are settled at the scope stated here. New facts may
justify a new version. Remaining work is implementation and real verification,
plus the specific teaching decisions above; it is not another open-ended round
of source-policy decisions. No platform code, frozen policy, original input,
historical receipt, website or Git history was changed for this review.
