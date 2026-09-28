# E acceptance handoff

This adds the remaining technical acceptance work to E's branch without
copying B's application into it. The replay installs the exact B and A commits
in [the version file](../../config/e-acceptance-versions.json), then runs in
fresh PostgreSQL 16 databases. See the [interfaces](interfaces.md),
[AT coverage](coverage.md) and [submission checklist](submission-checklist.md).

## Recorded run — 2026-09-28

[Results](results.json): 289 synthetic checks (216 in PostgreSQL modules),
165 recovery checks (34 PostgreSQL), and six full official checks passed with
no failures or skips. A's fresh schema, original A03 permissions, installed
resources, empty final tables and container cleanup passed.

The seven official files supplied 2,118,028 Raw rows. Source crash counts were
NSW 92,082, VIC 72,170 and QLD 66,624; these remain separate source results.
The complete B10 run took 1,306.537 seconds, wrote 6,699,693,248 WAL bytes and
ended at 3,809,590,295 database bytes. Recovery after the committed response was
lost took 0.053 seconds. The repeat took 60.122 seconds and returned `no_change`.
These are measured costs, not a performance guarantee or a live-demo threshold.

Runtime code was `1765269` from PR #49. The synthetic acceptance code was
`a5ef750`. The official run started from the E working tree; its recorded
acceptance-file hashes match the committed files in `a5ef750`. The receipt
keeps both execution histories rather than replacing them with a later HEAD.

Aditya owns Role E. Peixian prepared these additional expectations, tests and
replays as Role B. This does not count as Aditya's review or a new independent
human tester. Original authors and commits remain in Git history.

## Run

Use Python 3.12, Git, Docker and a checkout containing the pinned commits.
Run from the E checkout and use a new output directory each time:

```sh
git fetch origin
python3.12 tools/verify_e_acceptance.py --mode synthetic \
  --output ../e-synthetic-replay
```

The command creates separate B/A checkouts, a fresh venv and an installed
wheel. Tests run outside the source directory. It checks inventory bytes,
A's unchanged migrations 001–011 and A03 permissions. Normal callbacks use
`arsia_loader`; the owner only installs SQL, injects test faults and cleans up.
The verifier also runs A's cold-schema check and B14 recovery regressions.
Shared databases and public releases are untouched.

For the seven complete, pinned official files:

If no prepared run exists, create one with the installed runtime from the
synthetic replay. Only the seven original files are needed; no private database
or previous tester's archive is required:

```sh
../e-synthetic-replay/venv/bin/python - <<'PY'
from arsia_ingest.official import prepare_official_inputs
result = prepare_official_inputs(
    native_root="/absolute/path/to/raw_datasource",
    archive_root="/absolute/path/to/new-intake",
    project_root="../e-synthetic-replay/runtime",
)
assert result["status"] == "prepared", result
print(result["run_dir"])
PY
```

Pass that printed directory as `--prepared-run`:

```sh
python3.12 tools/verify_e_acceptance.py --mode official \
  --native-root /absolute/path/to/raw_datasource \
  --prepared-run /absolute/path/to/intake/official/runs/RUN_ID \
  --output ../e-official-replay
```

Use the existing complete official intake, not an arbitrary sample directory.
The replay rechecks its file hashes and identities. New file bytes need a
separate reviewed contract. Official sources remain separate; VIC restrictions,
unavailable maps and unavailable VIC/QLD unit reports still apply.

## Read the evidence

`OUTPUT/receipt.json` records the commits, copied acceptance-file hashes, wheel,
commands and overall result. `OUTPUT/postgres/` contains test XML, environment,
installed-file hashes, A03 audits, final table counts and database cleanup.
Detailed observations are under its evidence directory. Synthetic runs also
write `cold-start.json` and `recovery/`.

After both replays finish, create the compact checked-in result index:

```sh
python3.12 tools/summarize_e_acceptance.py \
  --synthetic ../e-synthetic-replay --official ../e-official-replay \
  --output docs/role-e-acceptance/results.json
```

The summary checks the receipts, actual JUnit cases, hashes, permissions and
cleanup. It refuses unfinished, failed or skipped runs and never overwrites an
existing result. It records counts and evidence hashes without copying Raw rows.

The hand-written oracle is
[`config/e-acceptance-s0-v1.json`](../../config/e-acceptance-s0-v1.json).
It covers the six S0 crashes, S8, changed N1, deleted Q2 and the N2 rule change.
The helper uses these rows to calculate expectations; it imports no production
loader, QA or report calculation. Required QA objects come from the declared
test resources and source/year grid, not E06's object generator.

The full S0 expectation is Raw 19, crashes/units 6/6, fatal
crashes/fatalities/casualties 2/3/7, map 4/6 and 63 QA rows. These are expected
values, not a run result. Actual PASS/FAIL and test counts belong to the
generated receipts. A selected test or an old receipt is not proof of a new run.

## Review and remaining work

E should review the oracle, AT coverage, fault outcomes and evidence scopes,
then replay the commands. Module defects go back to their owners through
separate fixes; acceptance tests must not replace a failed expectation with
the observed result.

E09 still needs an actual replay by a member uninvolved in environment setup.
Record that person's name, machine, commands and results. The current automated
B-assisted replay cannot supply that person's participation.

A separate official sample experiment is also pending. The current VIC policy
requires the complete four-file Raw profile, so an arbitrary subset cannot
stand in for a valid official build. The existing 308-row case covers C06 only.
E defines the experiment, B prepares parent-complete inputs and hashes, and C/E
review its profile. This uses the existing data; no new user upload is needed.

E01 teacher decisions and E10 report, recording and signed meeting records
remain human work. `independent_member_signoff` and `final_platform_accepted`
stay false until their separate requirements are met. These files are technical
handoff notes, not the course final report.
