# D09 official source limits

D09 previously allowed a combined official page and showed unavailable maps or
VIC/QLD units as zero. These outputs conflict with the pinned official reader policy.

Official pages now require one source. `query_official()` supplies availability
and reasons. The page keeps real SQL values but hides unavailable reports and
explains the source limits. Synthetic pages are unchanged. The Python/UI version
is `d09-0.1.2`; the unchanged SQL helpers remain `d09-0.1.1`.

Run `python -m pytest -q tests/test_d09.py tests/test_d09_official_policy.py`.
Result: 36 passed on 2026-09-28. E's acceptance verifier also checks the installed
assets and real official pages; its receipt records that separate database run.

Original D09: Role D, commit `d468cec2392a10a10b83c2ae8d6a5caac0516995`.
This policy fix and regression tests: Role B / Peixian, during E acceptance.
PR #46's synthetic evidence remains valid for its recorded version. It is not
evidence that this new official path passed. No shared release is changed.

The later [E replay in PR #50](https://github.com/A3939/advance-database-assignment-uts/pull/50)
passed 289 synthetic checks, 165 recovery checks and six full official checks,
all without skips. The official run used all 2,118,028 Raw records and tested
the three source pages as `arsia_reader`. Installed HTML/CSS hashes, A03 audits
and cleanup passed. Exact versions, costs and limits are in E's
`docs/role-e-acceptance/results.json`. These counts cover the replay suites,
not six individual assertions or a new human acceptance decision.

## PR review follow-up

Review found that the production context guard also hid the official-mode demo.
Commit `bbf0a5c` exempts only the explicitly labelled fixed example. Real official
snapshots still need policy metadata. The new HTTP regression failed before the
fix. The updated verifier now includes the official-policy tests.

The fresh installed-wheel suite passed 57 checks, including 15 PostgreSQL cases,
with no skips. A03 audits and cleanup passed. Run
`python tools/verify_d09_full_build_postgres.py --output NEW_DIRECTORY` from a
Python 3.12 environment with the current wheel installed. See the
[follow-up receipt](evidence/d09-demo-review-2026-09-28.json).
The earlier full official receipt keeps its original `1765269` runtime pin.
