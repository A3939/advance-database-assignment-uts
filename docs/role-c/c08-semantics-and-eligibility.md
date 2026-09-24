# C08 — Classification, Missing Values and Eligibility

> Internal development / semantic-rule note  
> Role: C  
> Status: Draft v0.1  
> Team baseline: `team-v1.1`

## 1. Shared semantic rules

C08 defines versioned semantic rules that are applied before Vault loading
and reused by the NSW, VIC and QLD source projections.

### 1.1 Missing values

- Preserve native source values in Raw.
- Convert only contract-declared missing values/tokens to NULL.
- Do not treat every `NA`, `Unknown`, blank-looking token or zero as missing.
- Known zero remains zero.
- An unknown required count component makes the derived total NULL.
- A new non-empty source category must not be silently mapped to false,
  `__MISSING__`, zero or another existing category.
- Undefined non-empty categories block semantic acceptance.

### 1.2 Independent metric eligibility

The following crash-level eligibility flags are independent:

- `fatal_crash_eligible`
- `fatality_eligible`
- `casualty_eligible`

An eligibility flag may be true only when:

1. the corresponding source definition is confirmed;
2. all required inputs are valid and determinable; and
3. the projected value is non-NULL under that confirmed definition.

One unavailable metric must not make the entire crash unavailable.

Setting all eligibility flags to false must not be used to bypass an
unknown or undefined business definition.

### 1.3 Invalid values

Invalid required keys, dates, counts or other core values block.

Negative people/count values are invalid unless explicitly supported by
the source contract.

Location problems are isolated from non-spatial crash measures and do not
remove otherwise valid crashes.

### 1.4 Quality reasons

`quality_notes` uses the fixed shared reason vocabulary:

- `missing`
- `unmapped`
- `definition_unconfirmed`
- `invalid_coordinate`
- `crs_unconfirmed`
- `location_conflict`
- `no_location`

Each false eligibility must have corresponding evidence/reason information.

Quality notes explain limitations; they do not convert invalid core values
into valid values.

### 1.5 Location eligibility

For the first official version, official maps remain disabled unless the
source-specific CRS and any required transformation are confirmed and
validated.

Where location is unavailable or not trusted:

- `latitude = NULL`
- `longitude = NULL`
- `location_crs = NULL`
- `location_record_id = NULL`
- `map_eligible = false`

The crash remains available for applicable non-spatial analysis.

### 1.6 Source-specific meanings

Official NSW, VIC and QLD metrics remain source-specific.

Do not pool or silently harmonise:

- severity categories;
- serious-injury concepts;
- casualty definitions;

## 2. NSW semantic rules

### 2.1 Rule versions

Source:

`official_nsw`

Release scope:

`nsw_pinned_2020_2024_v1`

Confirmed source contracts:

- `nsw-crash-contract-v1`
- `nsw-traffic-unit-contract-v1`

Projection mappings:

- `nsw-crash-projection-v1`
- `nsw-traffic-unit-projection-v1`

Severity definition:

`nsw-crash-severity-v1`

A04 is the confirmed source decision owned by Role A.
C08 consumes these rules without redefining their source meaning.

### 2.2 Occurrence time

Crash occurrence time uses:

- year: `Year of crash`
- month: `Month of crash`

`Reporting year` is retained for audit only and must not replace the
occurrence year.

The analysis scope is occurrence years 2020–2024.

Parent/child validation must occur before analytical-year filtering.

Month mapping:

- January → 1
- February → 2
- March → 3
- April → 4
- May → 5
- June → 6
- July → 7
- August → 8
- September → 9
- October → 10
- November → 11
- December → 12

A declared missing month may produce year precision.
A new non-empty month token is invalid and must not be converted to
year precision.

### 2.3 Severity classification

Source field:

`Degree of crash - detailed`

Registered categories:

| Native value | Severity code | Fatal crash |
|---|---|---:|
| `Fatal` | `FATAL` | true |
| `Serious Injury` | `SERIOUS_INJURY` | false |
| `Moderate Injury` | `MODERATE_INJURY` | false |
| `Minor/Other Injury` | `MINOR_OTHER_INJURY` | false |
| `Uncategorised Injury` | `UNCATEGORISED_INJURY` | false |
| `Non-casualty (towaway)` | `NON_CASUALTY_TOWAWAY` | false |
| native missing only | `__MISSING__` | NULL |

`Uncategorised Injury` remains a registered category even when it is not
observed in the selected snapshot.

A new non-empty severity token is undefined and blocks semantic acceptance.

### 2.4 Fatality and casualty counts

Fatality count:

`No. killed`

Casualty count:

`No. killed`
+
`No. seriously injured`
+
`No. moderately injured`
+
`No. minor-other injured`

If any required casualty component is unknown, `casualty_count` is NULL and
`casualty_eligible=false`.

Known zero components remain zero.

`No. of traffic units involved` is a relationship/count-reconciliation
field and is not part of the casualty calculation.

### 2.5 NSW metric eligibility

`fatal_crash_eligible=true` only when the severity category is registered
and the fatal/non-fatal interpretation is determinable.

`fatality_eligible=true` only when `No. killed` is a valid nonnegative
known count.

`casualty_eligible=true` only when all four casualty components are valid
nonnegative known counts.

Missing values remain NULL.

Undefined non-empty categories and invalid count values block rather than
being hidden through false eligibility flags.

### 2.6 Traffic Unit classification

Source field:

`TU type group`

Registered NSW Traffic Unit groups:

1. `Car/car derivative`
2. `Light truck`
3. `Heavy rigid truck`
4. `Articulated truck`
5. `Bus`
6. `Other motor vehicle`
7. `Motorcycle`
8. `Pedal cycle`
9. `Non-motorised vehicle`
10. `Pedestrian`
11. `Other or unknown`

`Pedestrian` is a valid NSW traffic-unit category.

`Other or unknown` is also a known publisher category and must not be
treated as missing.

A Traffic Unit row is count-eligible only when it has:

- a valid complete unit key;
- a valid parent Crash in the selected release scope; and
- a registered non-missing `TU type group`.

NSW Traffic Units must not be labelled as motor vehicles or pooled with
VIC Vehicle counts.

### 2.7 NSW location rule

The selected NSW Crash files contain latitude/longitude values, but A04
did not confirm field-specific CRS evidence for these coordinates.

Therefore the first official NSW projection uses:

- `latitude = NULL`
- `longitude = NULL`
- `location_crs = NULL`
- `location_record_id = NULL`
- `map_eligible = false`
- reason: `crs_unconfirmed`

Native coordinate text remains preserved in Raw.

Plausible coordinates or bounding-box checks do not establish CRS.

### 2.8 NSW status

A04 currently confirms:

- `contract_confirmed = true`
- `bundle_confirmed = true`
- unresolved blockers for enabled NSW Crash/TU products = none

C08 therefore treats these NSW semantic rules as confirmed inputs for
development of C03.

Any implementation conflict must be reported rather than resolved by
changing the A04 source semantics.
- traffic-unit / vehicle scopes.

Synthetic S0/S8 rules remain separate from official source semantics.


## 3. VIC semantic rules

### 3.1 Rule scope and status

Source:

`official_vic`

Release scope:

`vic_pinned_2020_2024_r1`

Restricted profile:

`vic-accident-only-2020-2024-v1`

Protocol:

`team-v1.1-vic-r1`

The VIC source remains under a restricted-use decision.

The current profile permits Accident-based measures only. Person/Vehicle-
dependent KPIs, relationship reports and official map products remain
unavailable.

C08 preserves the unresolved native definitions rather than inventing
cross-file or cross-state semantics.

### 3.2 Accident severity classification

Source field:

`SEVERITY`

Registered native values:

| Native value | Meaning | Fatal crash |
|---|---|---:|
| `1` | Fatal | true |
| `2` | Serious injury | false |
| `3` | Other injury | false |
| `4` | Non-injury | false |
| native missing | `__MISSING__` | NULL |

A new non-empty severity value is undefined and must block semantic
acceptance.

Missing severity must remain unknown rather than being converted to
non-fatal.

### 3.3 Fatality and casualty counts

Fatality count:

`NO_PERSONS_KILLED`

Casualty count:

`NO_PERSONS_KILLED`
+
`NO_PERSONS_INJ_2`
+
`NO_PERSONS_INJ_3`

`NO_PERSONS` is a participant count and must not be used as casualty count.

If any required casualty component is unknown, the derived casualty count
is NULL and `casualty_eligible=false`.

Known zero components remain zero.

Accident measures are derived from the Accident row and must not be
recomputed by joining Person rows.

### 3.4 VIC crash metric eligibility

`fatal_crash_eligible=true` only when `SEVERITY` is a registered,
determinable native category.

`fatality_eligible=true` only when `NO_PERSONS_KILLED` is a valid
nonnegative known count.

`casualty_eligible=true` only when all required casualty components are
valid nonnegative known counts.

The current restricted profile supports these Accident-based metrics for
the pinned 2020–2024 snapshot.

Person or Vehicle uncertainty must not be used to erase otherwise valid
Accident-level measures.

### 3.5 Person / Vehicle classification restrictions

The reviewed files contain:

- Vehicle type `21 / Electric Device`;
- Person role `16 / E-scooter Rider`.

These values are preserved as native observations but their complete
historical definitions and count-eligibility semantics remain unconfirmed.

They must not be treated as equivalent categories.

Under the current restricted profile:

- Person remains Raw/check-only;
- Person-dependent KPIs are unavailable;
- Vehicle-dependent KPIs are unavailable;
- all valid in-scope Vehicle projections must be retained for lineage/checking;
- every VIC unit must have `count_eligible=false`, regardless of vehicle category;
- record `definition_unconfirmed` in each unit's `quality_notes`.

Do not drop valid in-scope Vehicle projections or crashes to satisfy this
restriction. Invalid core values still block.

Undefined categories must remain visible and must not be silently mapped to
another known category.

### 3.6 Blank Person Vehicle references

Blank Person `VEHICLE_ID` values are distinct from non-empty unmatched
references.

For the exact frozen VIC files, the project restricted-use policy recognises
the file-bound case:

- `VEHICLE_ID=""`
- `ROAD_USER_TYPE="1"`
- `SEATING_POSITION="NA"`

as a team-defined non-association for this pinned profile only.

This rule does not establish general publisher nullability.

Other blank-reference patterns remain unresolved unless explicitly covered
by the frozen policy.

Non-empty unmatched references must remain preserved and must not be
repaired by creating Vehicle rows or artificial links.

### 3.7 Declared Person / Vehicle counts

Accident declarations and detail-row counts are preserved separately.

Known reviewed differences remain evidence; they are not repaired.

For the restricted profile:

- Person full-file count differences: 2
- Person 2020–2024 count differences: 0
- Vehicle full-file count differences: 5
- Vehicle 2020–2024 count differences: 3

Because compatible export/count scope is not fully confirmed, these
differences must not be converted into fabricated detail rows or automatic
tolerance.

### 3.8 VIC location eligibility

The VIC Node source does not have sufficient release-specific CRS evidence
for official map publication.

Therefore current official VIC projection uses:

- `latitude = NULL`
- `longitude = NULL`
- `location_crs = NULL`
- `location_record_id = NULL`
- `map_eligible = false`

Relevant reasons include:

- `crs_unconfirmed`
- `no_location`
- `location_conflict`
- `invalid_coordinate`

All Node observations remain in Raw.

Equivalent Node observations do not create additional crashes.

Conflicting coordinates must not be resolved by selecting the first row or
by averaging.

### 3.9 VIC semantic status

Current VIC status:

- restricted profile approved: true
- `bundle_confirmed = false`
- `contract_confirmed = false`

The restricted policy permits the specifically named Accident-based outputs
without claiming full four-resource compatibility.

Unknown definitions remain visible and version-bound.

Any new source bytes, new category, changed exception set or expanded output
scope requires a new reviewed rule version.


## 4. QLD semantic rules

> Status: adopted project rules for development.
> Final freeze remains subject to alignment with the latest D01 source evidence.

### 4.1 Rule scope

Source:

`official_qld`

The selected source is the pinned QLD crash-location CSV.

QLD is a crash-grain source. Aggregate `Count_Unit_*` fields remain
attributes of the crash source and must not be expanded into artificial
Person or Unit rows.

### 4.2 Crash identity and occurrence time

Crash identity uses:

`Crash_Ref_Number`

`Crash_Ref_Number` must be preserved as opaque native text.

The identifier must not be parsed to infer occurrence year, even where
publisher documentation suggests a year-based format.

Occurrence time uses:

- year: `Crash_Year`
- month: `Crash_Month`

`occurrence_date = NULL`.

Date precision is:

- `month` when the declared month is valid and known;
- `year` only under a contract-declared missing month.

Unknown non-empty month values must block rather than being converted to
year precision.

### 4.3 Severity classification

Source field:

`Crash_Severity`

Registered categories:

- `Fatal`
- `Hospitalisation`
- `Medical treatment`
- `Minor injury`
- `Property damage only`
- native missing → `__MISSING__`

`Fatal` maps to `is_fatal_crash=true`.

Other registered non-missing categories map to
`is_fatal_crash=false`.

A new non-empty category must not be silently mapped to false,
missing or another source category.

### 4.4 Fatality and casualty counts

Fatality count:

`Count_Casualty_Fatality`

Casualty count:

`Count_Casualty_Total`

The total casualty count must be checked against:

- `Count_Casualty_Fatality`
- `Count_Casualty_Hospitalised`
- `Count_Casualty_MedicallyTreated`
- `Count_Casualty_MinorInjury`

Unknown required inputs remain NULL and make the corresponding
metric ineligible.

Negative, malformed or unexplained inconsistent values block.

### 4.5 Aggregate unit attributes

The following fields remain crash-level aggregate source attributes:

- `Count_Unit_Car`
- `Count_Unit_Motorcycle_Moped`
- `Count_Unit_Truck`
- `Count_Unit_Bus`
- `Count_Unit_Bicycle`
- `Count_Unit_Pedestrian`
- `Count_Unit_Other`

C08 must not expand these counts into individual Person or Unit rows.

No Canonical unit rows may be fabricated from QLD aggregate counts.

### 4.6 QLD location rule

The source datum is documented as GDA2020.

However, the source-to-EPSG:4326 transformation operation has not yet been
validated for the official product.

Therefore:

- `latitude = NULL`
- `longitude = NULL`
- `location_crs = NULL`
- `location_record_id = NULL`
- `map_eligible = false`

Use reason:

`definition_unconfirmed`

The known source datum must not be relabelled as EPSG:4326 without an
executed and validated transformation.

### 4.7 D01 alignment status

These rules reflect the adopted team decisions available on
23 September 2026.

Before C08 QLD rules are frozen for official projection use, they must be
checked against the latest D01 source contract/evidence for exact rule
versions, missing-token treatment, coverage wording and remaining
source-specific limitations.

## 5. C08 implementation and freeze rules

### 5.1 Projection requirements

C03, C04 and C05 must apply the C08 rules before producing rows for
Vault loading.

Each projected crash must determine independently:

- `fatal_crash_eligible`
- `fatality_eligible`
- `casualty_eligible`
- `map_eligible`

Each projected real unit must determine:

- `count_eligible`

A false eligibility flag must have corresponding structured evidence in
`quality_notes`.

Unknown, unsupported or invalid values must not be repaired through defaults.

### 5.2 Blocking conditions

The following conditions block semantic acceptance:

- a new non-empty category not registered by the applicable versioned rule;
- an invalid required key;
- an invalid occurrence year/date;
- malformed or negative required counts;
- a derived count whose required known components do not reconcile;
- an enabled definition whose meaning remains unconfirmed.

A blocking value must not be made acceptable by setting all eligibility
flags to false.

### 5.3 Non-blocking unavailable measures

A crash may remain usable for other measures when one metric is genuinely
unavailable under a confirmed rule.

Examples include:

- known crash identity but unavailable fatality count;
- known fatality count but unavailable casualty total;
- valid non-spatial crash with unavailable official location.

Known zero remains zero; unavailable remains NULL.

### 5.4 Official location policy

For the current first official version:

- NSW official map: unavailable
- VIC official map: unavailable
- QLD official map: unavailable

Synthetic S0/S8 location rules remain separate and continue to support their
defined map scenarios.

Official map restrictions must not change synthetic acceptance expectations.

### 5.5 Source-rule ownership

C08 consumes source decisions without redefining them:

- NSW source semantics: A04
- VIC source semantics/restrictions: B06 + C02/C06 restricted policy
- QLD source semantics: D01

If implementation conflicts with an adopted source decision, C must record
the conflict rather than silently changing the source meaning.

### 5.6 Current freeze status

Shared rules: ready for implementation.

NSW:
- source contract confirmed;
- bundle confirmed;
- C08 rules ready for C03 implementation.

VIC:
- restricted profile adopted;
- full bundle/contract not confirmed;
- Accident-level restricted rules ready for C04 implementation;
- C07 remains responsible for Node/location handling.

QLD:
- adopted project rules available for development;
- final C08 freeze pending alignment with the latest D01 evidence.

C08 may be used for synthetic and source-specific projection development
while the remaining D01 alignment is tracked explicitly.
