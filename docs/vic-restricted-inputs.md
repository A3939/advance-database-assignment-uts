# VIC restricted inputs: B09 and B11

B now accepts `team-v1.1-vic-r1` for the adopted
`vic-accident-only-2020-2024-v1` profile. This is input support for the team’s
restricted-use decision, not a complete official build or release.

## Frozen definitions

```python
from arsia_ingest.vic_restricted import vic_restricted_definitions

definitions = vic_restricted_definitions()
```

The result has `sources`, `analysis`, `contracts`, `mappings`, `severity` and
`qa_contract`, ready for `build_manifest(run_dir, **definitions, ...)`.
The prepared run must select exactly the four approved VIC resources; a
seven-resource run also needs definitions and reviews for its other sources.
Use existing metadata with `freeze_manifest(...)` when assembling explicitly;
this still requires the actual complete code/schema inventory.
Do not regenerate full inputs just to inspect these definitions.

The wheel includes the three pinned definitions under `arsia_ingest/policies/`.
They have the same bytes and hashes as the files under `config/`. Loading
definitions works outside the checkout; it does not read or approve source data.

The shared policy and supporting files under `docs/role-c/` and the evidence
directory are unchanged copies from C’s handoff. They keep the original review
context; this guide describes B’s current support. The mapping ID is
`official_vic_restricted_use`, as expected by C06’s `review_manifest` entry.
Contracts use `status="restricted"`. Full-source `bundle_confirmed` and
`contract_confirmed` remain false, with all ten unresolved definitions retained.
The historical `runtime_integrated=false` flag remains valid for the full pipeline.

Three configuration files must appear in the actual code inventory:

- `config/vic-restricted-use-v1.json`: complete adopted policy, cases and dispositions.
- `config/vic-restricted-inputs-v1.json`: exact files, source/release, keys and severity.
- `config/qa-team-v1.1-vic-r1.json`: full baseline QA section plus the adopted addendum.

Include the executed Python/SQL and dependencies too. Missing team modules,
E03 SQL or migrations cannot be replaced with test inventory files.
Include the three packaged policy copies too, since installed code reads them.
Root `contract_version` stays `team-v1.1`; the QA protocol has its own version.
All seven required checks remain. FP1 receives the full rules and inventory,
with provenance excluded; only E’s SQL may produce the build fingerprint.

The profile is tied to four hashes, 1,439,470 native records, exact headers and
parser/locator versions, 2020–2024 analysis, native severity and the complete
case register. Changed cases, outputs, classifications or files require a new
reviewed version. Other sources and S0/S8 gain no approval from this profile.

## QA01 and QA02

Call `check_inputs` as documented in [input QA](input-qa.md), passing the mapping
accepted by C in `supported_mappings`. Leave `official_reviews` empty for these
VIC files. A supplied unrestricted VIC review blocks as a conflicting input.

QA01 checks all native bytes, headers and row counts, plus the frozen policy,
case register and 15 cited evidence files. Portable copies retain the original
SHA256 values and historical text. The two full-source confirmation metrics
are false; the other six required metrics must be true. Unexecuted checks stay
null. Evidence hashing proves identity, not that QA04/QA05 have run.

When calling installed `check_inputs`, pass `policy_evidence_root` as the checkout
or evidence directory containing the pinned `config/` and `docs/` paths.
`check_profile_evidence(root)` uses the same layout. Historical evidence stays
outside the wheel; missing, modified or symlinked evidence still blocks.
`run_build` passes its `project_root` to this check.
QA02 still compares native values, fields, identities and locators against
actual Raw. It does not forgive data loss or repair registered anomalies.

## Checks and limits

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
```

For opt-in archive/C06 tests, set `ARSIA_VIC_ARCHIVE_ROOT` to the existing intake
archive root and `ARSIA_C_PACKAGE` to C’s checkout. Set
`ARSIA_VIC_CASE_REPLAY=1` to run the 308-row official case excerpt; it scans the
existing Accident, Vehicle and Person CSVs and loads only those selected rows. PostgreSQL tests also need
`ARSIA_TEST_DSN`, `PGPASSFILE` and the existing Psycopg environment. They use the
caller’s transaction and roll back; they install nothing. Use a fresh
`--basetemp` directory to keep reports. The integration suite checks that C06
accepts B’s real `FrozenManifest` and blocks incomplete Raw rather than claiming
success. Test code inventories are explicitly labelled and do not describe a
deployed platform.

The [23 September receipt](evidence/b09-b11-vic-restricted-validation-2026-09-23.json)
records these final results:

| Run | Passed | Skipped | Failed |
|---|---:|---:|---:|
| B suite, default environment | 521 | 16 | 0 |
| B suite + existing C06 tests, PostgreSQL/archive checks enabled | 686 | 0 | 0 |

The combined run includes 537 B tests and 149 C tests; many are unit tests,
not database tests. Actual QA01 passed for all four archives and the batch.
C06 accepted B’s `FrozenManifest` on PostgreSQL 16.15. The 308-row excerpt
matched 39 missing Vehicle references, 24 unresolved blank links and two
Person count cases; it correctly blocked incomplete Raw and the incomplete
pedestrian subtotal. All writes rolled back; the three test tables were empty
before and after, and the container was stopped. Historical receipts and the
C handoff package are unchanged.

C can consume the new manifest and implement the remaining projection,
Vehicle/Node and semantic checks. D must enforce unavailable outputs and avoid
count multiplication. E must support the amended QA metrics, require every
concrete object and summary, and supply FP1 and the publication gate. A’s
remaining QA/build tables are still needed for persistence tests. No official
release is enabled until those checks are integrated and verified.
