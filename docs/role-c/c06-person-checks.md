# C06 — VIC Person Relationships and Count Checks

> Internal development / QA design note  
> Role: C  
> Status: Draft v0.1

## 1. Purpose

C06 validates VIC Person relationships against the selected Accident and
Vehicle resources and reconciles source-declared Person counts where the
definitions are confirmed to be comparable.

Person remains a Raw/runtime-check entity. C06 does not create a Person
Canonical table or Person fact table.

The checks must preserve native evidence and return Raw-located diagnostics.

---

## 2. Person candidate identity

The candidate Person key is:

`ACCIDENT_NO + PERSON_ID`

Checks required:

- both key components must be evaluated using the native source values;
- duplicate candidate Person keys must be reported;
- Person identity must not be created from row position or synthetic numbering.

Current source evidence indicates no duplicate Person candidate keys in the
reviewed VIC snapshot, but the runtime check must still remain active.

---

## 3. Person-to-Accident relationship

Every Person row must be checked against its Accident parent using:

`ACCIDENT_NO`

Expected rule:

- matching Accident → relationship is valid;
- missing Accident parent → report a relationship exception;
- do not create an artificial Accident parent.

Current reviewed evidence found no Person rows without an Accident parent in
the selected snapshot.

---

## 4. Person-to-Vehicle relationship

Where `VEHICLE_ID` is non-empty, the relationship must be checked using the
full key:

`ACCIDENT_NO + VEHICLE_ID`

`VEHICLE_ID` must not be matched independently of its Accident.

The runtime check must distinguish:

1. valid non-empty Vehicle reference;
2. allowed blank Vehicle reference;
3. unresolved blank Vehicle reference;
4. unmatched non-empty Vehicle reference.

For unmatched non-empty references:

- preserve the Person Raw row;
- preserve the valid Person-to-Accident relationship;
- do not invent a Vehicle row;
- do not invent a Person-to-Vehicle relationship;
- return the native key values and Raw locator in the diagnostic result.

Current evidence contains 39 unmatched non-empty Person-to-Vehicle references.

Under the current QA04 contract these remain blocking relationship exceptions
until any proposed rule change is formally confirmed and versioned.

---

## 5. Blank Vehicle references

Blank `VEHICLE_ID` values must not be treated the same as unmatched non-empty
Vehicle references.

Current source evidence indicates that most blank Vehicle references are
associated with pedestrian Person roles.

The runtime result must separate at least:

- `allowed_blank_vehicle_ref`
- `unresolved_blank_vehicle_ref`

The exact rule for which Person roles allow a blank Vehicle reference remains
subject to confirmed source/business rules.

No default rule should silently classify all blank values as valid.

---

## 6. Person count reconciliation

Where the source definitions are confirmed as comparable, C06 should compare
the Accident-level declared Person count with the Person detail rows.

Current evidence indicates that the 2020–2024 analytical scope reconciles for
the reviewed VIC snapshot.

The check must:

- compare only confirmed compatible scopes;
- distinguish count mismatch from relationship mismatch;
- report the affected Accident;
- retain the contributing Raw locators;
- never create or remove Person rows to force reconciliation;
- not introduce an automatic tolerance.

Historical discrepancies outside the analytical scope must remain visible if
the full source snapshot is checked.

---

## 7. Required diagnostic categories

C06 should return explicit diagnostic categories such as:

- `duplicate_person_key`
- `missing_accident_parent`
- `allowed_blank_vehicle_ref`
- `unresolved_blank_vehicle_ref`
- `unmatched_nonblank_vehicle_ref`
- `person_count_mismatch`

Diagnostic rows should include, where applicable:

- `raw_record_id`
- `ACCIDENT_NO`
- `PERSON_ID`
- `VEHICLE_ID`
- diagnostic code
- diagnostic detail/reason
- rule version

Native identifiers must remain visible in the result.

---

## 8. Development rules

C06 must not:

- create missing Accident parents;
- create missing Vehicle rows;
- match Vehicle references using `VEHICLE_ID` alone;
- invent Person records to satisfy a declared count;
- automatically tolerate count differences;
- merge blank and non-empty Vehicle reference exceptions into one category.

Synthetic tests may be used before the shared official Raw integration is
available.

---

## 9. Current dependencies

### Available

- B06/C02 Person key and relationship evidence
- B08 Raw interface
- VIC Accident / Vehicle / Person source evidence
- current QA04 relationship rule

### Still requiring confirmation

- exact business rule for valid blank `VEHICLE_ID` cases;
- exact scope/version of any future QA04 severity change;
- confirmed definition scope for all Person/unit count comparisons;
- final shared SQL/Python invocation convention from B10.

These items do not block development of the core C06 checks.

---

## 10. Completion criteria

C06 is complete when it can reproducibly report:

- Person key duplicates;
- missing Accident parents;
- valid versus invalid/unresolved Vehicle references;
- unmatched non-empty Vehicle references using the full Accident + Vehicle key;
- Person count reconciliation results under confirmed definitions;
- Raw-located evidence for each exception.

Person remains Raw/check-only and no artificial parent or detail records are
created.
