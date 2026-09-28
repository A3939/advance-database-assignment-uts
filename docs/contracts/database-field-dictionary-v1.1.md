# Complete Database Field Dictionary

**17 physical tables and 129 fields. Design baseline v1.1; implementation pending.** No table-creation code is supplied. Module exchange formats, JSON content, business-key encoding and acceptance decisions are governed jointly by [04](04-Team-Contracts-and-Acceptance.md) and [05](05-Sources-and-Mappings.md).

“No” in the NULL column includes the NOT NULL implied by a primary key. “None” means no DEFAULT is declared. Every PK/UNIQUE automatically creates a unique B-tree index; “Additional index” lists further design requirements. Composite keys must be interpreted and joined as complete column groups.

Types, primary and foreign keys, uniqueness, checks and indexes are design specifications for the responsible members to implement. A check allowing NULL does not enforce a non-null requirement.

## meta.source

One source namespace. This is the current intake registry; historical display names are frozen in the batch manifest and source dimension.

| Field | Type | NULL | Default | Key role | Meaning |
|---|---|---|---|---|---|
| source_id | text | No | None | PK | Stable source namespace; official and synthetic sources use different IDs. |
| jurisdiction_code | text | No | None | — | State or jurisdiction code; not restricted to a fixed list of states. |
| source_name | text | No | None | — | Currently registered source name; not a label for historical queries. |
| publisher | text | No | None | — | Source publisher. |

**Constraints and indexes**

- PK: `source_id`.
- CHECK: `btrim(source_id) <> ''`.
- Additional indexes: none; PK/UNIQUE indexes are implicit.

## meta.resource

One logical resource within a source. Format, native fields, contracts and mappings are maintained in configuration and frozen in the batch manifest.

| Field | Type | NULL | Default | Key role | Meaning |
|---|---|---|---|---|---|
| resource_id | text | No | None | PK; UNIQUE component | Resource ID unique across the configuration catalogue; not limited to seven resources. |
| source_id | text | No | None | FK→meta.source.source_id; UNIQUE component | Owning source namespace. |
| resource_role | text | No | None | — | Configured resource role distinguishing primary crashes, real units, persons and nodes. |
| entity_kind | text | No | None | — | Entity kind supported in phase one; person_raw and node_raw have no separate Canonical entities. |

**Constraints and indexes**

- PK: `resource_id`.
- UNIQUE: `resource_id, source_id`.
- FK: `(source_id) → meta.source(source_id)`.
- CHECK: `entity_kind IN ('crash', 'unit', 'person_raw', 'node_raw')`.
- Additional indexes: none; PK/UNIQUE indexes are implicit.

## meta.batch

One attempt to build a complete snapshot of all enabled sources. Raw archives and registration commit first; successful derived data and the current pointer commit together.

| Field | Type | NULL | Default | Key role | Meaning |
|---|---|---|---|---|---|
| batch_id | uuid | No | None | PK; UNIQUE component | Run-attempt identity; a failed retry creates a new UUID without resuming stages. |
| dataset_kind | text | No | None | UNIQUE component | official or synthetic; current pointers and queries are isolated within the same database. |
| input_fingerprint | text | No | None | — | SHA256 of the frozen file bundle, source release identities, hashes, parsers, full contracts and mappings with versions, code and analysis scope. |
| manifest | jsonb | No | None | — | Immutable JSON containing complete frozen sources, files, rules, analysis and required_checks; never substitute the latest configuration. |
| status | text | No | 'running' | UNIQUE component | running, succeeded or failed; no_change is a runner response, not a fourth database status. |
| started_at | timestamptz | No | now() | — | Registration time, stored in UTC. |
| finished_at | timestamptz | Yes | None | — | Successful or failed completion time. |
| error_details | jsonb | Yes | None | — | Errors, failed rules and raw-row evidence saved independently after build rollback; do not fabricate successful checks that were rolled back. |

**Constraints and indexes**

- PK: `batch_id`.
- UNIQUE: `batch_id, dataset_kind, status`.
- CHECK: `dataset_kind IN ('official', 'synthetic')`.
- CHECK: `input_fingerprint ~ '^[0-9a-f]{64}$'`.
- CHECK: `jsonb_typeof(manifest) = 'object'`.
- CHECK: `status IN ('running', 'succeeded', 'failed')`.
- CHECK: `(status = 'running' AND finished_at IS NULL) OR (status <> 'running' AND finished_at IS NOT NULL)`.
- CHECK: `status <> 'failed' OR error_details IS NOT NULL`.
- Additional index: `batch_fingerprint_idx`, method `btree`, columns `(dataset_kind, input_fingerprint, status)`.

## meta.current_release

One current complete-snapshot pointer per dataset kind. A page resolves batch_id once and binds every report to it.

| Field | Type | NULL | Default | Key role | Meaning |
|---|---|---|---|---|---|
| dataset_kind | text | No | None | PK; FK→meta.batch.dataset_kind | Separate official or synthetic query space. |
| batch_id | uuid | No | None | FK→meta.batch.batch_id | Current successful batch; the composite foreign key enforces both dataset kind and successful status. |
| batch_status | text | No | 'succeeded' | FK→meta.batch.status | Fixed to succeeded; a declarative foreign key prevents references to unsuccessful batches. |
| switched_at | timestamptz | No | now() | — | Time of the transactional pointer switch. |

**Constraints and indexes**

- PK: `dataset_kind`.
- FK: `(batch_id, dataset_kind, batch_status) → meta.batch(batch_id, dataset_kind, status)`.
- CHECK: `dataset_kind IN ('official', 'synthetic')`.
- CHECK: `batch_status = 'succeeded'`.
- Additional indexes: none; PK/UNIQUE indexes are implicit.

## raw.record

One native row extracted from a resource file by a specific parser. Original file bytes are stored in an append-only archive; payload retains every field.

| Field | Type | NULL | Default | Key role | Meaning |
|---|---|---|---|---|---|
| raw_record_id | uuid | No | None | PK; UNIQUE component | Raw-row UUID; a repeated locator returns the existing ID and must have an identical payload. |
| resource_id | text | No | None | FK→meta.resource.resource_id; UNIQUE component | Logical resource; the composite foreign key with source_id enforces the same source. |
| source_id | text | No | None | FK→meta.resource.source_id; UNIQUE component | Source namespace. |
| file_sha256 | text | No | None | UNIQUE component | SHA256 of original file bytes; batch.manifest.files binds the file to its source release. |
| parser_version | text | No | None | UNIQUE component | Native extraction parser version; performs no business transformation. |
| row_locator | text | No | None | UNIQUE component | Reliable locator, such as sheet name and original row number; never a temporary number assigned after sorting. |
| payload | jsonb | No | None | — | All native fields with native string or NULL values; preserves persons, nodes and QLD category counts in full. |
| ingested_at | timestamptz | No | now() | — | Time the native row was first received. |

**Constraints and indexes**

- PK: `raw_record_id`.
- UNIQUE: `resource_id, file_sha256, parser_version, row_locator`.
- UNIQUE: `raw_record_id, source_id`.
- FK: `(resource_id, source_id) → meta.resource(resource_id, source_id)`.
- CHECK: `file_sha256 ~ '^[0-9a-f]{64}$'`.
- CHECK: `btrim(parser_version) <> '' AND btrim(row_locator) <> ''`.
- CHECK: `jsonb_typeof(payload) = 'object'`.
- Additional index: `raw_file_idx`, method `btree`, columns `(source_id, resource_id, file_sha256, parser_version)`.

## rv.hub_crash

One complete crash business key within a source and release identity scope. IDs are not assumed stable across releases; no cross-state entity merging is claimed.

| Field | Type | NULL | Default | Key role | Meaning |
|---|---|---|---|---|---|
| source_id | text | No | None | PK; FK→meta.source.source_id | Source namespace. |
| release_scope | text | No | None | PK | Configured release scope in which identities are valid; conservatively treat each release as independent. |
| crash_key | text | No | None | PK | Canonical JSON-array text containing all crash-key components, preserving leading zeros and case. |
| first_seen_batch_id | uuid | No | None | FK→meta.batch.batch_id | First successful build referencing this identity; a failed transaction rolls back the Hub insertion too. |

**Constraints and indexes**

- PK: `source_id, release_scope, crash_key`.
- FK: `(source_id) → meta.source(source_id)`.
- FK: `(first_seen_batch_id) → meta.batch(batch_id)`.
- CHECK: `btrim(release_scope) <> '' AND btrim(crash_key) <> ''`.
- Additional indexes: none; PK/UNIQUE indexes are implicit.

## rv.sat_crash

One selected structured crash projection per batch. Complete batch snapshots replace complex effective dating and per-field hash-difference mechanisms.

| Field | Type | NULL | Default | Key role | Meaning |
|---|---|---|---|---|---|
| batch_id | uuid | No | None | PK; FK→meta.batch.batch_id | Build version. |
| source_id | text | No | None | PK; FK→rv.hub_crash.source_id; FK→raw.record.source_id | Source namespace. |
| release_scope | text | No | None | PK; FK→rv.hub_crash.release_scope | Source release identity scope. |
| crash_key | text | No | None | PK; FK→rv.hub_crash.crash_key | Complete crash business key. |
| raw_record_id | uuid | No | None | FK→raw.record.raw_record_id | Selected primary crash raw row; all unselected rows remain in raw. |
| attributes | jsonb | No | None | — | This version's structured projection, source differences, classification version and location evidence; raw.payload remains authoritative for all native fields. |

**Constraints and indexes**

- PK: `batch_id, source_id, release_scope, crash_key`.
- FK: `(batch_id) → meta.batch(batch_id)`.
- FK: `(source_id, release_scope, crash_key) → rv.hub_crash(source_id, release_scope, crash_key)`.
- FK: `(raw_record_id, source_id) → raw.record(raw_record_id, source_id)`.
- CHECK: `jsonb_typeof(attributes) = 'object'`.
- Additional indexes: none; PK/UNIQUE indexes are implicit.

## rv.hub_unit

One complete key for a real traffic unit within a source release identity scope. Local identifiers include the parent crash key; QLD category counts never generate fictitious units.

| Field | Type | NULL | Default | Key role | Meaning |
|---|---|---|---|---|---|
| source_id | text | No | None | PK; FK→meta.source.source_id | Source namespace. |
| release_scope | text | No | None | PK | Source release identity scope. |
| unit_key | text | No | None | PK | Canonical JSON-array text of the complete composite unit key. |
| first_seen_batch_id | uuid | No | None | FK→meta.batch.batch_id | First build batch. |

**Constraints and indexes**

- PK: `source_id, release_scope, unit_key`.
- FK: `(source_id) → meta.source(source_id)`.
- FK: `(first_seen_batch_id) → meta.batch(batch_id)`.
- CHECK: `btrim(release_scope) <> '' AND btrim(unit_key) <> ''`.
- Additional indexes: none; PK/UNIQUE indexes are implicit.

## rv.sat_unit

One structured projection snapshot of a real unit per batch.

| Field | Type | NULL | Default | Key role | Meaning |
|---|---|---|---|---|---|
| batch_id | uuid | No | None | PK; FK→meta.batch.batch_id | Build version. |
| source_id | text | No | None | PK; FK→rv.hub_unit.source_id; FK→raw.record.source_id | Source namespace. |
| release_scope | text | No | None | PK; FK→rv.hub_unit.release_scope | Source release identity scope. |
| unit_key | text | No | None | PK; FK→rv.hub_unit.unit_key | Complete real-unit key. |
| raw_record_id | uuid | No | None | FK→raw.record.raw_record_id | Real-unit raw row. |
| attributes | jsonb | No | None | — | Historical structured attributes and evidence for native types, statistical scope and other definitions. |

**Constraints and indexes**

- PK: `batch_id, source_id, release_scope, unit_key`.
- FK: `(batch_id) → meta.batch(batch_id)`.
- FK: `(source_id, release_scope, unit_key) → rv.hub_unit(source_id, release_scope, unit_key)`.
- FK: `(raw_record_id, source_id) → raw.record(raw_record_id, source_id)`.
- CHECK: `jsonb_typeof(attributes) = 'object'`.
- Additional indexes: none; PK/UNIQUE indexes are implicit.

## rv.link_crash_unit

Exactly one parent crash relationship per real unit per batch. Composite foreign keys prevent joins across sources, release scopes or batches.

| Field | Type | NULL | Default | Key role | Meaning |
|---|---|---|---|---|---|
| batch_id | uuid | No | None | PK; FK→rv.sat_crash.batch_id; FK→rv.sat_unit.batch_id; UNIQUE component | Relationship version. |
| source_id | text | No | None | PK; FK→rv.sat_crash.source_id; FK→rv.sat_unit.source_id; UNIQUE component | Shared source namespace. |
| release_scope | text | No | None | PK; FK→rv.sat_crash.release_scope; FK→rv.sat_unit.release_scope; UNIQUE component | Shared release identity scope. |
| unit_key | text | No | None | PK; FK→rv.sat_unit.unit_key; UNIQUE component | Complete real-unit key. |
| crash_key | text | No | None | FK→rv.sat_crash.crash_key; UNIQUE component | Complete parent crash key. |

**Constraints and indexes**

- PK: `batch_id, source_id, release_scope, unit_key`.
- UNIQUE: `batch_id, source_id, release_scope, unit_key, crash_key`.
- FK: `(batch_id, source_id, release_scope, crash_key) → rv.sat_crash(batch_id, source_id, release_scope, crash_key)`.
- FK: `(batch_id, source_id, release_scope, unit_key) → rv.sat_unit(batch_id, source_id, release_scope, unit_key)`.
- Additional index: `link_parent_idx`, method `btree`, columns `(batch_id, source_id, release_scope, crash_key)`.

## canonical.crash

One crash within a source release scope per batch. Types and eligibility are explicit; unknowns remain NULL. Raw or Satellite retains native and unharmonised semantics.

| Field | Type | NULL | Default | Key role | Meaning |
|---|---|---|---|---|---|
| batch_id | uuid | No | None | PK; FK→rv.sat_crash.batch_id | Complete snapshot version. |
| source_id | text | No | None | PK; FK→rv.sat_crash.source_id; FK→raw.record.source_id; FK→raw.record.source_id | Source namespace. |
| release_scope | text | No | None | PK; FK→rv.sat_crash.release_scope | Source release identity scope. |
| crash_key | text | No | None | PK; FK→rv.sat_crash.crash_key | Complete crash key. |
| raw_record_id | uuid | No | None | FK→raw.record.raw_record_id | Lineage to the primary crash raw row. |
| occurrence_year | integer | No | None | — | Crash occurrence year; never replace with report year. The batch configuration determines the permitted analysis range. |
| occurrence_month | integer | Yes | None | — | Evidence-supported occurrence month; NULL when only the year is known. |
| occurrence_date | date | Yes | None | — | Actual crash date only at day precision; never invent day 1 for month-level data. |
| date_precision | text | No | None | — | year, month or day; constrained to agree with the date and month fields. |
| severity_raw | text | Yes | None | — | Native severity text or code; NULL when missing. |
| severity_code | text | No | None | — | Source-specific mapped code; missing may use explicit __MISSING__. Not directly comparable across states. |
| severity_definition_version | text | No | None | — | Severity definition version for this source; matches the dimension and frozen mapping. |
| is_fatal_crash | boolean | Yes | None | — | Fatal-crash determination under a confirmed source definition; NULL when missing or undefined. |
| fatality_count | integer | Yes | None | — | Number of fatalities; unknown is NULL. Fatal-crash counts cannot substitute for it. |
| casualty_count | integer | Yes | None | — | Required casualty count; usable only after confirming its inclusion scope. Persons involved cannot substitute for casualties. |
| fatal_crash_eligible | boolean | No | FALSE | — | Eligibility for the fatal-crash metric; false requires missing-value or definition evidence in quality_notes. |
| fatality_eligible | boolean | No | FALSE | — | Eligibility for the fatality-count metric; aggregate only when true. |
| casualty_eligible | boolean | No | FALSE | — | Eligibility for the casualty metric under the source definition; cross-source comparability requires separate confirmation. |
| latitude | numeric(10, 7) | Yes | None | — | Confirmed WGS84 latitude; may be NULL without a trustworthy unique location while retaining the crash. |
| longitude | numeric(10, 7) | Yes | None | — | Confirmed WGS84 longitude. |
| location_crs | text | Yes | None | — | Location coordinate reference system; phase-one maps accept only EPSG:4326. No coordinate-transformation reference implementation is supplied. |
| map_eligible | boolean | No | FALSE | — | True only when location, CRS, relationship and uniqueness are confirmed; does not affect other eligible metrics. |
| location_record_id | uuid | Yes | None | FK→raw.record.raw_record_id | Trusted location raw row; direct coordinates may reference the crash row, while VIC may reference a node_raw row. |
| quality_notes | jsonb | No | CAST('{}' AS jsonb) | — | JSON evidence for missingness, eligibility, location matching and conflicting raw-row locators; does not replace typed metrics. |

**Constraints and indexes**

- PK: `batch_id, source_id, release_scope, crash_key`.
- FK: `(batch_id, source_id, release_scope, crash_key) → rv.sat_crash(batch_id, source_id, release_scope, crash_key)`.
- FK: `(raw_record_id, source_id) → raw.record(raw_record_id, source_id)`.
- FK: `(location_record_id, source_id) → raw.record(raw_record_id, source_id)`.
- CHECK: `occurrence_year BETWEEN 1900 AND 2100`.
- CHECK: `occurrence_month IS NULL OR occurrence_month BETWEEN 1 AND 12`.
- CHECK: `date_precision IN ('year', 'month', 'day')`.
- CHECK: `(date_precision = 'year' AND occurrence_month IS NULL AND occurrence_date IS NULL) OR (date_precision = 'month' AND occurrence_month IS NOT NULL AND occurrence_date IS NULL) OR (date_precision = 'day' AND occurrence_month IS NOT NULL AND occurrence_date IS NOT NULL AND pg_catalog.extract('year', occurrence_date) = occurrence_year AND pg_catalog.extract('month', occurrence_date) = occurrence_month)`.
- CHECK: `fatality_count IS NULL OR fatality_count >= 0`.
- CHECK: `casualty_count IS NULL OR casualty_count >= 0`.
- CHECK: `NOT fatal_crash_eligible OR is_fatal_crash IS NOT NULL`.
- CHECK: `NOT fatality_eligible OR fatality_count IS NOT NULL`.
- CHECK: `NOT casualty_eligible OR casualty_count IS NOT NULL`.
- CHECK: `(latitude IS NULL) = (longitude IS NULL)`.
- CHECK: `latitude IS NULL OR latitude BETWEEN -90 AND 90`.
- CHECK: `longitude IS NULL OR longitude BETWEEN -180 AND 180`.
- CHECK: `NOT map_eligible OR (latitude IS NOT NULL AND longitude IS NOT NULL AND location_crs IS NOT NULL AND location_crs = 'EPSG:4326' AND location_record_id IS NOT NULL)`.
- CHECK: `jsonb_typeof(quality_notes) = 'object'`.
- Additional index: `crash_year_idx`, method `btree`, columns `(batch_id, source_id, occurrence_year)`.

## canonical.unit

One real-unit detail per batch, analysed under its source definition. No common cross-state unit fact or expansion of QLD category counts.

| Field | Type | NULL | Default | Key role | Meaning |
|---|---|---|---|---|---|
| batch_id | uuid | No | None | PK; FK→rv.link_crash_unit.batch_id; FK→canonical.crash.batch_id | Complete snapshot version. |
| source_id | text | No | None | PK; FK→rv.link_crash_unit.source_id; FK→canonical.crash.source_id; FK→raw.record.source_id | Source namespace. |
| release_scope | text | No | None | PK; FK→rv.link_crash_unit.release_scope; FK→canonical.crash.release_scope | Source release identity scope. |
| unit_key | text | No | None | PK; FK→rv.link_crash_unit.unit_key | Complete unit key including the required parent-crash components. |
| crash_key | text | No | None | FK→rv.link_crash_unit.crash_key; FK→canonical.crash.crash_key | Parent crash in the same batch, source and identity scope. |
| raw_record_id | uuid | No | None | FK→raw.record.raw_record_id | Real-unit raw row. |
| unit_type_raw | text | Yes | None | — | Native unit type, retained even if unconfirmed. |
| unit_type_code | text | Yes | None | — | Analytically usable source-specific type code; NULL when unmapped. |
| statistical_scope | text | No | None | — | Statistical scope determined by the source definition and version, such as traffic units or vehicles; comparability is not assumed. |
| count_eligible | boolean | No | FALSE | — | Whether this unit contributes to basic counts within this source and statistical scope. |
| quality_notes | jsonb | No | CAST('{}' AS jsonb) | — | Evidence for unit missingness, classification and relationships. |

**Constraints and indexes**

- PK: `batch_id, source_id, release_scope, unit_key`.
- FK: `(batch_id, source_id, release_scope, unit_key, crash_key) → rv.link_crash_unit(batch_id, source_id, release_scope, unit_key, crash_key)`.
- FK: `(batch_id, source_id, release_scope, crash_key) → canonical.crash(batch_id, source_id, release_scope, crash_key)`.
- FK: `(raw_record_id, source_id) → raw.record(raw_record_id, source_id)`.
- CHECK: `btrim(statistical_scope) <> ''`.
- CHECK: `NOT count_eligible OR unit_type_code IS NOT NULL`.
- CHECK: `jsonb_typeof(quality_notes) = 'object'`.
- Additional index: `unit_parent_idx`, method `btree`, columns `(batch_id, source_id, release_scope, crash_key)`.

## dw.dim_source

One frozen display dimension per source per batch. meta.source maintains current registration; this table preserves historical report labels and release meaning.

| Field | Type | NULL | Default | Key role | Meaning |
|---|---|---|---|---|---|
| batch_id | uuid | No | None | PK; FK→meta.batch.batch_id | Frozen snapshot version. |
| source_id | text | No | None | PK; FK→meta.source.source_id | Source namespace. |
| source_name | text | No | None | — | Source name frozen from this batch's manifest. |
| jurisdiction_code | text | No | None | — | Jurisdiction frozen from this batch's manifest. |
| release_label | text | No | None | — | Recorded source release label; ingestion time cannot substitute for the release. |
| release_scope | text | No | None | — | Release identity scope used by this batch's source keys. |

**Constraints and indexes**

- PK: `batch_id, source_id`.
- FK: `(batch_id) → meta.batch(batch_id)`.
- FK: `(source_id) → meta.source(source_id)`.
- Additional indexes: none; PK/UNIQUE indexes are implicit.

## dw.dim_month

One Gregorian calendar year-month; a shared static dimension with no inferred crash day.

| Field | Type | NULL | Default | Key role | Meaning |
|---|---|---|---|---|---|
| month_id | integer | No | None | PK | Integer YYYYMM key; the fact foreign key is NULL for year-only crashes. |
| calendar_year | integer | No | None | UNIQUE component | Gregorian calendar year. |
| calendar_month | integer | No | None | UNIQUE component | Gregorian calendar month from 1 to 12. |

**Constraints and indexes**

- PK: `month_id`.
- UNIQUE: `calendar_year, calendar_month`.
- CHECK: `calendar_month BETWEEN 1 AND 12`.
- CHECK: `month_id = ((calendar_year * 100) + calendar_month)`.
- Additional indexes: none; PK/UNIQUE indexes are implicit.

## dw.dim_severity

One native severity category per source per batch. No common scale that assumes cross-state comparability.

| Field | Type | NULL | Default | Key role | Meaning |
|---|---|---|---|---|---|
| batch_id | uuid | No | None | PK; FK→dw.dim_source.batch_id | Snapshot version freezing the definition. |
| source_id | text | No | None | PK; FK→dw.dim_source.source_id | Owning source; must be included in grouping. |
| severity_code | text | No | None | PK | Source-specific category or explicit missing code. |
| severity_label | text | No | None | — | Display label for this version of the source category. |
| definition_version | text | No | None | — | Verified or restricted definition version. |
| definition_text | text | No | None | — | Source definition and non-comparability or missingness notes from the frozen mapping. |

**Constraints and indexes**

- PK: `batch_id, source_id, severity_code`.
- FK: `(batch_id, source_id) → dw.dim_source(batch_id, source_id)`.
- Additional indexes: none; PK/UNIQUE indexes are implicit.

## dw.fact_crash

One analytical fact per crash per batch. COUNT(*) counts crashes; fatal crashes and fatalities are separate metrics, reconciled strictly against Canonical.

| Field | Type | NULL | Default | Key role | Meaning |
|---|---|---|---|---|---|
| batch_id | uuid | No | None | PK; FK→canonical.crash.batch_id; FK→dw.dim_source.batch_id; FK→dw.dim_severity.batch_id | Complete snapshot version fixed for the page. |
| source_id | text | No | None | PK; FK→canonical.crash.source_id; FK→dw.dim_source.source_id; FK→dw.dim_severity.source_id | Composite source-dimension key component. |
| release_scope | text | No | None | PK; FK→canonical.crash.release_scope | Source crash identity scope. |
| crash_key | text | No | None | PK; FK→canonical.crash.crash_key | Unique crash key; joining units must never multiply facts. |
| occurrence_year | integer | No | None | — | Crash occurrence year; includes year-only crashes in annual statistics. |
| month_id | integer | Yes | None | FK→dw.dim_month.month_id | Trustworthy occurrence month; NULL when unknown. Monthly reports display month coverage. |
| severity_code | text | No | None | FK→dw.dim_severity.severity_code | Source-defined severity dimension code. |
| is_fatal_crash | boolean | Yes | None | — | Fatal-crash determination, counted according to eligibility. |
| fatality_count | integer | Yes | None | — | Fatality count, summed according to eligibility; unknowns are not replaced with zero. |
| casualty_count | integer | Yes | None | — | Casualty count under a confirmed definition, summed according to eligibility. |
| fatal_crash_eligible | boolean | No | None | — | Eligibility for the fatal-crash metric. |
| fatality_eligible | boolean | No | None | — | Eligibility for the fatality-count metric. |
| casualty_eligible | boolean | No | None | — | Eligibility for the casualty-count metric. |
| latitude | numeric(10, 7) | Yes | None | — | Trusted latitude copied from Canonical for map SQL. |
| longitude | numeric(10, 7) | Yes | None | — | Trusted longitude copied from Canonical. |
| map_eligible | boolean | No | None | — | Map eligibility; crashes without coordinates remain in other statistics. |

**Constraints and indexes**

- PK: `batch_id, source_id, release_scope, crash_key`.
- FK: `(batch_id, source_id, release_scope, crash_key) → canonical.crash(batch_id, source_id, release_scope, crash_key)`.
- FK: `(batch_id, source_id) → dw.dim_source(batch_id, source_id)`.
- FK: `(batch_id, source_id, severity_code) → dw.dim_severity(batch_id, source_id, severity_code)`.
- FK: `(month_id) → dw.dim_month(month_id)`.
- CHECK: `month_id IS NULL OR (month_id / 100) = occurrence_year`.
- CHECK: `fatality_count IS NULL OR fatality_count >= 0`.
- CHECK: `casualty_count IS NULL OR casualty_count >= 0`.
- CHECK: `NOT fatal_crash_eligible OR is_fatal_crash IS NOT NULL`.
- CHECK: `NOT fatality_eligible OR fatality_count IS NOT NULL`.
- CHECK: `NOT casualty_eligible OR casualty_count IS NOT NULL`.
- CHECK: `NOT map_eligible OR (latitude IS NOT NULL AND longitude IS NOT NULL)`.
- Additional index: `fact_trend_idx`, method `btree`, columns `(batch_id, source_id, occurrence_year, month_id)`.

## qa.check_result

One rule-object result within a batch. Every required rule also has an object_key=batch summary. Missing results block publication; unexecuted checks never count as pass.

| Field | Type | NULL | Default | Key role | Meaning |
|---|---|---|---|---|---|
| batch_id | uuid | No | None | PK; FK→meta.batch.batch_id | Build batch being checked; after failed-transaction rollback, evidence is retained by an independent failure-recording process. |
| rule_id | text | No | None | PK | Readable rule identifier; publication requires the complete frozen rule set. |
| object_key | text | No | None | PK | Check-object identity; batch identifies the required rule summary. Resource or raw-row objects may also be recorded. |
| result | text | No | None | — | pass, limited or block; unimplemented or unexecuted required checks block explicitly or through missing results. |
| affected_count | bigint | No | None | — | Number of affected rows or objects; warnings must not conceal errors. |
| actual | jsonb | No | None | — | JSON of measured values, ranges or states. |
| expected | jsonb | No | None | — | JSON of expectations or constraints frozen for this batch. |
| evidence | jsonb | No | None | — | Issue evidence, definition notes and necessary raw-file or row locators; limited also requires a documented resolution. |
| raw_record_id | uuid | Yes | None | FK→raw.record.raw_record_id | Primary affected raw row; additional locators go in an evidence array. |
| checked_at | timestamptz | No | now() | — | Time this check was executed. |

**Constraints and indexes**

- PK: `batch_id, rule_id, object_key`.
- FK: `(batch_id) → meta.batch(batch_id)`.
- FK: `(raw_record_id) → raw.record(raw_record_id)`.
- CHECK: `result IN ('pass', 'limited', 'block')`.
- CHECK: `affected_count >= 0`.
- CHECK: `result = 'pass' OR evidence <> CAST('{}' AS jsonb)`.
- Additional index: `qa_result_idx`, method `btree`, columns `(batch_id, result, rule_id)`.

