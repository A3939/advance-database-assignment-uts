# C10: projection, relationship, semantics and location QA

C's original C10 code covered part of QA03. QA04, QA05, QA07, callback persistence
and wheel resources were incomplete. Role C wrote that starting point in
`7bfb08e`, `ba65982` and `b0626ea`. Role B / Peixian added this implementation and
its PostgreSQL and installation checks on C base `ad8baed`.

The [QA07 year-coverage patch](c10-year-coverage.md) records the current fix and its tests. The original validation below remains the PR #26 baseline.

## Run and integration

`arsia_c.qa.runner_callback(connection, context)` is the `qa_c` entry point.
Use B's real `ModuleConnection`, `RunContext`, `FrozenManifest` and `RunEvidence`.
Bind `src/arsia_c/qa.py` with version `c10-role-c-v1.2`. Run it after C's temporary
projections, C09 Canonical and D02/D03 DW loading, in the same transaction.

`config/c10-inventory.json` records this component's paths and SHA-256 hashes.
It is a fragment. The final inventory must also pin the selected B, projection,
schema and other platform modules. No missing implementation hashes are supplied.

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt 'psycopg[binary]==3.3.6'
.venv/bin/python -m pytest -q tests/test_c10_packaging.py
.venv/bin/python tools/verify_c10_postgres.py --output /path/to/new-s0-results
# Optional complete, already-adopted official snapshots:
.venv/bin/python tools/verify_c10_postgres.py \
  --raw-root /path/to/raw_datasource --output /path/to/new-official-results
```

Docker is required. Fetch B `2750d8ea3f909cfacdc4cb10b35b87ffe729a468` and A
`c0824da06b6e7b3f73c4ddeab2114d10b7156913` if this clone lacks them. The verifier
assembles B's `peixian/b-cd-integration` checkpoint, overlays C10, builds a wheel and installs it in
a new venv. Tests run outside that checkout with `PYTHONPATH` removed. This B
version already contains the C03 resource fix returned to C in PR #24. Runtime
integration uses B's checkout: C's inherited B copy predates the restricted VIC
protocol, so use the pinned assembly above for official runs.

The verifier checks A's migration bytes, applies 001–011 in private PostgreSQL 16,
and runs A03's original permission audit before and after. Only fault injection
uses the owner; callbacks execute with `arsia_loader` privileges. Normal S0 and
official callbacks use actual loader sessions. Official Raw snapshots are committed as test inputs and analyzed by the owner,
so foreign-key lookups use current statistics. Candidate tables and QA results
are rolled back; the committed Raw baseline is checked and removed during fixture
cleanup. S0 rolls back its Raw rows too. The test container and its anonymous
volume are removed. No shared database is used. The full replay disables JIT, uses indexed foreign-key
lookups while loading, and allows hash joins for complete Raw scans. These are
session planner settings; constraints and permissions stay enabled.

## Checks and output

- **QA03:** one row per crash/unit resource. Native Raw supplies expected scope,
  keys, counts and typed values. Missing rows, invalid values and duplicates block.
- **QA04:** one row per unit/Person/Node resource. Check full native parent keys,
  non-empty Person vehicle references and confirmed declared counts. Node repeats
  are observations. The restricted VIC case sets must match exactly.
- **QA05:** one row per source. Compare projection and Canonical fields with frozen
  definitions and independent Raw expectations. Check NULL reasons and eligibility.
  Restricted VIC keeps its recorded categories, unresolved definitions and disabled
  unit KPIs; it does not acquire publisher approval.
- **QA07:** one row per selected source/year, including zero-crash years. Compare
  actual D03 counts and Canonical lineage with independently read Raw locations.
  Valid quarantined locations produce `limited` with one reason per unmapped crash.
  Incorrect mapping, missing crashes or inconsistent lineage produce `block`.

Each rule also writes a `batch` summary. B's existing `write_results` inserts all
rows into `qa.check_result`; C10 never replaces earlier rows. JSON evidence has
SHA-256 references, located differences and full detail row counts. Repeat calls
for the same batch are rejected. A blocking result raises `C10_BLOCK` after
writing diagnostic rows; B decides rollback. C10 does not commit or publish.

## Validation: 25 September 2026

Python 3.12.6 and PostgreSQL 16.15: **99 passed, 0 skipped, 0 failed**.
This includes 28 C10 S0/interface/fault cases, two complete official replays and
69 existing C06 SQL cases. The wheel/resource and C06 adapter checks separately
passed all 21 tests. A03 audits passed before and after; all candidate writes
were rolled back, fixture tables were empty, and the private container and volume
were removed. The full PostgreSQL run took about 33 minutes.

| Input | Native rows | Scoped crashes / units | C10 result |
|---|---:|---:|---|
| B S0 | 19 | 6 / 6 | 27 objects and four summaries; two location objects limited |
| Adopted QLD snapshot | 415,407 | 66,624 / not applicable | QA03/05 pass; all five QA07 years limited |
| Restricted VIC four-file snapshot | 1,439,470 | 72,170 / 132,372 | QA03/04/05 pass; all five QA07 years limited |

Official maps remain disabled. VIC unit KPIs remain disabled. Full VIC QA retains
39 registered unmatched Person references, exact Vehicle/Node case-set checks,
879 undefined-category rows (278 in scope), and ten unconfirmed definition IDs.
The full located case register is preserved in the frozen policy; none of these
observations is rewritten as zero.

[The receipt](c10-validation.json) records input hashes, code inventory, installed
wheel, migrations, environment, result metrics and evidence hashes. Full evidence
is reproducible with the commands above; original CSV data is not added to Git.

## Boundaries and C review

S0 uses B's actual definitions: three sources, 60 months and 12 severity entries,
including `__MISSING__`. Interface tests construct real `FrozenManifest` objects
with actual partial code inventories. They are not final platform freezes or E03
FP1 results. Full-original replay uses B's native reader and registration with a
bulk COPY into empty Raw, then the real component callbacks. It is not a B10 build.

C should review the independent expectations, required object coverage, NULL
reasons, restricted case matching and database receipts. Merge PR #24 for C03's
installed full projection path; this PR does not duplicate that fix. The C06 SQL
and two policy files are packaged here because QA04 calls the existing C06 code.
Their contents and C06 business rules are unchanged.

The latest A04 NSW contract still says `draft`, has no reviewer, and keeps
`contract_confirmed=false`. C must review that exact A contract with JJ before a
real official NSW FrozenManifest can be admitted. NSW's synthetic interface is
tested; this PR does not invent a source approval. VIC and QLD stay within their
adopted pinned scopes. C11's full source-model evidence is in PR #25.

B still needs to review/merge the component integration into `peixian/dev` and
freeze the final inventory after C review. E supplies
the accepted FP1/remaining QA and final acceptance work. D owns its remaining DW
and reconciliation review. These component results do not mark the platform as
accepted or authorize a real publication.
