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

## 4. `l_crash` contract

TBD — exactly 24 fields.

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
