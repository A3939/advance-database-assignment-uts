# Autonomous adapter interface (canonical-v2)


Codex responses may be compact views with explicitly omitted JSON Pointers.
Use `read_task_state(kind="tool_result", step_id=..., pointer="/exact/path",
max_chars=4000)` for exact evidence; follow `next_offset` to finish a selected
value. JSON Pointer escapes `/` as `~1` and `~` as `~0`. Invalid selectors fail.
Full result files remain available. `evidence/facts.json` and `evidence/index.json`
provide durable observations and retrieval references; `evidence/issues.json`
contains `progress` and `diagnostics`. Repeated downloads, changed URLs/hashes
and quote wording do not resolve an issue. Use its scoped blockers and full
step references to change the diagnostic approach, then test the corresponding
gate. Three repeated gate observations advise replanning; the existing no-progress
stop budget still applies. Partial unverified evidence is conservatively not
counted as progress. Omitted values are unknown, not permission
to discard fields. Never submit a compact view as a contract or a full quote.

The Python worker is the only durable orchestrator. Model output is untrusted.
An adapter is task-local Python exporting `adapt(ctx)`. The isolated runner calls
it with `AdapterContext` from an immutable image, without network, keys or DB.
The adapter can use Python/SQLite, read input tables, inspect docs and write task
output; it cannot edit the trusted QA or publisher.

## Source contract

`contract_version: canonical-v2` and the following JSON shape:

```json
{
  "contract_version": "canonical-v2",
  "source": {
    "source_id": "stable_dataset_identity",
    "jurisdiction": ["AU"],
    "publisher": "Named official publisher",
    "title": "Dataset title",
    "dataset_url": "https://official.gov.au/dataset",
    "licence": "Official stated licence",
    "grain": "crash",
    "coverage": {"from": "2020-01-01", "to": "2024-12-31"}
  },
  "update": {"mode": "snapshot", "from": "2020-01-01", "to": "2024-12-31"},
  "resources": [
    {"role": "crash", "file_id": "admitted-file-id", "grain": "crash", "key": ["ID"], "table": {"format": "csv"},
     "mapping": {
       "date": {"field": "DATE", "formats": ["%Y-%m-%d"], "precision": "day"},
       "severity": {"field": "SEVERITY", "categories": {
         "Fatal": {"code": "fatal", "label": "Fatal", "is_fatal_crash": true}
       }},
       "fatalities": {"field": "KILLED"},
       "casualties": {"sum_fields": ["KILLED", "INJURED"]}
     }
    }
  ],
  "relations": [],
  "evidence": {
    "source_identity": [{"document_id": "doc-sha", "quote": "Exact supporting text"}],
    "grain": [], "coverage_update": [], "date": [], "severity": [], "counts": [], "relations": [], "geography": []
  },
  "definitions": {"fatalities": "Published definition or unavailable reason", "casualties": "Published definition or unavailable reason"},
  "documents": []
}
```

The example above is a fictional schema illustration, not evidence of the
current upload's state, identity, fields, meanings or time coverage.
Resources use `grain: crash | unit | casualty | observation`. Every row retains
its complete source key and row locator. A key is not inferred from row numbers.
Source identity differs from jurisdiction; multiple datasets may cover one or
many jurisdictions. Prefer stable official dataset identities to filenames.
`source_id` must match `[a-z][a-z0-9_]{1,79}`; use underscores, not URL/URN
punctuation, and reserve `official_`/`syn_` for trusted legacy flows.
`jurisdiction` is a nonempty list using `NSW`, `VIC`, `QLD`, `SA`, `ACT`, `TAS`,
`WA`, `NT`, or `AU` (a national dataset), not ISO-prefixed codes such as `AU-ACT`.

Relations are `{child, parent, fields:[child field names], allow_blank:false}`,
matching the parent resource's complete key in declared order.
An optional key (`allow_blank:true`) must have every component missing; a
partially supplied composite key is still invalid. `inspect_relations` reports
duplicate parent groups and potential join row multiplication; its structural
measurements do not grant lookup, source meaning or publication authority.
Unit/casualty resources must connect to crash when a crash resource is provided. No generated
foreign key or repaired orphan. Unit records may declare `mapping.unit_type`
as a column name; casualties `mapping.injury` with field/categories, where each
category has `is_fatal:boolean|null`. Optional `mapping.unit_key` names unit FK
fields when a casualty→unit relation is declared.

Source category evidence supports scoped ArcGIS coded-value domains and
single-field unique-value renderers. Cite the actual domain/renderer entry,
not only the field descriptor. `uniqueValueGroups` takes precedence over legacy
`uniqueValueInfos`; a default symbol cannot authorize other values. Composite
fields or expressions need a reviewed transformation capability. Preserve native
labels, keep unfamiliar outcomes null, and do not set `standard_code` without
a separately supported harmonization rule. Different source meanings must not
share a canonical category code; same-label aliases may share one. These checks
do not establish common mortality windows, injury comparability or person counts.
When no supported structured dictionary is present, the current text grounding
is reported as `legacy_text_scope`, not as new structured classification proof.

Date spec: `field` and explicit `formats`, or `kind: epoch_ms|epoch_s` with field,
or `year_field`, optional `month_field`, explicit `month_values` for text months.
Precision is day/month/year; timezone/raw date are retained. Multiple formats
may be allowed only when every parse gives the same date. Unknown/ambiguous
dates do not silently fall back. `null_values` is an explicit list of missing
raw strings, default only empty/null. Counts are nonnegative integers; missing
counts remain null. A count spec is `{field}` or `{sum_fields:[...]}`; a missing
spec means unsupported, not zero. `declared_units`/`declared_casualties` count
specs trigger trusted cross-table reconciliation, according to source scope.
Multi-field sums need an applicable official addition definition, not only
evidence that each column exists. The current bounded recognizer accepts a whole
literal document line or a scoped structured field description such as
`Total casualties = "field A" + "field B"`, cited under `evidence.counts`.
That example is syntax, not permission to invent a publisher statement. All
operands must match the upload fields or their grounded official names; aliases
of the same count cannot be added twice. Known conflicting definitions remain
blocking even if omitted from citations. Arbitrary prose, inferred disjointness
or model-written confirmation is not this implementation's supported proof.
Prefer an explicitly documented source total when available. Do not remove a
supported metric merely to pass the gate. Single-field sums remain identity
projections. Duplicate operands, more than 32 operands, invalid fields and totals
over 2^31-1 are rejected. Any missing component keeps the total unknown; raw
missing-value markers are not applied a second time to a computed result.
Unit resources may also declare `mapping.declared_casualties` to verify their
complete casualty children against source-declared unit-level counts.
Every uploaded CSV/Excel/GeoJSON data resource must be assigned a grain; omitting
an inconvenient child table is not an acceptable exclusion policy.

Canonical WGS84 coordinates use 8 decimal places (approximately millimetre
resolution), to make macOS/Linux transforms reproducible. Raw coordinates remain
exact. Independent QA compares these canonical values exactly; adapters must not
apply their own tolerance or change the original coordinates.

Geography, when documented, uses `mapping.geography: {x_field,y_field,crs,
region_field?,region_type?,precision?}`. CRS must be recognized by pyproj and
evidence is required. Preserve raw coordinates/CRS and transform to EPSG:4326.
Without reliable geo evidence, preserve raw attributes but disable map support.

Geographic operations use `offline-transform-plan-v1`. Host and a separate
read-only executor-image probe independently select a fixed, non-ballpark 2-D
operation; missing preferred grids block instead of falling back. The probe
does not mount raw files or adapter code. QA records both PROJ/pyproj/database
receipts and the immutable executor image, compares exact operation/axis/grid
hashes, then replays every row. Packaged grids carry hashes; network downloads,
dynamic/epoch-dependent and compound/3-D transforms are not supported here.
Each available canonical point includes `transform_operation_sha256`. Coordinates
must fall in the source CRS and operation areas as well as the broad Australian
domain. Eight decimal places describe storage resolution, not positional
accuracy. The current illustrative-map policy records the database's operation
accuracy estimate (unknown is null) and offers no fixed accuracy guarantee;
survey-grade or source positional accuracy requires separate evidence/policy.
The Agent cannot supply its own operation string or upgrade that accuracy claim.

Observation resources use `mapping.metrics` with named count specs (`crashes`,
`fatal_crashes`, `fatalities`, `casualties`), date and optional region fields.
They remain aggregate observations, never expanded to synthetic crashes.

Update mode is snapshot, partition or incremental. Snapshot coverage must be
explicitly supported; narrower uploads cannot silently delete wider history.
Partition includes the exact from/to range. Incremental upserts stable complete
keys. The trusted publisher composes final data and checks retained history.
Retained-history updates also require unchanged meaning-bearing mappings,
definitions, null conventions and known structured official field definitions.
Upload IDs, resource order, date-format order and sum-operand order may change;
repeated operands, date/CRS/category/count changes may not be merged silently.
`UPDATE_SEMANTICS_UNPROVEN` requires a complete evidenced snapshot or a distinct
reviewed source version. It is not proof that the source is corrupt. Model-written
compatibility flags and newer document timestamps do not authorize a merge.
Automatic equivalence for renamed fields or rewritten definitions is not yet
implemented, even when those changes might be legitimate.

Publication compares actual old/new canonical identities after composition, in
the same transaction. Missing crash/unit/casualty/observation records need a
host-derived complete-resource proof; equal totals, declared dates, timestamps
or `complete:true` are insufficient. This applies to every update mode, so a
partition cannot bypass the snapshot guard. Incremental updates retain absent
stable keys. Unsupported proof formats are a system capability blocker, not a
request for the user to assert that the upload is complete.

The current positive proof path is the exact `fetch_arcgis_layer` v2 export:
authorized metadata, scoped all-ID queries before/after, count and every page
are hash-checked, membership is reconciled, and the derived input bytes are
reconstructed. To remove records, this live-layer export must have been observed
after the source version being replaced was published; a historical receipt
cannot silently roll back later membership. Recency alone is still insufficient.
The input must match that export exactly; downloading another
file cannot replace the user's upload as evidence. See `source_completeness` in
preflight. This proves observed current layer membership only, not historical
coverage, stable IDs across versions or absence of field edits during retrieval.
Other publisher file/partition completeness proofs are not yet implemented.

ArcGIS export v2 preserves page CRS on each geometry instead of relabelling all
pages with the layer extent CRS. Explicit per-geometry references remain local;
if the response omits a reference, only an actual explicit outSR request may be
used. Quantized geometry requires a supported decoder and is currently blocked.
Source coordinate values and any returned Z/M values are not rewritten.

For resource-specific dictionaries, a resource may propose `source_url`, an exact
publisher-distributed resource URL (or the declared dataset URL). It selects a
scope, not proof of the uploaded file's provenance. QA restricts CKAN metadata_url
documents to that resource, and supports root Schema.org JSON-LD `about` plus
day-resolution `temporalCoverage` start/end intervals. This conservative policy
treats the end as exclusive and requires coverage of the entire declared upload
range. Coarse/open periods and unsupported contexts produce capability diagnostics.
Document `version` is recorded, not assumed to be a data-file version; dateModified
never resolves a contradiction. Unscoped legacy documents retain an explicitly
unspecified dataset scope. Embedded HTML JSON-LD and arbitrary version semantics
are not a complete applicability implementation. Run preflight before execution.

`documents` is injected by the trusted evidence tool registry, not accepted
merely because the model supplies an URL/hash. Admission verifies local
document bytes, official origin or official catalog resource chain, quoted text
and applicable capabilities. A model cannot supply `confirmed:true` authority.

For structured evidence call `read_document(file_id, locator=...)`. Supported
locators are `{"kind":"json-pointer","pointer":"/columns/1"}`,
`{"kind":"xml-expanded-path","segments":[["root",0],["{namespace}definition",0]]}`,
and `{"kind":"pdf-text-range","page_from":1,"page_to":2,"start":0,"end":120}`.
XML child indexes are zero-based among all element children; PDF pages are
one-based and character offsets index the selected pages joined by two newlines.
Copy the returned `reference` into the appropriate `evidence` list. It pins the
registered document ID, original SHA-256, locator and resolved value hash; the
returned quote may be omitted. QA resolves the original bytes again, rejects
wrong hashes/locators/values and checks the cited field's scope. A valid reference
does not grant authority or prove unrelated fields. Record arrays and cached
personal rows remain inaccessible through the documentation tool. Legacy exact
text quotes continue to work for unstructured documents.

## Python SDK

`ctx.iter_rows(role)` yields `(locator, raw_dict)` with strings/null scalars (or
JSON typed scalars) and retained raw extensions. `ctx.project(role, locator,row)`
creates a canonical row following the contract. `ctx.emit(grain,row)` writes
bounded JSONL, and `ctx.exclude(role,locator,reason)` records explicit exclusions.
`ctx.contract`, `ctx.mode`, `ctx.input_paths`, `ctx.work_dir` are available.

Minimal adapter (generated by the Agent after determining source semantics):

```python
def adapt(ctx):
    for resource in ctx.contract["resources"]:
        role = resource["role"]
        for locator, raw in ctx.iter_rows(role):
            ctx.emit(resource["grain"], ctx.project(role, locator, raw))
```

This is a real versioned executable adapter. More complex Python is permitted
inside the same sandbox; trusted QA independently re-reads sources, validates
lineage, computes expected values, keys, relationships and source totals, then
checks exact candidate equality and aggregate/database reconciliation.
Adapter-provided QA, counts or success flags are not admission evidence.

Artifacts are `crashes.jsonl`, `units.jsonl`, `casualties.jsonl`,
`observations.jsonl`, `exclusions.jsonl` plus a runner envelope. A canonical row
includes `record_id`, `canonical_id`, `source_id`, `jurisdiction`, `resource_role`,
`raw_key`, `row_locator`, original fields under `extensions`, date/precision/raw,
severity/definitions, nullable metrics and `availability` reasons. Unit and
casualty rows retain `crash_id`; observation rows remain a distinct table.
QA and publisher attach real batch/release IDs; generated code cannot assign them.

`isolated_executor.run_python(code, files, work_dir, mode='sample'|'full',
check_cancelled=..., limits=None, source_contract=None)` returns
`{run_id,status,output_dir,artifacts,stdout,stderr,usage,image,code_sha256,...}`.
Every run has fresh output, read-only copied input and immutable code. No host
fallback is permitted. `trusted_qa.validate_candidate(run,source_contract,files,
adapter_sha256,work_dir,check_cancelled=None)` produces the existing publication
result plus canonical-v2 capabilities/admission/update metadata on full success.
Sample validation is diagnostic only and cannot authorize publication.

The Next trusted model gateway accepts authenticated worker requests
`{input:[ResponsesItems],tools:[function specs]}` and returns
`{id,output,usage,status,model}`. It owns the API key, instructions, tool allowlist
and byte/time bounds. The worker persists calls and decisions and handles retry;
the browser does not own the model call or task lifetime.

An absent source severity classification is allowed: omit `mapping.severity`
and explain its absence in `definitions.severity`. The crash count remains
available, while native/standard severity and the fatal-crash flag remain
unsupported/unknown. Do not omit documented source categories merely because
no harmonized national classification is available; preserve those native
categories with exact official field evidence.

### Casualty completeness evidence

`definitions.casualty_table_complete: true` alone does not authorize equality. `evidence.casualty_scope` must bind `resource_role` and the exact table key through an affirmative official declaration, such as “The complete casualty register uses EVENT_ID and PERSON_NO.” Supported declarations are checked as whole sentences; extra keys, negations, examples and conditional prose do not establish completeness. Use hash-pinned `locator` references or exact text quotes. Scoped JSON root descriptions are supported; nested neighbouring resource descriptions are not. Known complete/partial contradictions remain blocking even when a citation is omitted. A verified partial declaration currently yields `CASUALTY_PARTIAL_SCOPE_UNSUPPORTED` assigned to the system, with no request for another dictionary. Source-declared child count equality remains a separate existing path; generic direct count semantics and partial population algebra are not supplied by this grammar.

### XLSX parser plans

`inspect_bundle` includes every worksheet (visible, hidden and empty) and returns
`xlsx-parser-plan-v1`. Copy the complete selected table descriptor to
`resource.table`. The independently regenerated plan binds actual input bytes,
sheet/state, workbook epoch, exact ordered column names, physical header row,
hashes of each prefix row, and blank/formula/date policies. Inspection, profiling,
the isolated SDK and trusted QA use the same plan; QA stores its own replay in
admission evidence. A plan mismatch or changed bytes requires fresh inspection
and QA. A filename is not part of the plan identity.

Supported layouts are a first nonempty header, or a bounded prose prefix:
one labelled title (`Title: description`), at least one parenthesized annotation
or `Note:`, `Notes:`, `Source:`, `Updated:`, `Published:`, `Coverage:` annotation,
then a blank separator and a contiguous header of at least two columns. The
header must occur within the first 64 physical rows. This is a conservative
format grammar, not arbitrary semantic recognition of metadata. Other prefixes,
multiple table regions, merged/multilevel headers, or arbitrary row/column
filters require further reviewed capability. The original file and prefix hashes
remain available; no raw prefix text or person records are sent by inspection.

Internal blank records and all records after the header remain subject to QA;
only a wholly empty trailing tail is omitted. Missing/extra columns, formulas
and Excel error cells cannot be hidden with a later `header_row`, `skipRows` or
end-row hint. The entire sheet is examined before it can be declared empty;
nonempty sheets starting beyond the bound block rather than vanish. XLS retains
its existing first-row reader; this plan does not claim legacy preamble support.

The plan does not classify a sheet as a business fact/lookup, authorize ignoring
facts, determine casualty/crash grain, or provide aggregation. Those decisions
still require a TablePlan and applicable semantic evidence. Selecting one sheet
does not remove other sheets from the QA inventory.

### Table classification and dictionary reads

Policy 14 replaces the name/description header heuristic with
`schema-linked-table-classification-v1`. An unassigned dictionary must have
exactly two columns: `field`, `field_name`, `column`, `column_name` or `variable`,
and `description`, `definition` or `meaning`. Every row must contain a unique
exact field identifier from the same other uploaded physical table and a textual
definition of 12–8192 characters. The complete table is checked, up to 10,000
rows and 4 MiB of definition text. Extra record columns, missing/duplicate keys,
unknown fields, multiple unrelated target schemas and name/label tables cannot
silently disappear under dictionary classification.

Inspection returns `dictionary_review`; `read_document` independently repeats
the same check before returning any dictionary contents. Each dictionary sheet
has its own extraction document ID, even when multiple sheets share a file.
Trusted QA saves full classification receipts (input/table identity, row count,
row-content digest and linked schema fields); valid dictionaries are represented
as documentation, not counted as crashes. Preflight returns the classification
decisions. Model-written `table_plan.verified` flags have no authority.

This is a finite structural dictionary grammar, not proof that the publisher
endorses the definitions. Official semantic claims still need the scoped source
receipts and evidence gates. It is not a general lookup/codebook, arbitrary
attachment classifier or the union/aggregation TablePlan. The existing plain
TXT/MD documentation path remains separately identified as legacy in the receipt.

An unassigned uploaded JSON file can be treated as a standalone document only
when it meets the bounded metadata-only object grammar. Positional row arrays,
unknown envelopes, or documents mixed with raw record collections cannot be
ignored because their reader raises a capability/evidence diagnostic.

### Homogeneous physical partitions

A single logical resource can declare `partitions`, an ordered list of 2–24
physical `{file_id, table}` inputs. Its existing `file_id` and `table` must equal
the first item; this preserves the single-resource interface. All inputs use
the logical resource's **same key, mapping, grain, source URL and semantics**:

```json
{
  "role": "crash", "grain": "crash", "key": ["EVENT_ID"],
  "file_id": "first-admitted-upload", "table": {"format": "csv"},
  "partitions": [
    {"file_id": "first-admitted-upload", "table": {"format": "csv"}},
    {"file_id": "second-admitted-upload", "table": {"format": "csv"}}
  ],
  "mapping": {"date": {"field": "DATE", "formats": ["%Y-%m-%d"]}}
}
```

`homogeneous-union-v1` validates each selected physical table against the same
exact field names. Column order may differ; renames, extra/missing fields or
per-partition mapping overrides require further reviewed schema-drift support.
There is no filtering, row deduplication, sorting-based key generation or
implicit filename/year field. Repeating an identical file-hash/table pair is
rejected even if it has a different upload ID. Unassigned other sheets remain
subject to normal table conservation checks.

The SDK's existing `ctx.iter_rows(role)` streams all partitions. Union locators
are JSON arrays `["homogeneous-union-v1", file_sha256, table_id, native_locator]`.
The original source key remains the business ID. Trusted QA independently
replays all parts, requires cross-partition key uniqueness, and checks complete
relations and aggregates over the logical resource. Sample mode still examines
at most the first 1,000 rows per logical resource; only full QA checks all rows.
Every physical geometry envelope and required RDF coordinate binding is checked;
a later partition cannot borrow the first one's CRS validation.

Admission stores the host union plan and all physical input hashes. Registry
normalization and same-content recipe replay rebind every ephemeral upload ID;
changed bytes require investigation and fresh QA. The existing conservative
cache still does not arbitrarily pair a file reused by multiple table roles.

Union row conservation does not prove official complete partition coverage.
The existing deletion gate does not accept one member's completeness receipt
as authority for the whole union. Frozen native revisions retain their reviewed
table layouts; this autonomous union cannot rewrite that boundary. Lookup,
wide-to-long and aggregate TablePlans remain separate capabilities.

### Unique lookup: separate physical and semantic gates

Policy 21 replaced the former blanket `LOOKUP_ADMISSION_NOT_INTEGRATED` blocker
with scoped relation, field, category, count-population, coordinate-subject and
CRS checks. The supported subset can proceed only through fresh sample/full QA,
registration and atomic publication. Structural validation alone grants no
admission. Typed parent dates, legacy text category proof and unsupported missing
policies remain specific blockers; do not infer support from physical execution.
A synthetic end-to-end acceptance exists in the earlier paused checkpoint; it
is not a real VIC dataset admission or verification of later opt-in development.

The syntax keeps parent tables out of fact `resources`:

```json
{
  "lookup_tables": [
    {"role":"locations", "purpose":"lookup", "file_id":"admitted-parent",
     "source_url":"https://publisher.example.gov.au/locations.csv",
     "table":{}, "key":["LOCATION_ID"]}
  ],
  "resources": [
    {"role":"crash", "file_id":"admitted-crashes", "grain":"crash",
     "source_url":"https://publisher.example.gov.au/crashes.csv",
     "key":["CRASH_ID"],
     "lookups":[{"name":"place", "parent":"locations", "fields":["LOCATION_ID"],
                 "select":["LONGITUDE","LATITUDE"], "allow_blank":false,
                 "on_missing":"error"}],
     "mapping":{"geography":{"x_field":{"lookup":"place","field":"LONGITUDE"},
                              "y_field":{"lookup":"place","field":"LATITUDE"},
                              "crs":"EPSG:4326"}}
    }
  ]
}
```

This fragment omits normal required source/date/evidence fields and grants no
CRS authority. References are supported only at typed field positions in
date, geography, severity/injury, counts, observation dimensions and unit type.
Keys and relationships keep original child identifiers. Lookup keys cannot
depend on other lookups; filters, defaults, custom expressions and deduplication
are not supported. Selecting `preserve_unknown` instead of `error` only specifies
physical missing-value behavior; semantic admission currently rejects
that unsupported policy. `matched` with a null field, `unmatched`, and an entirely blank
`not_associated` key remain distinct.

The full parent is checked even for a 1,000-row child sample, across every
declared homogeneous partition. Every parent key must be unique, including
unused keys. A failed key/request invalidates the index receipt; catching an
exception does not permit dropping the record. Receipt counts describe recorded
requests, not proof of full child coverage. Parent field names and values are
not normalized; 001 and 1 remain distinct. An absent selected field is not
silently converted to an explicit null.

`ctx.project` preserves the child's original `extensions`, business key and
physical locator, and adds `lookup_lineage` with match status and parent file
SHA/table/locator/row hash. Exactly one child produces at most one projection.
Parent input bytes stay immutable and disk indexes contain all parent rows,
including unused keys. No lookup record contributes a crash count by itself.
Host replay rebuilds the parent indexes from immutable inputs, compares every
candidate field and parent lineage, enforces child-row conservation and counts
shared parent rows once. A diagnostic `trusted-lookup-replay-<run_id>.json` records
successful physical equality with `admission:false`. Separate semantic checks
and all other full QA gates must pass before an admitted recipe or publication.
The physical receipt alone is not a semantic oracle or full admission.

All fact and parent files (including parent partitions) participate in semantic
normalization, input fingerprints and recipe rebinding. Changed or missing
parent bytes cannot match a child-only recipe. Retained-history updates also
compare parent keys, child bindings, selected fields and missing-value policy.
Registry and publication retain their independent admission boundary. Synthetic
acceptance does not authorize a real source with duplicate parent keys.

Policy 18 resolves `{lookup,field}` to the exact physical parent role/field.
Parent schema, coverage and CRS evidence use the parent's publisher-bound
`source_url`, including per-resource metadata and temporal restrictions. Two
axes must come from the same lookup binding; mixed-row coordinate composition
is explicitly unsupported. Parent category maps use the existing scoped domain
review and record their original child consumer. A same-named child field/domain
cannot certify a parent field. These diagnostics do not prove count populations.

The relation reviewer implements a finite subset of the
[W3C CSVW foreign-key description](https://www.w3.org/TR/tabular-metadata/#schemas):
fixed `http://www.w3.org/ns/csvw` context, inline Table/TableGroup schemas,
ordered `columnReference`, and explicit `reference.resource` plus target columns.
Only already authorized, applicable documents are inspected. Relative resource
URLs use the actual document URL; contexts/schemas are not fetched. Exact child
and parent resource URLs, direction and ordered keys must match. The whole
reference must be cited with hash-pinned locators; uncited known contradictions
remain blocking. Optional keys need explicit unambiguous `required:false` on
every child key column. Schema references, context overrides, fragment selectors,
weak links and unmatched nonblank keys remain outside this implemented subset.
This is not full CSVW conformance. Policy 21 also permits exact version-pinned,
implementation-reviewed relationship claims; it does not infer arbitrary relations.

Policy 19 resolves direct counts and same-parent-row sums to physical parent
fields, reusing scoped direct definitions and official addition equations. Each
lookup operand also needs an explicit population matching the consumer grain;
field presence or an unqualified count definition is insufficient. Mixed-table
sums and independently matched parent rows remain
`LOOKUP_CROSS_RESOURCE_SUM_UNSUPPORTED`; no dictionary reference is coerced to a
field-name string. Existing pinned reviewed interpretations retain their exact
source, document, key, grain and coverage requirements.

Host QA records parent-row/metric allocation across all consumer roles and
bindings. The same physical parent count cannot be allocated to two consumer
records, including when its value is zero or unknown. This check covers all
children in full mode; a sample cannot establish nonbroadcast for later rows.
Multiple fields for the same consumer and shared category-only lookups are
allowed by this physical check, subject to the remaining semantic gate.

Capability checks retain the original child view and inspect explicitly
projected parent geometry against its own physical envelope/CRS. A parent
projection cannot hide supported child coordinates. Unprojected codebook
geometry is retained as lookup data and is not automatically promoted to a
crash location.

Policy 20 additionally reviews explicit parent-coordinate definitions for the
consumer's spatial subject and axis. A whole field definition such as
"Longitude coordinate of the crash" can establish this meaning; a station,
postcode or area centroid cannot be projected as a crash location just because
the CRS and foreign key match. This bounded structured-definition grammar does
not interpret arbitrary prose, establish positional accuracy, or replace the
CRS/relationship/full-QA gates. Both axes require scoped cited definitions, and
known contradictory or unresolved definitions remain visible.

All field/count/category reviews can select embedded schemas from already
publisher-scoped CKAN packages using an explicit, exact resource `source_url`.
The selector preserves original JSON pointers and duplicate matching resource
descriptors; it does not recursively borrow schemas from neighbouring resources
or query variants. `attributes` descriptors with an explicit `db_name` expose
their publisher-stated `name`/`alias` and definitions; arbitrary record attributes
are not schemas. The frozen VIC Node coordinate definitions were verified under
this path. Its raw duplicate-key blocker remains unchanged: verified metadata
meanings do not authorize deduplication, prove keys, or grant admission.

### Direct count meanings

Every direct count projection (including a single-field sum) must have a matching source metric definition; an injured-person count cannot map to fatalities and a unit-level count cannot map to a crash total. The host consumes full definitions from scoped fields/columns, not arbitrary neighbouring JSON. Known contrary definitions and unresolved additional definitions cannot be hidden by omitting citations. Explicit source equations may define a stored total without executing the equation. Literal text field definitions are bounded; arbitrary prose is not inferred.

`knowledge/reviewed-count-claims.json` contains versioned implementation-reviewed interpretations with exact official-document hash and locators, dataset URLs, source key/grain and tested coverage. These are trusted implementation data included in QA dependencies, not a model-written contract or a second source catalogue. A task must register the same applicable document and cite its definition; no hidden download or static-file substitution is permitted. The initial four SA interpretations were checked against rendered export-table p2, definition-table p3/p4 and population notes p6. The abbreviated/full-name relationship is an explicit implementation interpretation, not a machine-readable alias allegedly provided by the publisher. Other dictionaries/versions/populations require fresh review or supported structured definitions. No cross-source comparability or uploaded-file authenticity is inferred.


### Host opt-in adaptation development (not yet tested)

`autonomous_adaptation_v1` is a trusted runtime boolean, disabled by default.
Upload options, source contracts and model arguments cannot enable it. Historical
sessions keep their saved behavior. This development has not been tested; see
`docs/AUTONOMOUS-ADAPTATION-OPT-IN-20261002.md` before any future enablement.

When enabled, preflight reports the existing row/union/unique-lookup operators
and their host verifiers; the execution and QA paths apply the same operation
restriction. Arbitrary task Python can diagnose inputs but cannot provide its
own authoritative validator or bypass raw-row replay. System capability and
environment blockers preserve proposals and stop further source investigation.

With the existing private `knowledge_root`, an admitted recipe may seed a
same-source new-version candidate. This first subset requires name-addressed CSV,
exact official resource-byte binding, freshly checked scoped evidence,
compatible implementation, and a newly measured and evidence-authorized period.
Only explicit CKAN JSON cosmetic changes can reuse equal claim values with new
hash-pinned references; unknown changes and unsupported documents require review.
It always reruns sample/full QA and existing registration/publication gates.
Schema drift, ambiguous binding, unsupported parser/partition pairing or missing
temporal authority returns a specific difference to the existing Agent. It does
not inherit old QA, infer deletion rights from dates, or change `no_change`.
