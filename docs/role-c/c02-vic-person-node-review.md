# C02 — VIC Person / Node Source Contract Review

> **Internal team design / evidence note — not final submission prose.**  
> Task: **C02 — Confirm VIC Person / Node**  
> Role: **C**  
> Current status: **In progress**  
> Current contract status: `draft`  
> Four-resource bundle status: `bundle_confirmed=false`

## 1. Scope and reviewed evidence

This C02 review focuses on the VIC **Person** and **Node** resources and their compatibility with the VIC **Accident** and **Vehicle** resources reviewed in B06.

The review uses the locally saved VIC source files, recorded source metadata and file hashes, the B06 four-resource source review, local profiling results, and targeted official API comparisons already collected by the team.

The purpose of C02 is to confirm:

- Person identity and Accident/Vehicle reference behaviour;
- candidate Person keys;
- declared-person count scope;
- Node matching behaviour;
- repeated and duplicate Node observations;
- coordinate consistency;
- CRS evidence;
- source/release compatibility; and
- unresolved source-contract items.

A successful join or similar publication/download dates do **not** prove that the four VIC resources form one officially consistent release bundle. The source contract therefore remains draft while unresolved source-definition, release-compatibility and CRS issues remain.

---

## 2. Person identity and references

### 2.1 Candidate Person identity

The reviewed Person resource supports the candidate Person key:

`ACCIDENT_NO + PERSON_ID`

`ACCIDENT_NO` identifies the parent Accident and `PERSON_ID` identifies the person within that Accident.

### 2.2 Person-to-Accident relationship

Person records must first be checked against the full Accident source using `ACCIDENT_NO`.

Observed result in the current saved files:

- Person rows without an Accident parent: **0**

This is an observed result for the current source snapshot, not a permanent guarantee for future releases.

### 2.3 Person-to-Vehicle relationship

Where `VEHICLE_ID` is non-empty, the Vehicle reference must be checked using the full key:

`ACCIDENT_NO + VEHICLE_ID`

`VEHICLE_ID` must not be treated as globally unique or matched without the parent Accident scope.

Observed result:

- non-empty Person `VEHICLE_ID` values with no matching Vehicle: **39**
- all 39 are within the 2020–2024 analytical scope
- the same cases remain present in the targeted official API checks
- year filtering does not explain these mismatches

These records must not be repaired by inventing Vehicle rows or Vehicle links.

### 2.4 Current QA04 treatment

The current 04/05 contract treats the 39 unmatched non-empty Person→Vehicle references as **blocking relationship exceptions**.

A possible change to non-blocking treatment has been raised, but Role E still needs to confirm the exact decision, scope and rule version.

Until the shared contract is formally updated and versioned, C02 follows the current blocking rule.

Regardless of the final severity:

- preserve the Person record in Raw;
- preserve any valid Person→Accident relationship;
- do not create an artificial Vehicle;
- do not create an artificial Person→Vehicle link;
- record the unresolved reference as QA04 evidence.

This QA04 rule review does not prevent the remaining C02 evidence review or synthetic prototype work.

### 2.5 Blank `VEHICLE_ID`

Blank Vehicle references must be treated separately from non-empty unmatched references.

Observed in the full saved Person file:

| Observation | Full file | 2020–2024 |
|---|---:|---:|
| Blank `VEHICLE_ID`, pedestrian role | 18,752 | 6,186 |
| Blank `VEHICLE_ID`, unknown role | 24 | 6 |
| Blank `VEHICLE_ID`, other roles | 0 | 0 |

The current evidence does **not** establish a general official rule that every blank `VEHICLE_ID` is valid.

Current interpretation:

- pedestrian + blank Vehicle reference is a plausible valid non-association;
- unknown-role blank Vehicle references remain unresolved;
- blank references must not be automatically treated as valid or invalid without an approved source/business rule.

---

## 3. Declared-person count scope

`NO_PERSONS` represents total participants and includes uninjured people.

Person detail can therefore be compared with Accident-level participant and injury counts for reconciliation, but missing detail must not be reconstructed.

Observed results:

- two historical Person total/injury-component discrepancies were found in the full local snapshot;
- both discrepancies occur in 2015;
- **no Person-total or injury-component reconciliation exceptions were observed within the 2020–2024 analytical scope**.

Current rule:

- count comparison is diagnostic;
- mismatches must be recorded rather than silently tolerated;
- missing Person records must not be invented;
- successful reconciliation in the current analytical period does not remove the need to repeat reconciliation for later releases.

---

## 4. Node matching and repeated observations

### 4.1 Node matching key

For crash-specific Node matching, use:

`ACCIDENT_NO + NODE_ID`

This is a **matching/grouping key**, not an assumed unique row key.

The same Node ID may appear for multiple accidents and the same Accident/Node pair may appear in multiple exported observations.

### 4.2 Repeated observations

Observed results in the current saved Node file:

- Node rows: **405,918**
- exact duplicate rows across all native columns: **202,505**
- repeated groups where only `DEG_URBAN_NAME` varies: **3,137**

Raw observations must remain preserved as source evidence.

Downstream processing must prevent repeated Node observations from multiplying crash counts or creating artificial duplicate crash locations.

### 4.3 Coordinate consistency

Within each reviewed `ACCIDENT_NO + NODE_ID` group:

- matching coordinate pairs are equal as exact decimals;
- no conflicting coordinate groups were observed;
- no non-finite or out-of-range coordinate pairs were observed in the current saved file.

This does not remove the need for a runtime conflict rule. Synthetic tests should still include conflicting and invalid coordinate cases.

---

## 5. Missing Node matches

Observed results:

- Accident records without a matching Node: **85** in the full file
- Accident records without a matching Node in 2020–2024: **7**

The unmatched Accident `NODE_ID` values are negative identifiers:

`-1`, `-10`, `-3`

Their official meanings are not confirmed.

Current handling:

- retain the Accident/crash;
- do not create a synthetic Node record;
- do not create replacement coordinates;
- record location unavailability under QA07;
- keep the crash available for applicable non-spatial analysis.

---

## 6. CRS and spatial status

The Node resource contains latitude/longitude values and projected coordinate fields, but the reviewed Node-specific metadata does not provide sufficient release-specific evidence to assign an EPSG code to the latitude/longitude fields.

The current flat crash resource provides WGS84 metadata and selected Node coordinates match flat-resource coordinates exactly. This is supporting evidence only; it does not prove the CRS of the locally saved Node release.

Current status:

- coordinate values: observed and internally consistent in reviewed cases;
- coordinate range checks: no observed conflicts in the current saved file;
- Node release CRS: **unconfirmed**;
- formal EPSG:4326 assignment: **not approved**;
- map eligibility: remains limited/draft until CRS evidence is confirmed.

Plausible coordinate values alone must not establish CRS.

---

## 7. Release and version evidence

The four VIC resources are tracked with source metadata, source-file hashes, parser/locator versions and local evidence receipts.

The current locally saved metadata snapshot does not by itself establish one official joint four-resource release.

Relevant observations:

- Accident metadata changed in the later live metadata check;
- Vehicle, Person and Node retained the previously observed coverage during the targeted check;
- similar dates and successful joins are insufficient to establish release compatibility;
- no earlier confirmed joint snapshot is available to prove deletion/revision behaviour across all four resources.

Current compatibility state:

`status=draft`

`bundle_confirmed=false`

---

## 8. Current team rules applied by C02

The following rules are currently applied:

1. **Do not invent missing parent, Vehicle or Node records.**
2. **Non-empty Person→Vehicle references must use the full `ACCIDENT_NO + VEHICLE_ID` key.**
3. **The current 04/05 QA04 contract remains blocking until any proposed change is formally confirmed and versioned.**
4. **Repeated Node observations remain preserved in Raw but must not inflate downstream crash/location counts.**
5. **Missing or untrusted location information does not remove an otherwise eligible crash from non-spatial analysis.**
6. **Conflicting or untrusted locations must not be used in spatial/map outputs.**
7. **CRS must be supported by source evidence; plausible coordinate values alone are insufficient.**
8. **Unconfirmed official source rules remain draft while synthetic prototype work may proceed.**

---

## 9. Unresolved items

The following items remain unresolved:

- which blank Person `VEHICLE_ID` cases are officially valid;
- treatment of the small number of unknown-role blank Vehicle references;
- explanation for the 39 non-empty unmatched Person→Vehicle references;
- exact scope and version of any proposed QA04 rule change;
- complete definitions/count eligibility for Vehicle type `21` and Person role `16`;
- complete Vehicle count-scope rules for categories such as trailers and electric devices;
- official meaning of negative Accident `NODE_ID` values (`-1`, `-10`, `-3`);
- reason for repeated Node export observations;
- release-specific Node CRS / documented coordinate lineage;
- final four-resource release compatibility.

These unresolved items prevent final approval of the official four-file VIC source contract, but they do not prevent synthetic prototype development or further C-role implementation.

---

## 10. Current C02 assessment

The available evidence is sufficient to define the current Person and Node matching behaviour, document observed anomalies, establish non-invention rules and define the present spatial limitations.

However, the evidence is **not** sufficient to approve the four VIC resources as one fully compatible official release bundle.

Current C02 outcome:

- Person identity/reference evidence: **reviewed**
- Person count evidence: **reviewed**
- Node matching/repetition evidence: **reviewed**
- coordinate-conflict evidence: **reviewed**
- release/version evidence: **reviewed**
- CRS: **unresolved**
- blank Vehicle-reference semantics: **partly unresolved**
- QA04 rule change: **pending formal confirmation/versioning**
- four-resource source contract: **draft**
- `bundle_confirmed`: **false**

---

## 11. Evidence references

Primary internal evidence:

- `docs/sources/vic-accident-vehicle.md` — B06 VIC four-resource source review
- `docs/sources/evidence/vic/` — local profiling, Person/Node review, API comparison and validation evidence
- current 04/05 team contract and QA definitions
- Role E clarification regarding the pending QA04 rule review

Related Raw implementation evidence:

- `docs/b08-postgres-review.md`
- `docs/b08-db-handoff.md`
- `src/arsia_ingest/raw_load.py`
- B08 PostgreSQL test evidence

Official source materials reviewed by the team include the VIC Accident, Vehicle, Person and Node resource dictionaries and metadata.
