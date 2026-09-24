# A06 Vault loading contract

`arsia_ingest.vault_load.load_vault(connection, context)` is A's `vault`
callback for the shared runner. It uses the supplied connection, writes no
transaction boundary and records its counts through `context.evidence`.

## C-to-A session projections

C's preceding `project` callback creates two temporary tables on the same
database session:

- `pg_temp.arsia_i_crash`, with the 24 C01 crash fields;
- `pg_temp.arsia_i_unit`, with the 11 C01 unit fields.

The loader requires the declared column order, PostgreSQL types and NULL rules.
It rejects permanent substitutes, changed schemas, foreign batches, sources or
release scopes outside the frozen manifest, duplicate keys, orphan units,
invalid core values and Raw lineage outside the selected resources.

The crash projection fields are:

```text
batch_id, source_id, release_scope, crash_key, raw_record_id,
occurrence_year, occurrence_month, occurrence_date, date_precision,
severity_raw, severity_code, severity_definition_version, is_fatal_crash,
fatality_count, casualty_count, fatal_crash_eligible, fatality_eligible,
casualty_eligible, latitude, longitude, location_crs, map_eligible,
location_record_id, quality_notes
```

The unit projection fields are:

```text
batch_id, source_id, release_scope, unit_key, crash_key, raw_record_id,
unit_type_raw, unit_type_code, statistical_scope, count_eligible, quality_notes
```

## Five-table write

The loader inserts identities into `rv.hub_crash` and `rv.hub_unit`. Existing
identities are retained with their original `first_seen_batch_id`. It appends
the candidate snapshot to `rv.sat_crash` and `rv.sat_unit`, then writes every
real unit's same-scope parent relationship to `rv.link_crash_unit`.

Satellite `attributes` are produced with PostgreSQL `to_jsonb(record)`. This
preserves explicit JSON nulls and native numeric and boolean types. Identity,
scope and primary Raw lineage columns remain relational rather than duplicated
inside attributes. Unit attributes deliberately retain `crash_key`.

No insert commits independently. Any projection, relationship or lineage
failure rolls back with the shared candidate transaction controlled by B.

## C09 selection

`iter_satellites(connection, context, "crash" | "unit")` streams only the
current candidate's selected Satellite rows in stable key order. Unit results
include the parent `crash_key` from `rv.link_crash_unit`. C09 uses this method
instead of rebuilding Canonical data directly from Raw.

The current C branch provides the C01 typed contract and fixtures but not yet a
runner projection callback. A06 can validate its loader against those fixtures;
an end-to-end team build remains pending until C supplies the real callback.
