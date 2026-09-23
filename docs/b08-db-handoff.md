# Role A → B08 PostgreSQL handoff

Verified on 20 September 2026. Scope: `meta.source`, `meta.resource` and `raw.record` only. This is the B08 integration slice, not completion of Role A's 17-table schema or full reader-permission design.

## Baseline and files

- Branch: `jj/a01-environment`; verified code through commit `2c86229`.
- `compose.yaml`: pinned PostgreSQL 16 image; database `arsia`, owner `arsia_owner`, UTF-8, UTC and local port `127.0.0.1:55432`.
- Apply migrations **in order, once, to a fresh database**:
  1. `sql/migrations/001_meta_registry.sql`
  2. `sql/migrations/002_raw_record.sql`
  3. `sql/migrations/003_b08_loader_role.sql`
- `003` creates `arsia_loader` without a stored password. It grants schema usage and SELECT/INSERT on the three B08 tables; it does not grant UPDATE/DELETE.
- `requirements-db.txt` pins Psycopg and its binary implementation to 3.3.6 on Python 3.12.

## Reproduce on a fresh local database

Run commands from the repository root. Supply your **own** owner password through `ARSIA_DB_PASSWORD`; never commit it or put it in `.env.example`.

For Bash, run these one line at a time in the same terminal. Type your own owner password at the prompt and press Return:

```bash
read -r -s -p 'Database owner password: ' ARSIA_DB_PASSWORD
export ARSIA_DB_PASSWORD
```

```bash
docker compose config --quiet
docker compose up -d db
docker compose ps db
```

Wait until `db` reports `healthy`. With a local `psql` client, apply each migration once:

```bash
psql -h 127.0.0.1 -p 55432 -U arsia_owner -d arsia -W -v ON_ERROR_STOP=1 -f ./sql/migrations/001_meta_registry.sql
psql -h 127.0.0.1 -p 55432 -U arsia_owner -d arsia -W -v ON_ERROR_STOP=1 -f ./sql/migrations/002_raw_record.sql
psql -h 127.0.0.1 -p 55432 -U arsia_owner -d arsia -W -v ON_ERROR_STOP=1 -f ./sql/migrations/003_b08_loader_role.sql
```

At each `-W` prompt, enter the `arsia_owner` password. Then set a separate loader password interactively; do not add it to the migration:

```bash
psql -h 127.0.0.1 -p 55432 -U arsia_owner -d arsia -W -c '\password arsia_loader'
```

Install the test environment:

```bash
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements-db.txt
```

For B08, connect as `arsia_loader` to host `127.0.0.1`, port `55432`, database `arsia`. Use Psycopg 3 with `autocommit=False`, `%s` parameters and default tuple rows. The caller owns commit and rollback; `raw_load.py` does not commit. See `docs/raw-loading.md`.

For Bash, run these one line at a time. Enter the **arsia_loader** password at the hidden prompt, not the owner password:

```bash
read -r -s -p 'Loader password: ' arsia_loader_test_password
ARSIA_TEST_DSN='host=127.0.0.1 port=55432 dbname=arsia user=arsia_loader' PGPASSWORD="$arsia_loader_test_password" ./.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_raw_load_postgres.py
unset arsia_loader_test_password ARSIA_DB_PASSWORD
```

The connection settings and password are supplied only to this local test command. Do not put a password in a committed file, command argument or shared test result. PostgreSQL [cautions against keeping passwords in environment variables](https://www.postgresql.org/docs/16/libpq-envars.html); use a protected passfile or credential manager for longer-lived setups.

## Recorded evidence and limits

- PostgreSQL 16.15; database encoding UTF8; timezone UTC; database collation and character type `C.UTF-8`.
- `arsia_loader` login succeeded. SELECT/INSERT privileges were present; UPDATE/DELETE privileges were absent.
- A real INSERT into `meta.source` succeeded inside a transaction and was rolled back. An UPDATE was rejected with `permission denied for table source`.
- B08's real PostgreSQL test module: **8 passed in 2.16s** on 20 September 2026. The tests use synthetic inputs and roll back their writes.
- This does not verify official-data loading, durable commits, the full build, reader access to successful batches, or the remaining 14 tables.

Migration SHA-256 digests:

```text
001_meta_registry.sql   b44608c4baee8ce1d4ac6c3912a1a7d671772a1b305a32976b10f7bf00fe1893
002_raw_record.sql      550c022b204380af2c0b2ffffc48295df3b562fd217f99a62f392d8db15eb059
003_b08_loader_role.sql e84a2d122bcb8f5edd6ffeb9974ef48eac3910ae801d5a929286734978f9269d
```