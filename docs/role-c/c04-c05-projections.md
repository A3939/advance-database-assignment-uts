# C04 / C05 — VIC and QLD projections

This delivery implements C04 and C05 and connects C04 to the existing C07
location resolver. It uses the shared A05 business-key function, C01's 24/11
fields, C08 semantics, and B's connection/transaction. It does not publish a
batch or claim completion of C10, DW reconciliation, FP1, or project acceptance.

## Entry points and order

```python
from arsia_c.projections.vic import project as project_vic
from arsia_c.projections.qld import project as project_qld

# Within B's existing transaction, AFTER B08 and BEFORE A06:
project_vic(connection, context)  # when VIC is selected
project_qld(connection, context)  # when QLD is selected
# A06 load_vault -> C09 load_canonical -> D -> applicable QA -> E -> B commit
```

The context has `batch_id`, `manifest.as_dict()` and
`evidence.write_json(name, value)`. Both callbacks support B's
`ModuleConnection`. They never commit, roll back, close the connection,
calculate FP1 or change release pointers. The caller must roll back the entire
candidate transaction on any exception.

Each callback validates its complete selected snapshot before filtering years.
It preserves other sources/batches/releases in `pg_temp.arsia_i_crash` and
`pg_temp.arsia_i_unit`. Repeating the same source replaces only that selection.
Temporary `c45_*` tables and the C07 assembler add no persistent schema tables.

## C04

- Accident identity is the native text `ACCIDENT_NO`; Vehicle identity is
  `ACCIDENT_NO + VEHICLE_ID`. A05 performs encoding without Python re-encoding.
- Full-input duplicate keys, invalid values and orphan Vehicle/Node rows block.
  Year filtering never hides invalid parents. Exact ISO dates are required.
- Severity and casualty definitions follow the selected synthetic contract or
  the exact frozen official VIC restricted profile. Unknown required counts
  stay NULL; independently known metrics remain eligible.
- Actual in-scope Vehicle rows are retained. Under the official profile every
  unit has `count_eligible=false` and a `definition_unconfirmed` reason. Native
  `21` remains preserved without being equated to Person `16`.
- Official Vehicle declaration differences and absent Node matches must match
  the pinned accident/date/native-locator cases, not only aggregate counts.
  Vehicle category counts must match the frozen snapshot. This does not replace
  C06's Person checks or C10's complete QA objects and output-restriction checks.
- C07 evaluates every selected Node observation using exact decimals and the
  native accident/Node pair. Bad or conflicting locations retain their crash.
  Synthetic eligible coordinates use the numeric-original-row representative.
  Official maps remain disabled, with candidate lineage and reasons retained.
- Person remains Raw/check-only. Its selected input count is checked here;
  Person relationship/count semantics remain C06's responsibility.

C's native `c04_vic_relationship_check.sql` is retained unchanged. The callable
module uses the separate `c04_vic_staged_relationship_check.sql` after selection
and A05 validation; apply the complete delivery, not one SQL file in isolation.

## C05 and B09 handoff

`source_contracts.qld_definitions()` returns new copies of the pinned
`config/c05-qld-official-v1.json` source, analysis, contracts, mappings and
severity lists. B can merge those lists into its normal manifest assembly;
`docs/role-c/c05-qld-source-review.json` supplies the matching QA01 source review.
Pass the complete mapping entry to B's `supported_mappings`.

This is a confirmed **project contract for the enabled snapshot outputs**,
based on the already adopted website decisions and D01 evidence. It does not
claim D/C signatures, publisher certification, completed QA or publication.
It replaces the candidate choices only for this new version, preserving D01's
original draft and evidence. Runtime code, schema and policy inventories must
still contain their actual paths and hashes; no stand-in FP1 or inventory is
provided as an official build.

- `Crash_Ref_Number` remains opaque text; occurrence uses `Crash_Year` and
  `Crash_Month`, never the ID. No invented day is generated.
- The five native severities and `__MISSING__` are registered, including PDO
  even when absent from the analysis period. New nonempty tokens block.
- `Count_Casualty_Total` is reconciled with all four components. Unknown required
  values remain NULL/ineligible; negatives, malformed values and overflow block.
- `Count_Unit_*` remain Raw aggregate attributes. No QLD units or persons are
  generated. Accident measures remain source-specific.
- The source datum is GDA2020. The official map is disabled because the target
  EPSG:4326 operation is unvalidated. Trusted location fields are NULL and the
  reason explains that distinction; the source datum is not labelled unknown.

C07 PR #11 (`9338dc8`) was merged during implementation and is included in the
final regression baseline. C04 uses that version unchanged. Runtime SQL and
pinned configuration are also shipped as package resources; an installed-wheel
test resolves them outside the source checkout and checks exact parity.

The unchanged `config/vic-restricted-inputs-v1.json` is included from B's
`bc4ed6b` delivery. The existing VIC policy remains byte-for-byte unchanged;
its false confirmation flags and unresolved definitions are not cleared.

## C09 compatibility

A small accompanying change admits `restricted` only after matching the exact
VIC files, contracts, source, years, mappings, severity and QA protocol. The
pinned same-name parent-field convention is resolved explicitly. Unknown
restricted contracts and attempts to turn on VIC map/unit outputs still block.
Primary Raw lineage uses a parameterized primary-key lookup to avoid an
expensive join plan on the large uncommitted first build. All prior C09
adversarial tests remain part of the regression suite.

## Verification and limits

See `c04-c05-validation-2026-09-24.json` for measured results and file hashes.
Run the documented tests under Python 3.12 and PostgreSQL 16 with A's migrations
through `011_review_validation_fixes.sql`. The DSN must use `arsia_loader`. The native check uses a fresh dedicated
database; repeatedly rolled-back bulk loads followed by vacuum can leave
misleading empty-table statistics and make foreign-key checks very slow.
The final full-input runs used normal loader privileges and no disabled checks.

```sh
python -m pytest -q tests/test_c04_vic_projection.py tests/test_c05_manifest.py tests/test_c45_postgres.py
```

Without `ARSIA_TEST_DSN`, database tests explicitly skip. With it configured,
connection or migration failures fail rather than silently skipping.

The opt-in native verifier requires an EMPTY dedicated database and separately
retained native CSVs. It verifies hashes/headers, copies native records into Raw
as test setup, executes projection/A06/C09, compares independent native totals
and every Canonical field, then always rolls back:

```sh
python tools/check_c45_native.py --native-dir /path/to/raw_datasource --evidence-out /path/to/c45-native.json
```

This native check is not a full B08/B10 build or seven-group QA/publication run.
The separate S0 integration test does execute real B08 and all three actual
projections through A06/C09; it does not substitute prebuilt C01 rows.

References: [C04](https://arsia-team-design.vercel.app/plan.html?lang=en#C04),
[C05](https://arsia-team-design.vercel.app/plan.html?lang=en#C05),
[official decisions](https://arsia-team-design.vercel.app/official-decisions.html?lang=en),
[D01 evidence](https://github.com/A3939/advance-database-assignment-uts/blob/b5395768d7242f4d42d5c78a7595babb6d9b1adf/docs/source-contracts/D01-QLD-source-contract-draft.md).
