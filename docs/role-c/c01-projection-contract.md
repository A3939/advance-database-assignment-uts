# C01: typed projection contract and fixtures

Revision 0.2, aligned with team v1.1. This defines the C-to-A row interface and
its synthetic examples. It does not implement C03–C10 or approve official data.

## 1. Contract and identity

Team **02, `canonical.crash` / `canonical.unit`**, supplies the field names,
types and NULL rules below. **04 §2 L2** requires all 24 crash fields and all
11 unit fields, with the same names and types. No field is supplied implicitly
by a database default. `I_crash` and `I_unit` are logical session rowsets;
their actual SQL names still need to be agreed with A06.

Under **05 §2**, A05 encodes native text components as PostgreSQL 16 JSON array
text: crash `[crash ID]`, unit `[crash ID, unit ID]`. For example, the expected
texts for `0001` and `0001/01` are `["0001"]` and `["0001", "01"]`.
These examples do not replace the shared SQL encoder. Preserve leading zeros,
case and valid surrounding characters; blank or whitespace-only keys block.

Snapshot identities are `(batch_id, source_id, release_scope, crash_key)` and
`(batch_id, source_id, release_scope, unit_key)`. Each unit carries its parent
`crash_key` in the same batch, source and release scope. `batch_id` comes from
the runner; source and release scope come from the frozen manifest. A resource
ID identifies an input resource, not an extra crash identity component.

Build the complete native parent-key set before filtering by occurrence year.
A child without a parent is an orphan, not an out-of-range row. Duplicate
business keys and invalid required keys block; do not keep an arbitrary row.

## 2. I_crash

One row per crash in its batch/source/release scope.

| Field | PostgreSQL type | NULL? | Rule |
|---|---|---|---|
| `batch_id` | `uuid` | No | Candidate batch from the run context. |
| `source_id` | `text` | No | Frozen source namespace; synthetic and official IDs differ. |
| `release_scope` | `text` | No | Frozen identity scope; S0 uses `s0`. |
| `crash_key` | `text` | No | Complete SQL-encoded native crash key. |
| `raw_record_id` | `uuid` | No | Selected primary crash Raw row. |
| `occurrence_year` | `integer` | No | Actual occurrence year, 1900–2100. |
| `occurrence_month` | `integer` | Yes | Known month, 1–12; otherwise NULL. |
| `occurrence_date` | `date` | Yes | Real day precision only; never invent a day. |
| `date_precision` | `text` | No | Exactly `year`, `month` or `day`. |
| `severity_raw` | `text` | Yes | Native severity; declared missing becomes NULL. |
| `severity_code` | `text` | No | Source-internal code; declared missing is `__MISSING__`. |
| `severity_definition_version` | `text` | No | Frozen definition version; S0 uses `syn-1`. |
| `is_fatal_crash` | `boolean` | Yes | Confirmed fatal-crash interpretation; otherwise NULL. |
| `fatality_count` | `integer` | Yes | Nonnegative known fatalities; unknown is NULL. |
| `casualty_count` | `integer` | Yes | Confirmed casualty scope; any required unknown part gives NULL. |
| `fatal_crash_eligible` | `boolean` | No | Independent eligibility for the fatal-crash measure. |
| `fatality_eligible` | `boolean` | No | Independent eligibility for the fatality-count measure. |
| `casualty_eligible` | `boolean` | No | Independent eligibility for the casualty-count measure. |
| `latitude` | `numeric(10, 7)` | Yes | Trusted WGS84 latitude, −90 to 90. |
| `longitude` | `numeric(10, 7)` | Yes | Trusted WGS84 longitude, −180 to 180. |
| `location_crs` | `text` | Yes | `EPSG:4326` only when supported; do not relabel unknown CRS. |
| `map_eligible` | `boolean` | No | Valid coordinates, CRS, relationship and uniqueness are supported. |
| `location_record_id` | `uuid` | Yes | Selected Raw location evidence for this crash. |
| `quality_notes` | `jsonb` | No | Object with the structured reasons described below. |

For `year`, month/date are NULL. For `month`, month is known and date is NULL.
For `day`, the date must agree with year and month. NSW/QLD S0 examples use
month/year precision; VIC uses day precision.

An eligible measure must have a non-NULL value under a confirmed definition.
The three eligibility flags are independent. Missing values stay NULL, while
known zero remains zero. Undefined nonempty categories or unconfirmed business
definitions block QA05; setting every flag false does not make them acceptable.
Declared missing tokens under a confirmed rule are different from new categories.

## 3. I_unit

One row per real source unit. QLD category counts produce no unit rows.

| Field | PostgreSQL type | NULL? | Rule |
|---|---|---|---|
| `batch_id` | `uuid` | No | Same candidate batch as the parent. |
| `source_id` | `text` | No | Same source as the parent. |
| `release_scope` | `text` | No | Same identity scope as the parent. |
| `unit_key` | `text` | No | SQL-encoded crash ID and unit ID, in that order. |
| `crash_key` | `text` | No | Full parent crash key. |
| `raw_record_id` | `uuid` | No | Selected real unit Raw row. |
| `unit_type_raw` | `text` | Yes | Original unit type. |
| `unit_type_code` | `text` | Yes | Source-internal mapped code; unmapped is NULL. |
| `statistical_scope` | `text` | No | Nonblank scope constrained by the source definition/version. |
| `count_eligible` | `boolean` | No | Type, parent and statistical scope must be confirmed. |
| `quality_notes` | `jsonb` | No | Classification and relationship evidence. |

An eligible unit needs a non-NULL type code. A missing parent still blocks
QA03/QA04 when `count_eligible=false`. An undefined nonempty type blocks QA05.
NSW traffic units and VIC vehicles keep separate scopes; no common vehicle
total is implied. Direction, movement, declared counts and injury components
remain in Raw or permitted `source_extra`, not replacement interface columns.

## 4. Lineage, location and quality notes

`raw_record_id` references the immutable row returned by B08. Its source must
match, and its file must belong to the current selection. Raw identity remains
resource + file SHA256 + parser version + native row locator, separately from
business identity.

Direct NSW/QLD coordinates may use the crash Raw row as `location_record_id`.
VIC uses the selected Node Raw row matched on `ACCIDENT_NO + NODE_ID`. All Node
observations remain in Raw. Compare complete, finite, in-range coordinates as
exact decimals **before rounding**. All matching observations must agree and
have confirmed CRS/relationships. Equivalent observations select a representative
by file hash, parser version and numeric native locator. Do not average conflicts
or silently drop partly invalid observations.

Without a trusted location, retain the crash and set latitude, longitude, CRS
and location Raw ID to NULL; set `map_eligible=false` and record the reason.
Only QA07 can be `limited`. A true Node-to-Accident orphan still blocks QA04.

Under **05 §4**, `quality_notes` is an object with optional `fields`, `location`
and `references` members. Each `fields` item has `field`, `reason_code`,
`raw_token` (possibly NULL) and `contract_version`. `location` has `reason_code`,
`candidate_raw_record_ids`, `resolution` and `evidence_ref`. The reason vocabulary
is `missing`, `unmapped`, `definition_unconfirmed`, `invalid_coordinate`,
`crs_unconfirmed`, `location_conflict`, `no_location`. Every false eligibility
needs corresponding evidence. Notes do not turn invalid core values into passes.

## 5. Fixtures and checks

[`c01_projection.py`](../../tests/fixtures/c01/c01_projection.py) contains the
six expected S0 crashes, six real units and all four Node observations from
**04 §4**. It uses `syn_nsw/syn_vic/syn_qld`, `s0`, `syn-1`, and the fictional
F/I/N/missing definitions. It does not alter the shared native S0 files.

Python values use UUID, date, Decimal, bool, int, dict and None to represent
the SQL types. UUIDs are placeholders, not database lineage evidence. Real
integration substitutes the IDs returned by B08. Literal keys illustrate the
contract; this file neither generates production keys nor proves A05 serialization.

| Case | Expected behaviour |
|---|---|
| F01 | Normal V1 crash with full fields. |
| F02 | N2: missing values stay NULL, three measure flags false; QA05 pass, QA07 limited. |
| F03 | A separate V1-based candidate with an undefined nonempty category: shape valid, QA05 block. |
| F04A/B | Native ID `0001` stays distinct across NSW and VIC. |
| F05 | Real VIC unit with the full matching parent identity. |
| F06 | Structurally complete orphan: QA03 and QA04 block; no invented parent. |
| F07 | V1 uses separate Node lineage; both equivalent observations remain. |
| F08 | Q1 uses the same Raw row for crash and location. |
| F09 | V2 remains present with conflicting Node evidence and no trusted location. |
| F10 | QLD crash retained, zero individual QLD units. |
| F11 | Known fatal-crash/fatality measures remain eligible when casualties are unknown. |

F cases run independently. Do not concatenate them into one batch: several
intentionally reuse an S0 identity. `expected_shape_valid` and `expected_qa`
are test metadata outside the 24/11 fields. Negative candidates must not be
fed to A06 as valid output. QA labels in the fixtures are expectations, not
persisted QA results or executed SQL checks.

Run from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_c01_projection.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tests/fixtures/c01/c01_projection.py
```

The pytest file independently checks the field/type/NULL contract, S0 values,
independent eligibility, identity scope, parent counterexamples, location
lineage and explicit QA expectations. The script alone only checks field shape.
See [the validation receipt](c01-validation-2026-09-22.json) for the actual run.

## 6. Integration and remaining work

Use B10's existing `(connection, context)` callback convention, documented in
the [runner guide](https://github.com/A3939/advance-database-assignment-uts/blob/3185b841a86a4b8f9c998636766efbf6332efa8c/docs/runner.md#module-interface).
Callbacks use the supplied connection and never commit, roll back or close it.
Their return values are ignored. C must create the agreed session rowsets for
A on that connection; the fixture lists are not a runner callback implementation.

Integration needs a verified A05 SQL signature and encoding test results. A06/C
must agree the rowset names and how A consumes them. Satellite attributes follow
**04 §2 L3**: exclude batch/source/release/self-key/primary Raw ID; unit attributes
retain `crash_key`, with explicit JSON nulls and proper value types. C09 must read
the selected Satellite observations, not rebuild Canonical directly from Raw.

The fixed field and identity rules are settled in team v1.1. Official mappings,
compatible releases and Node CRS still need source evidence; see [C02](c02-vic-person-node-review.md).
This revision supplies a contract and tested examples, not acceptance of C's
SQL projection, Vault integration, QA persistence or a complete build.
