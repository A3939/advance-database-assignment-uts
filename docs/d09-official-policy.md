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
