# C07 review fixes

These changes only cover the Node location output and SQL packaging.
Grouping, exact coordinate comparison and representative selection stay the same.

- A usable location must have `EPSG:4326`. Other CRS values clear the four
  location fields and record `crs_unconfirmed`; the crash is retained.
- Raw decimals are checked for range and agreement before rounding. The
  I_crash output uses seven decimal places, with ties away from zero, matching
  PostgreSQL `numeric(10,7)`. No datum transformation is performed.
- The SQL is loaded from `arsia_c/sql/c07_vic_node_observations.sql` in the
  installed package. The original `sql/projections/` copy remains available;
  a test checks that both copies match.

## Validation

Python 3.12.6, pytest 8.4.2 and PostgreSQL 16.15 were used on 24 September 2026.

| Check | Result |
| --- | --- |
| Original C07 code with the new regression cases | 22 passed, 9 failed |
| C07, C01, C03 unit and C09 unit checks after the fix | 129 passed |
| Installed-wheel C07 checks on PostgreSQL 16 | 5 passed |

The database used A commit `c0824da06b6e7b3f73c4ddeab2114d10b7156913`,
migrations 001–010 followed by 011, and the unchanged `arsia_loader` role.
The PostgreSQL tests check the actual S0 Node query, file/parser filtering,
numeric rounding and caller rollback. A03 permission checks passed before
and after the run. The disposable database was removed after testing.

In a fresh Python 3.12 virtual environment:

```sh
python -m pip install -r requirements-c06.txt
python -m pytest -q tests/test_c07_node_location.py tests/test_c07_boundaries.py tests/test_c07_packaging.py tests/test_c01_projection.py tests/test_c03_nsw_projection.py tests/test_c09_canonical.py
python -m pip wheel --no-deps --no-build-isolation --no-index -w /tmp/c07-wheels .
python -m pip install --no-deps --force-reinstall /tmp/c07-wheels/arsia_native_intake-0.1.0-py3-none-any.whl
```

For the database checks, set `C07_TEST_DSN` to the loader connection for a
separate PostgreSQL 16 database with the A migrations above, then run:

```sh
python -m pytest -q --noconftest -o pythonpath= tests/test_c07_postgres.py
```

This validates C07's installed SQL adapter and output boundary, not the full
C04/B10 build. Role C still needs to connect the VIC projection and confirm
its integration results. Official VIC map eligibility remains restricted by
the existing CRS policy. Please review the three changes before merging.
