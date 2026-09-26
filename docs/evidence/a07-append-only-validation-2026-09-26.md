# A07 append-only history and lineage validation

Validated on 26 September 2026 from shared `origin/main` commit `addc151`
on branch `jj/a07-append-only-history`.

## Scope

This evidence checks Role A's append-only database boundary:

- a later batch reuses existing Hubs without replacing their
  `first_seen_batch_id`;
- each batch retains separate Crash and Unit Satellites and a separate
  Crash–Unit Link;
- loading an unpublished candidate does not move `meta.current_release` away
  from the earlier successful batch;
- the earlier successful Satellite rows remain byte-for-byte equivalent at
  the PostgreSQL value level after the later batch is loaded;
- invalid batch scope, orphan units, duplicate keys, invalid coordinates and
  Raw rows outside the frozen file selection are rejected;
- Canonical parent and location lineage failures roll back the shared
  transaction without leaving partial Vault or Canonical rows.

## Local PostgreSQL result

The local database used PostgreSQL 16 through `arsia-role-a-db-1` on loopback
port 55432. Migrations 001–010 were already installed and migration 011 was
applied successfully before this run.

The focused Vault suite was run as the restricted `arsia_loader` role:

```text
tests/test_vault_load_postgres.py
7 passed in 0.40s
```

The broader A07-related selection was also run as `arsia_loader`:

```text
tests/test_vault_load_postgres.py
tests/test_c09_acceptance_postgres.py
tests/test_d02_postgres.py
tests/test_b10_lifecycle_postgres.py
31 passed, 9 skipped in 1.85s
```

The nine skips are deliberate environment gates. D02 and B10 persistent
history cases require their disposable PostgreSQL verifiers and must not run
against the ordinary shared test database. Existing repository evidence
records those isolated runs; a skip is not counted here as a local pass.

The ordinary local regression suite was then run with the disposable-only
`test_ac_integration_postgres.py` module excluded:

```text
751 passed, 12 skipped in 20.84s
```

The twelve skips are declared optional-data or isolated-database gates. There
were no failures or errors in the tests that are valid against the ordinary
local PostgreSQL database. The excluded A/C integration module asserts an
`AC_TEST_RUN` marker and is intentionally runnable only through
`tools/verify_ac_postgres.py`; it is not safe to force against the persistent
development database.

## Acceptance mapping

| A07 concern | Executable evidence |
|---|---|
| Later observations append without replacing Hub identity history | `test_new_batch_appends_history_without_moving_current_release` |
| Earlier Crash and Unit Satellite values remain unchanged | Snapshot assertions in the same test |
| Candidate loading cannot silently publish itself | `meta.current_release` remains on the first successful batch |
| Complete parent identity is required | `test_vault_rejects_orphan_unit_without_writes` and C09 parent/link checks |
| Frozen Raw lineage is required | `test_vault_rejects_raw_row_from_different_frozen_file` and C09 selected-file checks |
| Location lineage is exact | C09 Node/direct-location acceptance and rejection cases |
| Partial writes roll back | `test_shared_transaction_rolls_back_partial_canonical_and_vault` |

## Integrated team evidence

- Merged PR #18 records three-source loading, caller-owned rollback and
  preservation of an earlier committed snapshot.
- Merged PR #29 adds cross-batch QA-history checks.
- `docs/evidence/b-ac-integration-2026-09-24.json` records the integrated
  PostgreSQL component-chain validation.
- `docs/evidence/b10-local-validation-2026-09-25.json` records the isolated
  lifecycle run, including protection of finished batches and empty final
  tables after cleanup.

## Remaining boundary

This evidence does not claim a completed full-platform publication run. Final
update/deletion and published-history acceptance still requires the accepted
E03 fingerprint and E06 publication/current-release bindings, the final frozen
inventory, and one complete B10 run with all real module callbacks. Until that
exists, A07 remains **in progress** even though the A-owned Vault append-only
and lineage boundary is implemented and locally verified.
