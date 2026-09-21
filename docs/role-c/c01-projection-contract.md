# C01 — Typed Projection Contract and Fixtures

> **Internal team design / development contract — not final submission prose.**  
> Role: **C**  
> Status: **Draft v0.1**  
> Purpose: provide a fixed early-development interface for A06/B10 and later source projections C03–C05.

## 1. Purpose and scope

C01 defines the fixed projection interfaces used before Vault loading.

The contract defines:

- `l_crash` with exactly 24 fields;
- `l_unit` with exactly 11 fields;
- PostgreSQL-compatible types;
- NULL rules;
- semantic identity scope;
- Raw lineage;
- eligibility/reason handling;
- fixed synthetic fixtures; and
- logical invocation conventions for downstream modules.

C01 defines **identity semantics**, not the physical key encoding. The shared serialization/hash/business-key encoding remains an A05 responsibility.

`l_crash` represents one projected crash at the common crash grain.

`l_unit` represents one **real individual source unit** linked to a real parent crash. Aggregate QLD unit-category counts must not be expanded into artificial `l_unit` rows.

Person and Node remain Raw/runtime-check inputs and are not introduced as new C01 projection entities.

---

## 2. Raw lineage contract

The authoritative immutable native-row store is `raw.record`.

Relevant B08 Raw fields are:

- `raw_record_id uuid PRIMARY KEY`
- `resource_id text NOT NULL`
- `source_id text NOT NULL`
- `file_sha256 text NOT NULL`
- `parser_version text NOT NULL`
- `row_locator text NOT NULL`
- `payload jsonb NOT NULL`
- `ingested_at timestamptz NOT NULL`

Native Raw identity is:

`resource_id + file_sha256 + parser_version + row_locator`

The loader reuses the existing `raw_record_id` for an identical Raw identity and rejects a changed payload under the same identity.

### 2.1 Primary Raw lineage

`primary_raw_record_id` references the `raw.record.raw_record_id` from which the projected crash or unit is primarily derived.

### 2.2 Location Raw lineage

`location_raw_record_id` identifies the Raw row supplying the location evidence used by a crash projection.

Proposed convention:

- NSW crash/location from the same Raw row:  
  `location_raw_record_id = primary_raw_record_id`
- VIC Accident with separate Node location:  
  `location_raw_record_id` references the selected VIC Node Raw row
- QLD crash/location from the same Raw row:  
  `location_raw_record_id = primary_raw_record_id`
- no trusted matching location:  
  `location_raw_record_id = NULL`

File hash, parser version and row locator remain authoritative in `raw.record`; they are not duplicated unnecessarily into the projection contracts.

---

## 3. Identity semantics

### 3.1 Crash identity

A native crash ID is not globally unique.

The semantic crash identity must retain at least:

- `source_id`;
- `primary_resource_id`; and
- `source_crash_id`.

The same native crash ID appearing in different sources/resources must remain a distinct crash identity.

If A05 determines that a release-specific component is required for a source whose published IDs are not stable across releases, that scope must be included by A05 without overwriting the native source ID.

### 3.2 Unit identity

A unit identity must retain:

- `source_id`;
- `primary_resource_id`;
- the complete parent crash identity; and
- `source_unit_id`.

A unit identifier must not be interpreted independently of its parent crash.

### 3.3 Raw identity versus business identity

Business identity and Raw row identity are separate concepts.

- Business identity identifies the crash or real unit.
- `raw_record_id` identifies the immutable native source row used as lineage evidence.

The exact physical business-key serialization or hashing method is owned by A05.

---

## 4. `l_crash` projection contract

### 4.1 Contract status

The following 24-field contract is **Draft v0.1 for team review**.

| # | Field | PostgreSQL type | NULL? | Meaning / rule |
|---:|---|---|---|---|
| 1 | `source_id` | `text` | No | Source namespace registered in `meta.source`. |
| 2 | `primary_resource_id` | `text` | No | Native crash resource from which the primary crash projection is derived. |
| 3 | `source_crash_id` | `text` | No | Native crash identifier preserved as text; not globally unique. |
| 4 | `occurrence_year` | `smallint` | No | Actual crash occurrence year used for analytical scope. |
| 5 | `occurrence_month` | `smallint` | Yes | Occurrence month where genuinely available. |
| 6 | `occurrence_date` | `date` | Yes | Exact occurrence date only where the source supplies day precision. |
| 7 | `date_precision` | `text` | No | Temporal precision, e.g. `DAY`, `MONTH`, `YEAR`. |
| 8 | `source_severity` | `text` | Yes | Original jurisdiction-specific severity value/code; never overwritten by a harmonised value. |
| 9 | `definition_version` | `text` | Yes | Source definition/classification version or reference used to interpret the row. |
| 10 | `fatality_count` | `integer` | Yes | Known fatalities under the supported source definition. |
| 11 | `serious_injury_count` | `integer` | Yes | Serious-injury count where a confirmed source definition exists. |
| 12 | `other_injury_count` | `integer` | Yes | Other source-supported injury count; no unsupported cross-state equivalence implied. |
| 13 | `casualty_count` | `integer` | Yes | Source-supported killed/injured total; remains NULL when required components are unknown. |
| 14 | `declared_unit_count` | `integer` | Yes | Source-declared crash-level unit/vehicle count where available; for reconciliation only. |
| 15 | `declared_person_count` | `integer` | Yes | Source-declared participant count where available and definitionally supported. |
| 16 | `latitude` | `numeric` | Yes | Selected latitude only where location evidence is usable. |
| 17 | `longitude` | `numeric` | Yes | Selected longitude only where location evidence is usable. |
| 18 | `crs_code` | `text` | Yes | Confirmed CRS only; plausible coordinate values do not establish CRS. |
| 19 | `primary_raw_record_id` | `uuid` | No | Raw lineage to the primary native crash row. |
| 20 | `location_raw_record_id` | `uuid` | Yes | Raw lineage to the source row supplying location evidence. |
| 21 | `metric_eligible` | `boolean` | No | Whether the crash is eligible for governed non-spatial metrics under C08. |
| 22 | `metric_reason` | `text` | Yes | Reason for metric limitation/ineligibility; NULL when no reason is required. |
| 23 | `map_eligible` | `boolean` | No | Whether the location is eligible for governed spatial/map use. |
| 24 | `map_reason` | `text` | Yes | Reason for spatial limitation/ineligibility. |

### 4.2 `l_crash` NULL rules

The projection must not:

- replace unknown counts with zero;
- invent a crash day from month-only data;
- infer CRS from plausible coordinates;
- invent missing Person, Vehicle or Node rows;
- hide unresolved mappings through default values.

Unknown/unavailable information remains explicit through NULL and/or the applicable eligibility/reason fields.

---

## 5. `l_unit` projection contract

### 5.1 Contract status

The following 11-field contract is **Draft v0.1 for team review**.

`l_unit` contains only complete **real individual units** supported by a source resource. It does not represent crash-level aggregate category counts.

| # | Field | PostgreSQL type | NULL? | Meaning / rule |
|---:|---|---|---|---|
| 1 | `source_id` | `text` | No | Source namespace registered in `meta.source`. |
| 2 | `primary_resource_id` | `text` | No | Native unit resource supplying this unit row. |
| 3 | `source_crash_id` | `text` | No | Native ID of the real parent crash. |
| 4 | `source_unit_id` | `text` | No | Native individual unit/vehicle identifier preserved as text. |
| 5 | `source_unit_type` | `text` | Yes | Original source unit/vehicle type value or label; not a harmonised category. |
| 6 | `direction` | `text` | Yes | Source-supported travel/initial direction where available. |
| 7 | `movement` | `text` | Yes | Source-supported manoeuvre/vehicle movement where available. |
| 8 | `primary_raw_record_id` | `uuid` | No | Raw lineage to the native individual unit row. |
| 9 | `parent_crash_raw_record_id` | `uuid` | No | Raw lineage to the real parent crash row used for the relationship. |
| 10 | `metric_eligible` | `boolean` | No | Whether this real unit is eligible for the governed unit-level use defined by C08. |
| 11 | `metric_reason` | `text` | Yes | Reason for unit-level limitation/ineligibility; NULL when no reason is required. |

### 5.2 Parent identity rule

The `l_unit` parent is identified semantically by:

- `source_id`;
- the applicable crash resource/source scope; and
- `source_crash_id`.

A unit row must not be projected when its required real parent crash cannot be established under the approved source relationship rules.

A05 owns the shared physical encoding of the full unit and parent crash business keys.

### 5.3 QLD rule

The selected QLD source is crash-level and contains aggregate unit-category counts rather than individual unit rows.

Therefore:

- QLD may produce `l_crash` rows;
- QLD produces **zero `l_unit` rows** from the selected source;
- aggregate `Count_Unit_*` values remain crash-level/source-specific evidence;
- no synthetic or expanded individual QLD units may be created.

---

## 6. Fixed development fixtures

C01 fixtures must be independent of the unfinished C03–C05 source readers/projections.

At minimum, the fixed fixture set must cover:

| Fixture | Scenario | Expected contract behaviour |
|---|---|---|
| F01 | Normal valid crash | One valid `l_crash` row with primary Raw lineage. |
| F02 | Optional source value missing | NULL remains explicit; no silent default. |
| F03 | Unknown/unmapped classification | Source value remains visible; eligibility/reason identifies the limitation. |
| F04 | Same native crash ID in different sources | Two distinct semantic crash identities. |
| F05 | Valid real unit with correct parent | One `l_unit` row linked to the correct parent identity and Raw rows. |
| F06 | Unit with missing/wrong parent | No invented parent; invalid relationship is surfaced according to the applicable QA rule. |
| F07 | VIC-style separate location lineage | `primary_raw_record_id` and `location_raw_record_id` point to different Raw rows. |
| F08 | Same-row location lineage | `location_raw_record_id = primary_raw_record_id`. |
| F09 | Missing/untrusted location | Crash retained; map eligibility false/limited with an explicit reason. |
| F10 | QLD crash with aggregate unit counts | `l_crash` exists; no artificial `l_unit` rows are emitted. |

Fixture values should be fixed and deterministic so A06/B10 tests can develop against them before C03–C05 are finished.

---

## 7. Logical call convention

The following are logical development interfaces only. They are **not claims that installed functions/modules already exist**.

Conceptually:

- NSW projection → `l_crash`, `l_unit`
- VIC projection → `l_crash`, `l_unit`
- QLD projection → `l_crash`, empty `l_unit`

The implementation registered later by C03–C05 must document:

- actual module/function/query name;
- arguments;
- output version;
- contract version;
- expected exception behaviour.

B10 should review the runner-facing call convention before C01 is frozen.

---

## 8. Open items and dependencies

### A05 — business-key encoding

Pending:

- exact serialization/hash/key format;
- any required release-specific component for unstable source IDs;
- parent crash key encoding for `l_unit`.

C01 defines the semantic components only.

### A06 — Vault loader review

A06 should confirm:

- whether both Raw lineage UUIDs are sufficient for Vault loading;
- whether `parent_crash_raw_record_id` should remain explicit in `l_unit`;
- whether the fixture representation is convenient for early Vault-loader tests.

### B10 — runner review

B10 should confirm:

- fixture format;
- logical invocation convention;
- how projection outputs are supplied to the shared transaction/run boundary.

### C08 — eligibility semantics

C08 must define the governed rules for:

- classification validity;
- missing values;
- count eligibility;
- metric eligibility/reasons;
- map eligibility/reasons.

The C01 fields reserve the interface for these decisions but do not pre-approve unresolved source semantics.

### Team review before freeze

The following remain **proposed** until reviewed:

- exact 24-field `l_crash` contract;
- exact 11-field `l_unit` contract;
- `location_raw_record_id = primary_raw_record_id` convention for same-row locations;
- common injury/count fields where jurisdiction definitions differ;
- fixture serialization/format.

---

## 9. Freeze criteria for C01

C01 can be frozen as Version 1 when:

- `l_crash` contains exactly 24 explicitly defined fields;
- `l_unit` contains exactly 11 explicitly defined fields;
- every field has a type and NULL rule;
- crash and unit identity scope is documented;
- A05 has no conflict with the semantic identity components;
- A06 accepts the loader-facing lineage/fixture contract;
- B10 accepts the runner-facing convention;
- fixtures cover NULL/unknown, same-ID-across-source, parent identity, location lineage, eligibility/reasons and no-invented-QLD-unit cases;
- unresolved official source semantics remain explicit rather than hidden by defaults.
