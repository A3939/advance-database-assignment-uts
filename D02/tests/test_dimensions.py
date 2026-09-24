from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from uuid import UUID

from arsia_d02.dimensions import (
    DimensionContractError,
    build_dimension_rows,
    load_dimensions,
    runner_callback,
)


FIXTURE = Path(__file__).parent / "fixtures" / "s0-manifest.json"
BATCH_ID = "12345678-1234-5678-9234-567812345678"


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class FakeCursor:
    def __init__(self, database):
        self.database = database
        self.result = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def executemany(self, sql, rows):
        if "dw.dim_source" in sql:
            table, key = self.database.sources, lambda r: (r[0], r[1])
        elif "dw.dim_month" in sql:
            table, key = self.database.months, lambda r: (r[0],)
        elif "dw.dim_severity" in sql:
            table, key = self.database.severities, lambda r: (r[0], r[1], r[2])
        else:
            raise AssertionError(sql)
        for row in rows:
            table.setdefault(key(row), tuple(row))

    def execute(self, sql, parameters):
        if "FROM dw.dim_source" in sql:
            batch = parameters[0]
            self.result = sorted(
                (r for r in self.database.sources.values() if r[0] == batch),
                key=lambda r: r[1],
            )
        elif "FROM dw.dim_month" in sql:
            year_from, year_to = parameters
            self.result = sorted(
                (r for r in self.database.months.values() if year_from <= r[1] <= year_to),
                key=lambda r: (r[1], r[2]),
            )
        elif "FROM dw.dim_severity" in sql:
            batch = parameters[0]
            self.result = sorted(
                (r for r in self.database.severities.values() if r[0] == batch),
                key=lambda r: (r[1], r[2]),
            )
        else:
            raise AssertionError(sql)

    def fetchall(self):
        return list(self.result)


class FakeDatabase:
    autocommit = False

    def __init__(self):
        self.sources = {}
        self.months = {}
        self.severities = {}

    def cursor(self):
        return FakeCursor(self)


class Frozen:
    def __init__(self, value):
        self.value = value

    def as_dict(self):
        return deepcopy(self.value)


class Evidence:
    def __init__(self):
        self.records = {}

    def write_json(self, name, value):
        self.records[name] = value


class DimensionTests(unittest.TestCase):
    def test_s0_builds_expected_complete_dimensions(self):
        rows = build_dimension_rows(fixture(), BATCH_ID)
        self.assertEqual(rows.counts(), {"dim_source": 3, "dim_month": 60, "dim_severity": 12})
        self.assertEqual(rows.months[0], (202001, 2020, 1))
        self.assertEqual(rows.months[-1], (202412, 2024, 12))
        self.assertEqual({r[1] for r in rows.sources}, {"syn_nsw", "syn_vic", "syn_qld"})
        self.assertEqual(
            {r[1] for r in rows.severities if r[2] == "__MISSING__"},
            {"syn_nsw", "syn_vic", "syn_qld"},
        )

    def test_loader_is_idempotent_and_verifies_database_rows(self):
        database = FakeDatabase()
        first = load_dimensions(database, BATCH_ID, fixture())
        second = load_dimensions(database, BATCH_ID, fixture())
        self.assertEqual(first, second)
        self.assertEqual((len(database.sources), len(database.months), len(database.severities)), (3, 60, 12))

    def test_existing_same_key_with_different_content_is_rejected(self):
        database = FakeDatabase()
        rows = build_dimension_rows(fixture(), BATCH_ID)
        wrong = list(rows.sources[0])
        wrong[2] = "Wrong frozen name"
        database.sources[(wrong[0], wrong[1])] = tuple(wrong)
        with self.assertRaisesRegex(DimensionContractError, "differ from the frozen manifest"):
            load_dimensions(database, BATCH_ID, fixture())

    def test_runner_callback_uses_frozen_manifest_and_writes_evidence(self):
        database, evidence = FakeDatabase(), Evidence()
        context = SimpleNamespace(
            batch_id=UUID(BATCH_ID), manifest=Frozen(fixture()), evidence=evidence
        )
        counts = runner_callback(database, context)
        self.assertEqual(counts["dim_month"], 60)
        self.assertEqual(
            evidence.records["d02-dimensions.json"],
            {"batch_id": BATCH_ID, "counts": counts},
        )

    def test_duplicate_source_code_is_rejected(self):
        value = fixture()
        value["rules"]["severity"].append(deepcopy(value["rules"]["severity"][0]))
        with self.assertRaisesRegex(DimensionContractError, "more than one definition"):
            build_dimension_rows(value, BATCH_ID)

    def test_every_source_requires_explicit_missing_category(self):
        value = fixture()
        value["rules"]["severity"] = [
            item
            for item in value["rules"]["severity"]
            if not (item["source_id"] == "syn_qld" and item["severity_code"] == "__MISSING__")
        ]
        with self.assertRaisesRegex(DimensionContractError, "explicit __MISSING__"):
            build_dimension_rows(value, BATCH_ID)

    def test_reversed_year_range_is_rejected(self):
        value = fixture()
        value["analysis"] = {"year_from": 2024, "year_to": 2020}
        with self.assertRaisesRegex(DimensionContractError, "must not exceed"):
            build_dimension_rows(value, BATCH_ID)


if __name__ == "__main__":
    unittest.main()
