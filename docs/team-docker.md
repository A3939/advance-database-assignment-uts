# Team Docker setup

Use this package for a local database, the S0 build and the D09 page. Only Git
and Docker Desktop with Compose are needed on the host, with access to this
repository. Start Docker Desktop
before running the commands. Python 3.12.6, PostgreSQL 16.15 and the Python
packages run in the pinned images.

The daily database keeps work between runs. Acceptance uses a different Compose
project and volume because its tests clear their own rows. Never point the
acceptance service at the daily database.

## Select the code and local settings

Clone the repository or use an existing clean checkout. Keep unfinished changes
in their current checkout. For an exact replay, select the reviewed **Docker
package commit** supplied in the handoff:

```text
git clone https://github.com/A3939/advance-database-assignment-uts.git arsia
cd arsia
git fetch origin
git switch --detach FULL_PACKAGE_COMMIT
git rev-parse HEAD
```

The tested implementation is
`f9d22c698e2a47559923179da3c76fd7d53b13a6`; use that for `FULL_PACKAGE_COMMIT`.
The later handoff commit only adds these notes and the compact receipt, outside
the Docker build context. The older B baseline listed below does not contain this package. For development, switch to your own branch
instead. Do not overwrite another member's branch.

Create `.env` once. On macOS:

```sh
cp -n .env.example .env
open -e .env
mkdir -p artifacts/team
```

On Windows PowerShell:

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
New-Item -ItemType Directory -Force artifacts/team | Out-Null
```

Replace all `REPLACE_...` values. Use three different local passwords. Set
`ARSIA_PROJECT=arsia-yourname`, `ARSIA_EXECUTOR` to the person actually
running the commands, and `ARSIA_REVISION` to the full result of
`git rev-parse HEAD`. Choose unused DB/web ports if 55432/8765 are busy.
Keep the project name, passwords and `.env` for later runs. `.env` is ignored;
do not commit it or share its contents.

Use `ARSIA_PROJECT`, not Docker's `COMPOSE_PROJECT_NAME`. Do not export the
latter or pass the same `-p` to both files: it overrides their separate names.
`docker compose config` and `docker compose -f compose.acceptance.yaml config`
must show different project names. The Git attributes keep text/fixture bytes
stable across Windows and macOS.

The commands below work in both shells, from the repository root.

On Linux hosts, a bind-mounted evidence directory may need UID 10001 ownership.
After building, this command changes only the selected output directory:

```sh
docker compose run --rm --no-deps --user 0 --entrypoint python app -c "import os; os.chown('/evidence', 10001, 10001)"
```

Linux host filesystem permissions still need a native team replay.

## Build and use the daily environment

```sh
docker compose config --quiet
docker compose --profile tools build app
docker compose up -d --wait db
docker compose --profile tools run --rm app info
docker compose --profile tools run --rm app init
docker compose --profile tools run --rm app s0
docker compose --profile tools run --rm app status
docker compose --profile web up -d dashboard
```

Open `http://localhost:8765/` (or your configured web port). This page reads the
real published S0 batch. Expected values are 6 crashes, 6 units, measures 2/3/7,
4 mapped crashes and 63 QA rows. QA07 retains its expected `limited` result for
two crashes without usable coordinates. A repeat `s0` should return `no_change`.

`init` applies A's unchanged migrations 001–011 only to a fresh database, then
installs FP1 and D05–D09 SQL. It checks the installed wheel, source hashes,
17 tables/129 columns, constraints and A03 permissions. Subsequent calls verify
the existing installation without clearing rows. An unknown, partial or changed
installation is refused; inspect the error instead of deleting data to hide it.

The owner installs SQL. Builds log in as `arsia_loader`; the page logs in as
`arsia_reader`. The page binds only to the host loopback interface.

## Run acceptance separately

```sh
docker compose -f compose.acceptance.yaml up -d --wait acceptance-db
docker compose -f compose.acceptance.yaml run --rm acceptance
docker compose -f compose.acceptance.yaml down --volumes --remove-orphans
```

This uses `<project-name>-acceptance`, its own network and
`acceptance_pgdata` volume, with no published database port. It runs the installed
E synthetic checks, B recovery tests and UI/build checks outside the source
directory. The test reader shares the loader's test password because the
existing isolated fixtures require that; daily credentials stay separate.

Each command writes a new directory under `artifacts/team/`. Read `receipt.json`,
test XML and logs. A failed or skipped test is not acceptance. Keep failed
receipts too. After inspecting any failure, the cleanup command above removes
only the acceptance project and its volume; it keeps the saved evidence.

## Optional official build

Put the **seven complete pinned original files** in a local directory, using
their catalogue filenames. Set `ARSIA_OFFICIAL_DIR` in `.env`, for example
`/Users/yourname/arsia-official` or `C:/Users/yourname/arsia-official`.
The path must already exist. Do not use the 308-row C06 case as a full input.

```sh
docker compose -f compose.yaml -f compose.official.yaml --profile tools run --rm app official-check
docker compose -f compose.yaml -f compose.official.yaml --profile tools run --rm app official-build
```

`official-check` checks file identities only. The second command performs the
real build in the daily database and retains evidence. The original files are
mounted read-only at `/official`; they are not copied into the image or committed
by this workflow. Prepared archives and JSONL files stay in the daily `appdata`
volume at `/data`. Keep that volume with the database: later checks may need
earlier archives.

Read one official source at a time, for example
`http://localhost:8765/?mode=official&sources=official_vic`. VIC restrictions and
unavailable maps or unit reports remain visible. A local publication is not a
public release. The default acceptance command does not run official inputs.

## Stop, resume and recover

```sh
docker compose --profile web stop
docker compose --profile web start
docker compose --profile web restart
docker compose --profile web --profile tools down
```

These retain daily `pgdata`, `appdata` and host evidence. After `down`, use
`docker compose --profile web up -d --wait` to recreate the services.
`restart` does not rebuild an image or apply changed Compose settings.

If a build reports `unknown_commit`, keep its evidence and recover that exact
run before retrying. Use the inner run directory containing its `result.json`:

```sh
docker compose --profile tools run --rm app recover --run-dir /evidence/SAVED_COMMAND/build/SAVED_RUN
```

Replace the two saved-directory names with those in the failed receipt. Recovery
checks the original database; it does not start a replacement build.

To intentionally erase a disposable **daily** environment, the command is:

```sh
docker compose --profile web --profile tools down --volumes --remove-orphans
```

This deletes daily database and archive volumes. Do not use it for normal stops.
It leaves `artifacts/team/` on the host.

## Changes, versions and evidence

The image installs a wheel; it does not mount your source as live Python code.
After code changes on your branch, review the change, refresh affected inventory
hashes, commit it, update `ARSIA_REVISION`, and rebuild the image. A changed
inventory is not automatically applied to an existing daily database. Use a new
project name for a new test baseline, retaining the previous project and volumes.
For a recorded replay, use exactly the reviewed package commit and a clean tree.

The optional `workspace` service runs development tools on your local files:

```sh
docker compose run --rm workspace -m pytest -q tests/test_runner.py
docker compose run --rm workspace tools/update_build_inventory.py
git diff -- config
```

Run the inventory command only after reviewing the affected code. It refreshes
the actual hashes, not business rules. Rebuild the app and rerun acceptance
afterward. Development tests can import edited source; the acceptance service
still checks the rebuilt, installed wheel.

[`docker/team/sources.json`](../docker/team/sources.json) records original paths,
commits and hashes. This package reuses:

- B integration: `ade3d4cf9ac32f1740b6e40124f72f469d6cf630`.
- A environment: `8f91a6b41dc0777d5873d2151f71e9f1cbe05501`; unchanged schema:
  `c0824da06b6e7b3f73c4ddeab2114d10b7156913`.
- E acceptance: `eba079a59ab7eb41835ee044c12e45dbdca03e9b`.

E's earlier full acceptance tested runtime `1765269`. That historical result
does not certify this Docker package. Original A/C/D/E authorship remains in
Git; Peixian adds this packaging and its checks.

The tested host was Apple Silicon macOS with Docker 28.5.2 and Compose 2.40.3.
Native ARM64 and emulated AMD64 each passed **501 checks, 0 failed, 0 skipped**:
290 E synthetic, 165 recovery, 8 UI/build and 38 wrapper checks. Both app and
PostgreSQL architecture were checked. This does not verify native AMD64 hardware.
The ARM64 default suite passed 1,072 checks; 402 optional database/data checks
skipped. Its optional pytest cache was unavailable in the read-only image tree.
The dedicated suite supplies its own database and allows no skips.

Both architectures passed S0, repeat `no_change`, HTTP/error handling, unchanged
rows after stop/start, restart and DB container recreation, rejection of daily
DB acceptance, and separate acceptance cleanup. All task-owned test containers
and volumes were removed afterward; host evidence was retained. ARM64 also
checked the seven official-file hashes and read-only mounting. The official
full-data build was **NOT_RUN** for this package: application code and inventory
were unchanged, and this run covers packaging and the synthetic database path.

[The compact receipt](evidence/team-docker-2026-09-29.json) records commits,
image IDs, wheel hashes, commands, results and hashes of local evidence under
`artifacts/team/final-arm64/` and `artifacts/team/final-amd64/`. Native Windows,
AMD64 hardware and Linux host filesystem permissions remain **NOT_RUN**.
Do not copy these results into a new member's receipt.

A member who did not write the environment must perform the independent replay.
They should record their own name, machine/OS, selected commit, commands,
receipt paths and any missing steps. `ARSIA_EXECUTOR` is a declaration, not proof
of independent participation. The automated receipts keep human sign-off and
final platform acceptance false. Teacher decisions, final report, recording and
signed meeting records remain separate team work.
