# C02 — VIC Person / Node Source Contract Review

> **Internal team design / evidence note — not final submission prose.**
> Role: **C**
> Status: **Draft v0.3**
> Source contract status: `draft`
> Four-resource bundle status: `bundle_confirmed=false`

## 1. Scope

C02 reviews the VIC Person and Node resources together with the Accident
and Vehicle evidence already established in B06.

The purpose is to confirm:

- Person identity and relationship behaviour;
- candidate Person keys;
- Person-to-Accident and Person-to-Vehicle references;
- declared Person-count reconciliation;
- Node matching behaviour;
- repeated Node observations;
- coordinate consistency;
- CRS evidence;
- source/release compatibility; and
- unresolved source-contract items.

The current four-file source contract remains draft because unresolved
relationship, classification, count-scope, release-compatibility and CRS
questions remain.

---

## 2. Person identity

The candidate Person identity is:

`ACCIDENT_NO + PERSON_ID`

The key must retain the full native source values.

Person identity must not be derived from:

- row position;
- synthetic numbering;
- `PERSON_ID` alone.

Current evidence found no blank or duplicate Person candidate keys in the
reviewed source snapshot.

---

## 3. Person-to-Accident relationship

Person rows must first be matched to Accident using:

`ACCIDENT_NO`

Current observed result:

- Person rows without an Accident parent: **0**

Parent matching must be performed against the full Accident resource before
applying the 2020–2024 analytical occurrence-year filter.

Child rows inherit analytical scope from the matched Accident occurrence
date/year. A missing Accident parent is therefore treated as an orphan,
not as an out-of-range Person row.

This is an observed result for the current saved source snapshot and must
not be treated as a permanent guarantee for future releases.

If a future Person row has no matching Accident:

- retain the Raw Person evidence;
- report the relationship exception;
- do not create an artificial Accident parent.

---

## 4. Person-to-Vehicle relationship

Where `VEHICLE_ID` is non-empty, the Vehicle relationship must use the
full composite reference:

`ACCIDENT_NO + VEHICLE_ID`

`VEHICLE_ID` must not be matched independently of its parent Accident.

Vehicle matching must occur within the same source and selected
snapshot/release context. The same `VEHICLE_ID` in another Accident or
source context is not a valid match.

Current observed result:

- non-empty unmatched Person-to-Vehicle references: **39**
- all 39 are within the 2020–2024 analytical scope
- the same cases persist in targeted official API evidence

Of the 39 unmatched references, three affected crashes contain no Vehicle
rows at all. The other 36 contain Vehicle rows, but the referenced
`ACCIDENT_NO + VEHICLE_ID` key is absent.

The 39 cases must not be repaired by:

- blanking the Vehicle reference;
- matching the same `VEHICLE_ID` from another Accident;
- creating an artificial Vehicle;
- creating an artificial Person-to-Vehicle link.

### Current QA04 treatment

Under the current team contract, the 39 unmatched non-empty references
remain **blocking QA04 relationship exceptions**.

If the team later changes the severity or publication treatment, that
change must be formally confirmed, scoped and versioned before C02 adopts it.

Regardless of future severity treatment, invalid relationships must never
be manufactured.

---

## 5. Blank `VEHICLE_ID`

Blank Vehicle references must be handled separately from unmatched
non-empty Vehicle references.

Observed evidence:

| Observation | Full file | 2020–2024 |
|---|---:|---:|
| Blank `VEHICLE_ID`, pedestrian role `1` | 18,752 | 6,186 |
| Blank `VEHICLE_ID`, unknown role `9` | 24 | 6 |
| Blank `VEHICLE_ID`, other roles | 0 | 0 |

Pedestrian + blank `VEHICLE_ID` is currently a plausible candidate
non-association rule based on the observed source pattern, but it is not
an officially confirmed nullability rule.

Unknown-role blank references remain unresolved.

Pedestrian status alone must not be used to remove an existing non-empty
Vehicle reference, because some pedestrian records have valid matching
Vehicle references.

Therefore C06/runtime checks must distinguish:

- candidate/confirmed allowed blank Vehicle reference;
- unresolved blank Vehicle reference;
- unmatched non-empty Vehicle reference.

Blank `VEHICLE_ID` cases must be classified from confirmed source/business
rules, not inferred from role code alone.

A blank reference must not be promoted to "allowed" unless the supporting
source/business rule is confirmed and versioned.

No default rule should silently classify all blank Vehicle references
as valid.

## 6. Person count reconciliation

`NO_PERSONS` represents total participants and includes uninjured people.

Current evidence shows:

- two historical Person total/injury-component discrepancies in the full file;
- both discrepancies occur in 2015;
- all reviewed Person totals and injury components reconcile in the
  2020–2024 analytical scope.

Count reconciliation must:

- compare only confirmed compatible scopes;
- retain native Accident and Person evidence;
- report differences explicitly;
- not create Person rows to satisfy a declared count;
- not introduce an automatic tolerance.

Count reconciliation must use Person rows attached to the confirmed Accident
parent set before applying analytical-scope conclusions.

Zero observed mismatches in 2020–2024 is a result for the reviewed snapshot,
not proof that future releases or all publication scopes are complete.

Once the comparison scope is confirmed, unexplained differences block QA04
under team 04 §3; describing a comparison as diagnostic does not waive this rule.
If scope is not confirmed, keep that limitation explicit under QA05 rather than
reporting reconciliation as passed. Historical discrepancies remain recorded
even when they fall outside the current 2020–2024 analytical scope.

---

## 7. Vehicle 21 / Person 16 classification issue

The reviewed files contain:

- Vehicle type `21 / Electric Device`; and
- Person role `16 / E-scooter Rider`.

These codes are associated in many records but are not interchangeable.

Their labels are observed in the data, but complete historical definitions,
recoding rules and count-eligibility semantics remain unresolved.

C02 therefore preserves the native values and does not infer a new shared
classification rule.

---

## 8. Node matching

Crash-specific Node matching uses:

`ACCIDENT_NO + NODE_ID`

This is a **matching/grouping key**, not a unique row key.

The same Node ID may be associated with multiple crashes, and the same
Accident/Node pair may appear in multiple exported observations.

The implementation must therefore not assume one physical Node row per
`ACCIDENT_NO + NODE_ID`.

---

## 9. Repeated Node observations

Current evidence shows substantial repeated Node observations.

Observed results include:

- 143,808 distinct Node IDs;
- 200,267 `ACCIDENT_NO + NODE_ID` groups;
- 202,505 exact duplicate rows;
- 3,137 groups where only `DEG_URBAN_NAME` differs.

The matching key is therefore highly non-unique at row level.

Repeated Node rows must be treated as source observations, not as
additional crash locations.

Raw must preserve the observations, while downstream logic must prevent
them from multiplying crash counts or creating artificial location facts.

---

## 10. Representative location selection

A representative location record may only be selected when all relevant
matching Node observations:

- are valid;
- are complete for the required coordinate fields;
- share one exact coordinate pair;
- have supported relationship evidence; and
- have supported CRS evidence.

The implementation must not:

- arbitrarily select the first matching row;
- average conflicting coordinates;
- discard conflicting observations;
- fabricate missing coordinates.

Compare coordinates as exact decimals before rounding to `numeric(10, 7)`.
When observations are equivalent and otherwise usable, select the representative
by file SHA256, parser version and numeric native row locator, in that order
(team 05 §4). This determines `location_record_id`; all observations stay in Raw.
An unresolved or partly invalid group must not be made usable by dropping rows.

---

## 11. Missing Node matches

Current evidence shows:

- 85 Accidents without matching Node observations in the full file;
- 7 such Accidents within 2020–2024.

All reviewed missing matches use negative Accident `NODE_ID` values:

- `-1`
- `-10`
- `-3`

Their official meanings remain unconfirmed.

Current rule:

- retain the crash;
- do not create a negative-ID Node row;
- do not invent coordinates;
- treat location as unavailable/limited under QA07;
- retain the crash for applicable non-spatial analysis.

---

## 12. Coordinate consistency

Within reviewed matching Node groups:

- coordinate pairs are equal as exact decimals;
- no conflicting coordinate groups were observed;
- no non-finite coordinate values were observed;
- no out-of-range coordinate pairs were observed.

These are observed results for the reviewed snapshot.

Runtime logic must still support synthetic tests for:

- conflicting coordinates;
- incomplete coordinates;
- invalid coordinates;
- repeated observations.

---

## 13. CRS status

The reviewed Node-specific metadata does not provide sufficient
release-specific evidence to formally assign a CRS to the Node
latitude/longitude fields.

The flat crash resource declares WGS84, and selected Node coordinates match
flat-resource coordinates exactly.

This is supporting evidence only.

Current status:

- coordinate values: observed and internally consistent;
- Node release CRS: **unconfirmed**;
- formal EPSG:4326 assignment: **not approved**;
- row eligibility: `map_eligible=false` until CRS evidence is confirmed;
- projected latitude, longitude, `location_crs` and `location_record_id`: NULL;
- QA07: may be `limited` only when the location has been correctly isolated and
  its evidence retained. This does not clear the separate QA01/QA04/QA05 blockers.

Plausible coordinate values alone must not establish CRS.

---

## 14. Release and compatibility status

The locally saved four VIC resources share similar metadata dates, but this
does not prove that they form one officially consistent release bundle.

Current descriptive release label:

`locally saved 2026-08 metadata snapshot`

Current official release scope:

`unconfirmed`

Targeted official API checks confirm that the reviewed anomalies persist in
published data.

However, targeted API checks do **not** constitute validation of the complete
current release.

Therefore:

`status=draft`

`bundle_confirmed=false`

remains the correct current source-contract status.

---

## 15. Current C02 rules

C02 currently applies the following rules:

1. Preserve all native Raw evidence.
2. Use `ACCIDENT_NO + PERSON_ID` as the candidate Person key.
3. Match Person to the full Accident resource before applying the
   2020–2024 analytical occurrence-year filter.
4. Treat a missing Accident parent as an orphan, not as an out-of-range row.
5. Match a non-empty Person-to-Vehicle reference only on
   `ACCIDENT_NO + VEHICLE_ID` within the same source and selected source
   snapshot/file set.
6. Do not infer official release compatibility from successful joins or
   similar publication dates.
7. Do not create missing Accident or Vehicle parents.
8. Keep blank Vehicle references separate from unmatched non-empty references.
9. Treat pedestrian blank Vehicle references only as a candidate rule until
   a supporting source/business rule is confirmed and versioned.
10. Perform Person-count reconciliation only under confirmed compatible
    comparison scopes; unexplained differences then remain QA04 exceptions.
11. Preserve repeated Node observations in Raw.
12. Do not allow repeated Node rows to multiply crash/location counts.
13. Do not choose an arbitrary first Node observation.
14. Do not average conflicting coordinates.
15. Do not create Node records for negative IDs.
16. Keep crashes with unavailable locations for applicable non-spatial analysis.
17. Do not assign CRS from plausible coordinate values alone.
18. Keep the four-resource VIC source contract draft until compatibility
    evidence is sufficient.

## 16. Unresolved items

The following items remain unresolved:

- Which blank Person `VEHICLE_ID` cases are officially valid.
- Why the 39 non-empty Vehicle targets are missing.
- Why the two historical uninjured Person details are missing.
- Which Vehicle categories count toward declared Vehicle totals.
- Full definition and historical treatment of Vehicle type `21`.
- Full definition and historical treatment of Person role `16`.
- Why Node observations repeat.
- What negative Node IDs `-1`, `-10`, `-3` officially mean.
- Whether the reviewed Node release is formally WGS84 / EPSG:4326.
- What documented coordinate lineage or operation establishes Node CRS.
- Whether the four locally saved VIC files form one compatible official release bundle.
- Whether any future QA04 severity change is formally confirmed and versioned.

---

## 17. Current C02 assessment

Current evidence is sufficient to define:

- Person candidate identity;
- Accident-parent matching;
- Vehicle-reference matching;
- observed blank/non-empty Vehicle-reference patterns;
- Person count reconciliation behaviour;
- Node matching behaviour;
- repeated Node observation behaviour;
- current coordinate-consistency evidence;
- current missing-location handling.

Current evidence is not sufficient to confirm:

- all blank Vehicle-reference semantics;
- complete Vehicle count scope;
- complete Vehicle 21 / Person 16 semantics;
- negative Node ID meanings;
- release-specific Node CRS;
- a fully compatible official four-resource bundle.

Current outcome:

- Person identity evidence: **reviewed**
- Person relationship evidence: **reviewed**
- Person count evidence: **reviewed**
- Node matching evidence: **reviewed**
- repeated Node evidence: **reviewed**
- coordinate consistency evidence: **reviewed**
- CRS: **unresolved**
- blank Vehicle-reference semantics: **partly unresolved**
- four-resource contract: **draft**
- `bundle_confirmed`: **false**

---

## 18. Evidence references

The observations above refer to the saved August files and the September 17 UTC
API checks, not a new full-source run. September 18 document dates use Sydney
time. The following links pin the existing B evidence; no historical receipt
has been regenerated for this revision.

| Evidence | Exact location / use |
|---|---|
| [B06 / C02 shared review](https://github.com/A3939/advance-database-assignment-uts/blob/3185b841a86a4b8f9c998636766efbf6332efa8c/docs/sources/vic-accident-vehicle.md) | §1 original SHA256/version table; §5 Person; §6 Node; §7 compatibility; §9 reproduction. |
| [Initial profile](https://github.com/A3939/advance-database-assignment-uts/blob/3185b841a86a4b8f9c998636766efbf6332efa8c/docs/sources/evidence/vic/local-profile-2026-09-17-final.json) | `files.person` candidate-key checks; `findings.person_missing_accident`; `findings.person_nonblank_vehicle_not_found`; `node_observations`. |
| [Local follow-up](https://github.com/A3939/advance-database-assignment-uts/blob/3185b841a86a4b8f9c998636766efbf6332efa8c/docs/sources/evidence/vic/person-node-local-review-2026-09-17.json) | `person.reference_counts`, `person.unmatched`, `person.unmatched_scope_counts`, `count_differences`, `vehicle_type21`, `person.type16`, `node`. |
| [API receipt](https://github.com/A3939/advance-database-assignment-uts/blob/3185b841a86a4b8f9c998636766efbf6332efa8c/docs/sources/evidence/vic/person-node-api-check-2026-09-17.json) | `requests[]`: saved URLs, filters, response content and retrieval hashes. API IDs are not CSV locators. |
| [Offline comparison](https://github.com/A3939/advance-database-assignment-uts/blob/3185b841a86a4b8f9c998636766efbf6332efa8c/docs/sources/evidence/vic/person-node-comparison-2026-09-17.json) | `original_unmatched_references`, `current_api_count_differences`, `original_missing_node_cases`, `node_and_flat_coordinates`, `native_field_comparisons`. |
| [Research record](https://github.com/A3939/advance-database-assignment-uts/blob/3185b841a86a4b8f9c998636766efbf6332efa8c/docs/sources/evidence/vic/person-node-research-2026-09-18.json) | `official_support` versus `file_and_api_observations`, `inferences_not_rules` and `open_questions`. |
| [B08 Raw interface](https://github.com/A3939/advance-database-assignment-uts/blob/3185b841a86a4b8f9c998636766efbf6332efa8c/docs/raw-loading.md) | Supplied connection, immutable Raw values and ID reuse. |
| [C06 draft](c06-person-checks.md) | Current Person-check work; the source review does not certify its SQL implementation. |

For Node, the local follow-up's `node.exact_duplicate_extra_rows` is 202,505;
`node.varying_fields` identifies 3,137 groups varying only in DEG_URBAN_NAME.
Use `node.missing_matches` for the 85 full-file cases and
`node.missing_scope_counts` for the 7 in scope. Blank-reference totals come
from `person.reference_counts`, separated by scope and road-user type.

The official definitions behind the review are preserved in the
[package evidence](https://github.com/A3939/advance-database-assignment-uts/blob/3185b841a86a4b8f9c998636766efbf6332efa8c/docs/sources/evidence/vic/official-package-2026-09-17.json):
Person `result.resources[2].attributes`, Node `result.resources[4].attributes`,
and Accident `result.resources[0].attributes` (NO_PERSONS: AT-14416).
The source overview explains which claims these definitions support.

The policy basis remains team v1.1: **02** for Raw/Canonical fields,
**04 §3** for QA04/05/07, and **05 §4** for Person references, Node selection
and quality reasons. These shared documents live under
`F/ARSIA-Team-Handoff/` in the course workspace. Their rules are not changed
by this evidence note.
