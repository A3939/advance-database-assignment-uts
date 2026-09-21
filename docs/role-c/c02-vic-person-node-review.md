# C02 — VIC Person / Node Source Contract Review

> **Internal team design / evidence note — not final submission prose.**  
> Role: **C**  
> Status: **Draft v0.2**  
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

Current observed result:

- non-empty unmatched Person-to-Vehicle references: **39**
- all 39 are within the 2020–2024 analytical scope
- the same cases persist in targeted official API evidence

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

- allowed blank Vehicle reference, once formally confirmed;
- unresolved blank Vehicle reference;
- unmatched non-empty Vehicle reference.

No default rule should silently classify all blank Vehicle references
as valid.

---

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

Historical discrepancies remain valid source exceptions even though they
fall outside the current 2020–2024 analytical scope.

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

Where a representative can safely be selected, its Raw lineage must remain
traceable to the chosen native Node observation.

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
- map eligibility: remains limited until CRS evidence is confirmed.

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
3. Match Person-to-Vehicle only on `ACCIDENT_NO + VEHICLE_ID`.
4. Do not create missing Accident or Vehicle parents.
5. Keep blank Vehicle references separate from unmatched non-empty references.
6. Treat pedestrian blank Vehicle references only as a candidate rule until confirmed.
7. Preserve repeated Node observations in Raw.
8. Do not allow repeated Node rows to multiply crash/location counts.
9. Do not choose an arbitrary first Node row.
10. Do not average conflicting coordinates.
11. Do not create Node records for negative IDs.
12. Keep crashes with unavailable locations for non-spatial analysis.
13. Do not assign CRS from plausible coordinates alone.
14. Keep the four-resource VIC contract draft until compatibility evidence is sufficient.

---

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

Primary internal evidence:

- `docs/sources/vic-accident-vehicle.md`
- `docs/sources/evidence/vic/person-node-local-review-2026-09-17.json`
- `docs/sources/evidence/vic/person-node-api-check-2026-09-17.json`
- `docs/sources/evidence/vic/person-node-comparison-2026-09-17.json`
- `docs/sources/evidence/vic/local-profile-2026-09-17-final.json`

Related implementation evidence:

- B08 Raw interface
- current QA04/QA05/QA07 team rules
- C06 Person relationship checks
- C07 Node/location checks
