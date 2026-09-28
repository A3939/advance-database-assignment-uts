# C06: Person relationships and counts

Version `c06-person-v0.3`. C06 supports the existing S0/S8 definitions and the
adopted [VIC restricted policy](vic-restricted-use-decision.md). It checks Raw
through B's connection and returns diagnostics. It does not publish results,
write QA tables or implement Node, Vehicle count reconciliation or C10.

## Checks

The SQL selects complete Accident, Vehicle and Person snapshots by source,
resource, file SHA256 and parser. It checks keys and parents before assigning
years, so an orphan cannot disappear as an out-of-range record. Duplicate keys,
invalid dates/counts, ambiguous parents and invalid references block. Grouped
parents prevent join multiplication. Original values, locators and Raw IDs
remain in the evidence; no records are repaired or deleted.

S0/S8 keep their explicit blank-reference and complete-count definitions.
For the pinned official files, `team-v1.1-vic-r1` adds:

- Native empty Vehicle ID with `ROAD_USER_TYPE='1'` and `SEATING_POSITION='NA'`
  is a team-defined non-association. NULL, whitespace and other tokens are not
  covered. Nonempty pedestrian links are checked normally.
- The 39 unmatched references and 24 unknown-role blanks must match the exact
  registered keys, native fields, locators, parent dates and scope. Available
  vehicle locators are also checked for unmatched references. Missing, changed
  or additional cases block, even when the total count stays the same.
- Declared and observed Person counts are compared diagnostically across the
  full files. Both 2015 differences must match their declared/observed values
  and contributing Person/Vehicle locators. In-scope differences are counted
  separately. Unknown declarations stay NULL; opposite deltas cannot cancel.
- The four file declarations, years and complete policy must match
  [`c06-vic-r1.json`](../../config/c06-vic-r1.json). That file pins the adopted
  policy bytes. Pedestrian and registered-case totals are checked separately
  from case membership. These are exact expectations, not error allowances.

`definitions_confirmed` stays false for official inputs. A C06 `pass` means
these relationship/count checks passed under the restricted policy. It does
not confirm export completeness, Node checks, report restrictions or release.

## Interfaces

For S0/S8, use `review_manifest(connection, frozen_manifest)` or
`check_person(connection, context)` from `arsia_c.person_checks`.
The callback writes `c06-person.json` through B's immutable evidence writer
before raising `C06_BLOCK`. Neither entry owns the connection or transaction.

The Python entries prepare `pg_temp.c06_selected_raw` with the complete three
selected files, then index and analyze that temporary table. The SQL resource
expects this preparation; it is no longer a standalone Raw query. Direct SQL
tests call `_stage_selected(connection, files)` in the same transaction first.
Use the public Python entries in integrations. See the
[performance backport](c-performance-backport.md) for current verification.

The standalone official entry is ready for C10 and source review:

```python
from arsia_c.restricted_person import restricted_inputs, review_restricted

spec, policy = restricted_inputs()
report = review_restricted(connection, selected_files, spec["analysis"], policy)
```

`selected_files` must contain the actual four prepared file declarations, with
exactly the fields in `spec['files']`. SQL reads three of them; the Node
identity is bound to the bundle but its observations are outside C06. A named
cursor streams results within the caller's transaction. B's `ModuleConnection`
is supported. C06 never connects, commits, rolls back or closes the connection.

Reports contain file counts, distinct affected Raw rows, separate summary
violations, registered limitations, missing/unexpected cases and original
observations. `declared_count_absolute_delta` remains NULL for official inputs;
`diagnostic_count_delta` records each numerical difference without claiming a
confirmed common export scope. SHA256 here identifies evidence, not FP1.

`qa04_person_contribution` provides eight measured Person metrics and their
policy expectations. `restriction_violation_count` is explicitly unexecuted:
C10 must check D's output restrictions before creating a complete QA04 object.
Do not use C06 alone as B's complete `qa_c` callback. Vehicle and Node QA04
objects, QA05 semantics and the other required groups still need their owners.

This checkout retains B's earlier `team-v1.1` implementation. Its
`FrozenManifest` does not yet accept the restricted protocol. C06 includes
the binding checks for a supported manifest: mapping ID
`official_vic_restricted_use`, version `vic-accident-only-2020-2024-v1`, content
equal to the entire policy, referenced by all four VIC contracts. This route
has guard tests. The newer B checkout implements the protocol. Its implementation and
execution records are maintained separately and are not copied into this
branch. Legacy manifests and `review_official_draft` retain their blocks.

## Reproduce

Run from the repository root using Python 3.12 and
[`requirements-c06.txt`](../../requirements-c06.txt). Environment setup and
module/full-suite commands are in the [handoff](c02-c06-handoff.md#reproduce).
Tests use this checkout by default and do not require a neighbouring directory.
Set `ARSIA_REPOSITORY` only for an explicit compatibility check with another B
implementation; C's code and SQL remain in this repository.

Real SQL tests require an isolated PostgreSQL 16 database initialized by A,
Psycopg 3, `ARSIA_TEST_DSN` and a protected `PGPASSFILE`. The loader needs
SELECT/INSERT on the three B08 tables. Tests roll back. A missing DSN skips
these tests; an invalid supplied DSN fails. This module does not install or
migrate the database.

For the official-case excerpt, first provide the pinned original Accident,
Vehicle and Person CSVs. Existing native-input configurations are supported;
relative resource paths resolve against the configuration directory. The base
`config/native-inputs.json` uses `raw_datasource/` at the repository root. Git
LFS pointer files must be replaced by the actual pinned originals, obtained
through the team's data handoff or Git LFS access.

With the connection configured and those files present:

```sh
python tools/replay_c06_cases.py --input-config config/native-inputs.json --evidence .local/c06-excerpt-new.json
```

Use a new evidence filename on each run. `--input-config` can instead name an
existing configuration for originals kept elsewhere. It selects data paths,
not imported Python code. The command identifies LFS pointers before database
access; it does not download or copy the originals.

The command requires empty test tables, scans the three originals, loads only
registered-case excerpts and rolls back. It expects a completeness block:
the excerpt is smaller than the selected full files. A successful replay is
not a complete official Raw evaluation or publication result.

## Validation records

Test source and replay commands are included. Generated execution reports are
retained separately by the team, with their original environment and hashes;
this delivery does not include or relabel those results. Reproduction should
record the actual code version, input hashes, command, environment and result.
The [handoff](c02-c06-handoff.md) describes the remaining integration boundary,
including original source validation files required by newer B evidence guards.
