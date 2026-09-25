# B14 PostgreSQL validation — Peixian (Role B)

I added 23 real PostgreSQL 16 recovery tests and a repeatable verifier. They cover interrupted runs, preserved batch history and release pointers, loader permissions, locking, uncertain commits and fresh-session retries. One test terminates a real database backend before COMMIT. No recovery runtime fix was needed.

The selected suite passed 158 tests, including 34 PostgreSQL tests and 124 existing unit tests. The verifier uses A's fixed migrations 001–011 and keeps the original A03 grants. It records input hashes, checks cleanup and removes its private container.

These are component tests with genuine `FrozenManifest` objects built from fixture inventories and seeded batch states. They do not certify E's FP1, publication or a complete B10 build. See the [run instructions](../recovery.md) and [validation receipt](../evidence/b14-postgres-validation-2026-09-25.json).
