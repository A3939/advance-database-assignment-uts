# A01/A09 environment and cold start

Use this guide for three separate checks: A's empty database, Compose data
retention, and the installed S0 build. Each check creates its own PostgreSQL
instance. None uses a shared database or proves independent E09 acceptance.

## Versions and inputs

- Tested Python: **3.12.6**, recorded in `.python-version`.
- PostgreSQL: **16.15**, from the digest pinned in `compose.yaml` and the tools.
- Tested Docker Engine: **28.5.2**; Compose: **2.40.3**.
- Python packages: `requirements-db.txt` includes the pinned runtime, test,
  build and database dependencies, including `typing_extensions`.
- Schema: A's fixed commit `c0824da06b6e7b3f73c4ddeab2114d10b7156913`,
  migrations `001–011`. Their contents and A03 grants are unchanged.
- Dictionary: [the committed v1.1 copy](contracts/database-field-dictionary-v1.1.md),
  SHA-256 `99a4835bf2c63d5b0eb5f7e642b19e54613c02fb676c88aef07d60dec2933298`.
  Its bytes match the original team handoff. No separate handoff folder is needed.
- Runnable B integration: `562de2910bfd7be276b3036983e5680d436fde1e`
  on `peixian/dev`. This A branch retains the older shared application baseline;
  the S0 tool fetches the fixed B revision into a separate directory.

Install Python 3.12.6, Git and Docker with Compose, then start Docker. These
commands work on macOS/Linux. Repository access and package/image downloads
need network access. The synthetic checks need no official data or Git LFS
objects. Use new output paths for each run; keep failed receipts too.

## 1. Install A's test dependencies

From this checkout:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-db.txt
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q tests/test_a09_cold_start.py
```

The tests check the dictionary, migration sequence, private-container flags,
invalid dictionary handling and protection of existing receipts.

## 2. Rebuild A's database

```sh
.venv/bin/python tools/verify_a09_cold_start.py \
  --output artifacts/a-handoff/schema.json
```

This starts an empty database with temporary storage, applies `001–011`, and
compares the live catalog with `config/schema-v1.1.json`: 17 tables, 129 fields,
17 primary keys, 30 foreign keys, 6 UNIQUE and 46 CHECK constraints. It checks
column order, types, NULL rules, ownership, roles, UTF8 and UTC.

The unchanged A03 audit tests the permission boundary. The additional 011
smoke check rejects blank/Unicode-whitespace keys and map eligibility without
confirmed WGS84 CRS. Its temporary `LIKE` table copies CHECK constraints, not
foreign keys; it is not a foreign-key behaviour test. Exact `COUNT(*)` queries
confirm all 17 application tables are empty after rollback. The tool removes
its container and prints `status: passed` only if validation and cleanup pass.

## 3. Check Compose lifecycle and real role logins

```sh
.venv/bin/python tools/verify_a01_lifecycle.py \
  --output artifacts/a-handoff/lifecycle.json
```

This creates a random Compose project, loopback port, password and named
volume. It applies the same schema, checks real TCP logins as `arsia_loader`
and `arsia_reader`, and commits one synthetic source record. It then verifies:

- `stop` followed by `start` retains that record;
- `restart` retains it;
- `down` followed by `up` creates a new container and retains the named-volume data;
- the A03 permission audit still passes after recreation.

Only this private project's container, network and volume are removed at the
end. The receipt confirms cleanup. No global Docker cleanup is used.

## 4. Install and run the complete synthetic S0 build

```sh
.venv/bin/python tools/verify_a09_synthetic.py \
  --output artifacts/a-handoff/synthetic
```

The tool clones the fixed B revision over SSH, creates another fresh venv,
installs both sets of pinned requirements, builds and installs a wheel, then
runs B's real PostgreSQL verifier outside the runtime source directory.
For HTTPS authentication, add:

```text
--repository https://github.com/A3939/advance-database-assignment-uts.git
```

The verifier checks installed package bytes and inventory hashes before
loading. It compares A's migrations and permission audit byte for byte. S0
then runs the actual A/B/C/D/E callbacks, FP1, QA01–QA07, private synthetic
publication, retry/failure handling and recovery. Success must include
`full_s0_build_verified: true` and `final_platform_accepted: false`.

Outputs include `receipt.json`, numbered command logs, and `full-build/`
with test XML, input hashes, permission audits, final table counts and cleanup.
The cloned runtime, wheel and venv remain local for inspection; the database
is disposable. Do not commit venvs, source archives or credentials.

## Local development with Compose

Choose a project name and free port. Generate an ignored password file once:

```sh
python3.12 - <<'PY'
import os
from pathlib import Path
import secrets
with Path('.env').open('x', encoding='utf-8') as stream:
    os.chmod('.env', 0o600)
    stream.write('ARSIA_DB_PASSWORD=' + secrets.token_urlsafe(30) + '\n')
    stream.write('ARSIA_DB_PORT=55432\n')
PY
docker compose -p arsia-local config --quiet
docker compose -p arsia-local up -d --wait db
```

An existing `.env` is not overwritten. Port 55432 is the default; change
`ARSIA_DB_PORT` if it is in use. Shell values override `.env` values. Apply
migrations **once**, only to a new empty database:

```sh
for migration in sql/migrations/*.sql; do
  docker compose -p arsia-local exec -T db \
    psql -X -v ON_ERROR_STOP=1 -U arsia_owner -d arsia < "$migration" || break
done
```

Stop on any error and use a fresh test database to diagnose it. Do not rerun
the whole migration sequence on an existing database. Set local role passwords
interactively; no extra grants are needed:

```sh
docker compose -p arsia-local exec db psql -X -U arsia_owner -d arsia -c '\password arsia_loader'
docker compose -p arsia-local exec db psql -X -U arsia_owner -d arsia -c '\password arsia_reader'
```

B connects to `host=127.0.0.1 port=55432 dbname=arsia user=arsia_loader`.
Supply its password through a protected PostgreSQL passfile or your local
credential setup. Never commit a password or put it in a receipt.

```sh
docker compose -p arsia-local stop db
docker compose -p arsia-local start db
docker compose -p arsia-local restart db
docker compose -p arsia-local down
```

These commands retain the named volume. A later `up -d --wait db` reuses it.
`down --volumes` deletes that project's database: use it only when intentionally
removing a disposable project. `restart` does not apply changed Compose config;
use `up -d` for configuration changes. See Docker's
[down](https://docs.docker.com/reference/cli/docker/compose/down/) and
[restart](https://docs.docker.com/reference/cli/docker/compose/restart/) references.

## Schema maintenance and failures

| Migrations | Content |
|---|---|
| 001–004 | Source/resource registry, Raw, initial loader role, batches and release pointer |
| 005–008 | Vault, Canonical, dimensions/facts and QA |
| 009 | Final migrator/loader/reader ownership and privileges |
| 010–011 | Ordered business keys, map eligibility and whitespace fixes |

Add a new numbered migration for a schema change. Do not edit an applied
migration. Update the dictionary and schema contract only after team agreement,
then rerun in an empty database. A changed hash is a different build input.

If Docker or Git access fails, fix access and rerun with a new output path.
For dictionary/hash errors, restore the pinned input. For schema or permission
errors, inspect the receipt and migrations; do not grant wider privileges or
patch live tables to get a pass. Retain failed receipts. If cleanup fails,
inspect the exact container/project named in that receipt and remove only
those private test resources.

## Evidence and remaining acceptance

JJ's [26 September record](evidence/a09-cold-start-2026-09-26.json) is retained.
The [A handoff](a01-a09-handoff.md) links the new replay and its actual results.
Peixian ran it as the assisting B integrator, outside JJ's original environment.
This completes the recorded A component and runnable S0 setup checks. E09 still
owns independent acceptance. Dashboard work, official publication and final
course/team sign-off are separate; no permission or acceptance is inferred.
