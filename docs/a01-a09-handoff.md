# A01/A09 handoff

## Changes

The old A09 guide needed a dictionary outside the checkout and reused an
already committed output path. It also covered only the database component.
This handoff keeps the dictionary in Git, documents a fresh install, and adds
real Compose lifecycle and installed S0 replay commands.

The schema verifier now exercises the 011 fixes and uses exact table counts.
Compose accepts a configurable loopback port. `typing_extensions` is pinned,
and its requirements file hash is updated in the baseline's partial inventory.
No migration, A03 grant, application callback or business rule was changed.

## Versions and credit

- JJ's A01 work: `1b257c831c665e1c8d38ca7b6b0d2f8ed02afed1`.
- JJ's original A09: `43d0fd040f743132b90f0808f2c51e770bdf2972`,
  [PR #32](https://github.com/A3939/advance-database-assignment-uts/pull/32).
- Fixed A schema: `c0824da06b6e7b3f73c4ddeab2114d10b7156913`,
  [PR #5](https://github.com/A3939/advance-database-assignment-uts/pull/5).
- Runnable B integration: `562de2910bfd7be276b3036983e5680d436fde1e`.
- This environment, documentation and verification follow-up: Role B / Peixian.

JJ remains the author of A's original work. Peixian replayed the setup outside
JJ's environment and added these checks. This is an assisted integration
replay, not E09's independent final acceptance.

## Reproduce

Follow the [cold-start guide](cold-start-and-schema-maintenance.md). Its three
tools are `tools/verify_a09_cold_start.py`, `tools/verify_a01_lifecycle.py` and
`tools/verify_a09_synthetic.py`. Use Python 3.12.6, the pinned PostgreSQL 16.15
image and a running Docker daemon. The S0 tool also needs repository access.

Recorded results:

| Check | Result |
|---|---|
| A default suite | 624 passed, 155 skipped |
| A09 focused tests, included above | 9 passed |
| Fresh A database | All 11 migrations; 17 tables / 129 fields; schema and A03 audits pass |
| Migration 011 smoke | Blank keys and invalid CRS rejected; valid values accepted; rolled back |
| Compose lifecycle | Real loader/reader logins; stop/start, restart and down/up retain committed data |
| Installed B S0 suite | 335 passed, 0 skipped, including 112 real PostgreSQL tests |
| Cleanup | Private containers/volumes removed; S0 final application tables empty |

Default-suite skips need separate PostgreSQL or source fixtures; they are not
passes. The 335-test S0 suite overlaps with B's existing tests and is not an
additional 335 new tests. It uses 19 synthetic Raw records, the real callbacks,
FP1, QA01–QA07 and private synthetic publication. It does not publish official data.

The committed [evidence index](evidence/a01-a09-20260928/index.json) records
the tested implementation commit and file hashes. It links separate schema,
lifecycle, default-suite and S0 receipts. Full command logs, the installed
wheel and runtime checkout are local outputs; reviewers can recreate them
with the commands above. JJ's original 26 September receipt is retained.

## JJ review and next steps

1. Review this follow-up into `jj/a09-cold-start-guide`. Check the unchanged
   dictionary hash, schema/grants, install commands and recorded scope.
2. After merging it, review PR #32 against `main`; this follow-up updates its
   head branch. Do not treat the older main application baseline as B's latest
   integration. Other A task branches keep their own commits and evidence.
3. Give E the pinned revision and fresh-run commands for E09. E records its own
   execution and any resource/acceptance checks required by the team contract.

A's component setup and runnable S0 handoff are covered here. Final team/course
decisions, source permissions, dashboard work, official publication and E09
acceptance remain with their owners. This PR does not close those items or
change task statuses on the website.
