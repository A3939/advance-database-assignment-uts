# C01 — Typed Projection Contract and Fixtures

> Internal team design / development contract  
> Role: C  
> Status: Draft v0.1

## 1. Purpose

C01 defines the fixed projection interfaces used before Vault loading.

The contract defines:

- `l_crash` with exactly 24 fields;
- `l_unit` with exactly 11 fields;
- PostgreSQL-compatible types;
- NULL rules;
- identity scope;
- Raw lineage;
- eligibility/reason handling;
- fixed development fixtures; and
- logical invocation conventions for downstream modules.

The physical business-key encoding is not defined here and remains an A05 responsibility.

## 2. Raw lineage contract

Raw lineage uses `raw.record.raw_record_id` as the row-level reference to an immutable native source row.

`primary_raw_record_id` identifies the Raw record from which the projected crash or unit is primarily derived.

`location_raw_record_id` identifies the Raw record supplying the location evidence used by a crash projection.

Where the primary crash record and location evidence come from the same Raw record, the proposed convention is:

`location_raw_record_id = primary_raw_record_id`

Where location is supplied by a separate source resource, such as VIC Node, `location_raw_record_id` references that Node Raw record separately.

File hash, parser version and native row locator remain authoritative in `raw.record` and are not duplicated unnecessarily in the projection contract.

## 3. Identity semantics

### 3.1 Crash identity

A native crash identifier is not globally unique.

Crash identity must retain:

- source namespace; and
- native source crash identifier.

The same native crash identifier appearing in different sources must represent distinct crash identities.

The exact serialization or hashing method is owned by A05.

### 3.2 Unit identity

A unit identity must retain:

- source namespace;
- full parent crash identity; and
- native source unit identifier.

A unit identifier must not be interpreted independently of its parent crash.

### 3.3 Raw identity versus business identity

Business identity and Raw row identity are separate concepts.

Business identity represents the crash or real unit.

Raw lineage is retained through `raw_record_id`.

## 4. `l_crash` projection contract

### 4.1 Contract status

The following 24-field contract is **Draft v0.1 for team review**.

C01 defines the field semantics, types, NULL behaviour and identity
components. The physical business-key encoding is owned by A05 and
is therefore not fixed in this version.

| # | Field | PostgreSQL type | NULL? | Meaning / rule |
|---:|---|---|---|---|
| 1 | `source_id` | `text` | No | Source namespace registered in `meta.source`, e.g. the selected NSW/VIC/QLD source. |
| 2 | `primary_resource_id` | `text` | No | Native crash resource from which the primary crash projection is derived. |
| 3 | `source_crash_id` | `text` | No | Native crash identifier preserved as text. It is not globally unique. |
| 4 | `occurrence_year` | `smallint` | No | Actual crash occurrence year used for analytical scope. Reporting/publication year must not substitute for occurrence year. |
| 5 | `occurrence_month` | `smallint` | Yes | Occurrence month where supported. NULL means unavailable, not zero. |
| 6 | `occurrence_date` | `date` | Yes | Exact occurrence date only where the source genuinely provides day precision. No synthetic day is created. |
| 7 | `date_precision` | `text` | No | Precision of the occurrence time representation, e.g. `DAY`, `MONTH` or `YEAR`. |
| 8 | `source_severity` | `text` | Yes | Original jurisdiction-specific severity value/code. It must not be replaced by a harmonised value. |
| 9 | `definition_version` | `text` | Yes | Version/reference for the source definition or classification interpretation used by the projection. |
| 10 | `fatality_count` | `integer` | Yes | Number of known fatalities where supported by the source definition. NULL means unknown/unavailable and must not be replaced by zero. |
| 11 | `serious_injury_count` | `integer` | Yes | Source-supported serious-injury count where a confirmed definition exists. |
| 12 | `other_injury_count` | `integer` | Yes | Other source-supported injury count where a confirmed mapping/definition exists. No unsupported cross-state equivalence is implied. |
| 13 | `casualty_count` | `integer` | Yes | Source-supported total killed/injured count. If required components are unknown, the derived total remains NULL. |
| 14 | `declared_unit_count` | `integer` | Yes | Crash-level unit/vehicle count declared by the source where available; used for reconciliation, not to create artificial units. |
| 15 | `declared_person_count` | `integer` | Yes | Crash-level participant count where available and definitionally supported. |
| 16 | `latitude` | `numeric` | Yes | Selected location latitude where location evidence is usable. Missing location does not remove the crash. |
| 17 | `longitude` | `numeric` | Yes | Selected location longitude where location evidence is usable. |
| 18 | `crs_code` | `text` | Yes | Confirmed CRS identifier only. Plausible coordinates alone must not establish a CRS. |
| 19 | `primary_raw_record_id` | `uuid` | No | Row-level lineage to the primary `raw.record` used to derive the crash. |
| 20 | `location_raw_record_id` | `uuid` | Yes | Row-level lineage to the `raw.record` supplying location evidence. May differ from the primary row, e.g. VIC Node. |
| 21 | `metric_eligible` | `boolean` | No | Whether the crash is currently eligible for the governed non-spatial crash metrics defined by C08. |
| 22 | `metric_reason` | `text` | Yes | Reason for metric limitation/ineligibility. NULL when no reason is required. |
| 23 | `map_eligible` | `boolean` | No | Whether the crash location is eligible for governed spatial/map output. |
| 24 | `map_reason` | `text` | Yes | Reason for spatial limitation/ineligibility, e.g. missing location, conflicting observations or unconfirmed CRS. |

### 4.2 Identity rule

The semantic crash identity is based on:

- `source_id`; and
- `source_crash_id`.

The same native crash identifier in different source namespaces must
represent different crash identities.

If A05 determines that release-specific identity is also required for
a source whose identifiers are not stable across releases, the A05
business-key encoding must incorporate the required release/Raw scope
without changing the source identifier itself.

`primary_raw_record_id` is lineage, not the crash business identifier.

### 4.3 Raw lineage rule

`primary_raw_record_id` references `raw.record.raw_record_id`.

`location_raw_record_id` references the Raw row supplying the location
evidence used by the projection.

Proposed convention:

- NSW crash/location from the same Raw row:
  `location_raw_record_id = primary_raw_record_id`
- VIC Accident + separate Node location:
  `location_raw_record_id` references the selected VIC Node Raw row
- QLD crash/location from the same Raw row:
  `location_raw_record_id = primary_raw_record_id`
- no trusted matching location:
  `location_raw_record_id = NULL`

The file hash, parser version and native row locator remain authoritative
in `raw.record` and are not duplicated into `l_crash`.

### 4.4 NULL rules

C01 uses NULL to represent information that is unavailable, unknown or
not supported at the common projection grain.

The projection must not:

- replace unknown counts with zero;
- invent occurrence days from month-only data;
- infer a CRS from plausible coordinate values;
- manufacture missing Person, Vehicle or Node records; or
- hide an unresolved mapping through a default value.

Eligibility fields and reason fields make analytical limitations explicit.

## 5. `l_unit` contract

TBD — exactly 11 fields.

## 6. Fixed fixtures

The fixtures must cover at least:

- normal valid crash;
- optional NULL values;
- unknown/unmapped values;
- same native crash ID across different sources;
- valid real unit with correct parent;
- invalid/wrong parent identity;
- separate primary Raw and location Raw lineage;
- QLD crash with no invented `l_unit` rows.

## 7. Logical call convention

The following are logical interface names for development and are not assumed to be implemented functions yet:

- NSW projection → `l_crash`, `l_unit`
- VIC projection → `l_crash`, `l_unit`
- QLD projection → `l_crash`, empty `l_unit`

Actual module names, arguments and versions must be registered when C03–C05 are implemented.

## 8. Open items / dependencies

- A05 must define the shared physical business-key encoding.
- A06 should review the lineage fields and expected Vault-loader input.
- B10 should review the projection call convention and fixture format.
- `l_crash` 24 fields and `l_unit` 11 fields still require team review before the contract is frozen.
