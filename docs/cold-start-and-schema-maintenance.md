# A09 cold-start and schema-maintenance guide

This guide rebuilds the Role A database component from an empty PostgreSQL 16
instance and checks the resulting schema against the team v1.1 field
dictionary. It is intentionally narrower than the complete platform cold
start: AT17, official/full-scale data, publication, and unfinished C/D/E
modules remain outside this run.

## What this verifies

- PostgreSQL starts from temporary empty storage with UTF-8 and UTC settings.
- Migrations `001` through `011` are present and run once in filename order.
- The resulting six application schemas contain exactly 17 tables and 129
  fields with the expected order, PostgreSQL type and NULL rule.
- The catalog contains 17 primary keys, 30 foreign keys, 6 UNIQUE constraints
  and 46 CHECK constraints.
- Schema ownership, the three application roles and the A03 permission audit
  still match the least-privilege design.
- `rv.encode_business_key()` preserves ordered text and leading zeroes, and
  migration `011`'s corrected map constraint is active.
- No application rows or persistent database volume remain after the run.

The executable contract is [`config/schema-v1.1.json`](../config/schema-v1.1.json).
It is derived from *Complete Database Field Dictionary*, whose SHA-256 is
`99a4835bf2c63d5b0eb5f7e642b19e54613c02fb676c88aef07d60dec2933298`.
Keeping the expected inventory in Git lets a reviewer see exactly which
dictionary version is tested instead of comparing the database with itself.

## Prerequisites

Use macOS or Linux with:

- Python 3.12;
- Docker with the daemon running;
- a checkout containing the team field dictionary beside this repository at
  `../ARSIA-Team-Handoff-EN 2/02-Database-Field-Dictionary.md`.

The verifier does not use the shared Compose database, ask for a password, or
create a Docker volume. It generates a short-lived random password in a
mode-0600 temporary file, starts the pinned PostgreSQL image on a random
loopback port, and removes the container in `finally` even when a check fails.

## Reproduce the database cold start

Run from the repository root:

```bash
./.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_a09_cold_start.py
```

The small test first checks the committed contract, exact migration sequence
and temporary-container safety flags. It does not start Docker.

Then run the actual empty-environment reproduction:

```bash
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python tools/verify_a09_cold_start.py \
  --output docs/evidence/a09-cold-start-2026-09-26.json
```

Success prints `"status": "passed"`, `"migrations_applied": 11`, catalog
counts and `"container_removed": true`. The JSON evidence records:

- Git revision and dirty working-tree paths;
- Python, operating system and pinned container image;
- the dictionary, contract, audit and migration SHA-256 values;
- all migration results;
- the complete observed table/column inventory;
- constraint, ownership, role, permission and migration-011 checks;
- empty final table counts and cleanup result;
- explicit executed and unexecuted scope.

Do not edit a failed receipt into a pass. Diagnose the failure, remove the
failed receipt, correct the source problem, and create a new recorded run.

## Recorded validation on 2026-09-26

The committed evidence is
[`docs/evidence/a09-cold-start-2026-09-26.json`](evidence/a09-cold-start-2026-09-26.json).
The run started a fresh pinned PostgreSQL 16 container, applied all 11
migrations, passed the A03 permission audit and removed the container without
creating a persistent volume.

| Check | Result |
|---|---:|
| Migrations applied | 11 |
| Physical tables | 17 |
| Fields | 129 |
| Primary / foreign keys | 17 / 30 |
| UNIQUE / CHECK constraints | 6 / 46 |
| A09 targeted tests | 3 passed |
| Default regression suite | 618 passed, 155 skipped |

The default-suite skips require optional PostgreSQL DSNs, source archives or
isolated integration verifiers. They are not counted as passes. The A09
database checks were executed separately by the disposable verifier and are
recorded in the JSON evidence; no failure was hidden as a skip.

## Manual Compose development setup

The disposable verifier is the acceptance path. For ordinary local
development, set your own owner password only in the current shell:

```bash
read -r -s -p 'arsia_owner database password: ' ARSIA_DB_PASSWORD
export ARSIA_DB_PASSWORD
docker compose config --quiet
docker compose up -d db
docker compose ps db
```

Apply migrations only to a new database and in ascending order:

```bash
for migration in sql/migrations/*.sql; do
  psql -h 127.0.0.1 -p 55432 -U arsia_owner -d arsia -W \
    -v ON_ERROR_STOP=1 -f "$migration" || break
done
```

This loop stops on the first error. The migrations are not a repeatable reset
script: `CREATE TABLE` and `CREATE ROLE` correctly fail if replayed against an
already provisioned database. Use a new disposable database for proof instead
of manually dropping constraints or editing tables until the script passes.

After migration `009`, set local login passwords interactively if human or
application connections are needed:

```bash
psql -h 127.0.0.1 -p 55432 -U arsia_owner -d arsia -W \
  -c '\password arsia_loader'
psql -h 127.0.0.1 -p 55432 -U arsia_owner -d arsia -W \
  -c '\password arsia_reader'
```

Passwords do not belong in migrations, Git, evidence files or terminal
arguments. A protected PostgreSQL passfile or credential manager is preferable
for longer-lived environments.

## Migration order and maintenance rules

| Range | Responsibility |
|---|---|
| `001–002` | Source/resource registry and append-only Raw records. |
| `003` | Initial restricted loader role required by early Raw integration. |
| `004` | Build batches and successful current-release pointer. |
| `005` | Two Hubs, two Satellites and the crash–unit Link. |
| `006` | Typed Canonical crash and unit tables. |
| `007` | Source/month/severity dimensions and crash fact. |
| `008` | Persisted QA results. |
| `009` | Final migrator/loader/reader ownership and privileges. |
| `010` | Shared ordered JSON business-key encoder. |
| `011` | Review fixes for map eligibility and Unicode whitespace keys. |

Never modify an already shared migration silently. Add the next numbered
migration for a schema change, state the dependency, update
`config/schema-v1.1.json` only after the governing dictionary/contract changes,
and rerun A09 in a fresh container. A changed migration SHA is evidence of a
different build input even when its filename is unchanged.

## Failure diagnostics

| Symptom | Meaning and action |
|---|---|
| Docker cannot connect | Start Docker Desktop/daemon, then retry. No database work has begun. |
| Image cannot be pulled | Check network/registry access. Do not substitute an unpinned image in recorded evidence. |
| Missing dictionary or SHA mismatch | Use the exact v1.1 handoff file; do not update the pinned hash without a reviewed contract revision. |
| Missing migration number | Restore the required migration or intentionally version a new schema contract. Gaps are rejected before Docker starts. |
| Migration fails | Inspect the named migration and its dependency. Never patch the live database manually. |
| Table/field mismatch | Compare the recorded actual inventory with `config/schema-v1.1.json`; fix migration or reviewed contract, not the evidence. |
| Constraint-count mismatch | Inspect `pg_constraint`; a table can have correct columns while losing referential or validation rules. |
| A03 audit fails | Ownership or grants changed. Review migration `009` and avoid granting broad PUBLIC access. |
| Cleanup is false | Run `docker ps -a --filter label=arsia.scope=a09-cold-start`, inspect the named container, then remove that exact disposable container. |

## Acceptance boundary

This run proves that an independent member can reproduce the **database
component** without private secrets, a pre-existing volume or manual schema
repairs. It does not prove that every application module is installed, that
the complete B10 runner succeeds, that official data loads at full scale, or
that E's publication/AT17 acceptance is complete. E09 must still run the
independent full-platform replay after all required modules and publication
functions are integrated.
