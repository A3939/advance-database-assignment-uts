# C02 / C06 code handoff

Target branch: `yue/role-c`. Base commit:
`87d1c5803a6ec61475823ea877a995ba589f22f7`.

This delivery contains the C02 source review, the adopted VIC policy, C06 SQL
and Python, test source, source observations and reproduction instructions.
Generated development test reports and machine-environment receipts are stored
separately by the team and are not part of this code delivery. Their omission
is not a claim that validation was performed on a particular member's computer.

Start with [C02](c02-vic-person-node-review.md),
[C06](c06-person-checks.md) and the
[source-material index](c02-evidence-index.json).

## Scope

C06 checks Person keys, Accident parents, native Vehicle references, exact
registered exceptions, declared counts and Raw evidence. Its SQL and adapter
remain `c06-person-v0.3`; the business implementation is unchanged by packaging.
Node checks, Vehicle count reconciliation, complete C10 QA, D's restricted
outputs and E's publication gate are separate integration work.

This branch contains B's earlier `team-v1.1` implementation. C06's standalone
`review_restricted` entry supports the pinned official Person diagnostics.
Newer B work has `team-v1.1-vic-r1` support, but is not included in this delivery.
Its evidence guard requires the byte-identical source validation records listed
as external in the index: `cross-check.json`, `validation.json` and `pytest.xml`.
B/E must restore those originals at the recorded repository paths before that
guard can pass. Do not replace them with a new run or edit policy hashes.
A complete official B-to-C build is therefore not self-contained in this ZIP.

## Reproduce

Use Python 3.12 from the repository root. If an environment is already available,
activate it and skip environment creation. Otherwise:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-c06.txt
```

On Windows, create the environment with `py -3.12 -m venv .venv` and activate
`.venv\Scripts\Activate.ps1` in PowerShell. The commands below use that
active environment. No neighbouring checkout or personal directory is required.

```sh
python -m pytest -q -p no:cacheprovider tests/test_person_checks.py tests/test_restricted_person.py tests/test_c06_postgres.py tests/test_c06_replay_cli.py
python -m pytest -q -p no:cacheprovider tests
```

Without `ARSIA_TEST_DSN`, PostgreSQL tests are skipped. A skip is not an SQL pass.
For actual database checks, obtain an isolated PostgreSQL 16 test database from
A, with `meta.source`, `meta.resource` and `raw.record` initialized, UTF-8/UTC and
the loader's SELECT/INSERT grants. Set `ARSIA_TEST_DSN` without a password and
use a protected `PGPASSFILE`. Do not place credentials in this repository.
C includes no migration or database installer; fixtures roll back test rows.
Keep any generated XML or logs in ignored `.local/` or `artifacts/` directories.

Tests import this repository by default. `ARSIA_REPOSITORY` is only for an
explicit compatibility run using a different B checkout. See
[C06](c06-person-checks.md#reproduce) for the official-case excerpt command and
original-data requirements.

## Source observations and separate records

Included source JSON and contract snapshots retain their original bytes.
The [source archive notes](../sources/evidence/vic/followup-2026-09-23/README.md)
explain which generated validation records are held separately. Frozen policy
paths and hashes are retained as provenance, not rewritten to suggest a new
source review. Historical team snapshots retain their original folder links;
use the current C02/C06 documents and index when navigating this package.

The source observations do not establish publisher approval, a compatible full
release, full official Raw validation or end-to-end publication acceptance.
The team keeps the actual execution records and B/E record downstream
reproduction before marking a handoff accepted.

## Submit this scope

Use [the file list](c02-c06-submit-files.txt) after applying the delivery.
Review any previously staged work separately. From a clean staging area:

```sh
git status --short
git diff --check
git add --pathspec-from-file=docs/role-c/c02-c06-submit-files.txt
git diff --cached --stat
git diff --cached --check
git commit -m "Implement C02 review and C06 restricted Person checks"
git push origin HEAD:refs/heads/yue/role-c
```

Use the submitting member's existing authorized Git configuration. This package
contains no Git directory, credentials, signing key, generated commit or test
results, and does not change the configured author or committer. Do not force
push; if the remote advances, integrate the new commits and review again.
