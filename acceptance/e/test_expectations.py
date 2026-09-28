"""Check the hand-calculated oracle without importing runtime calculations."""
from decimal import Decimal

import pytest

from e_acceptance_expected import crashes, load_expected, map_coverage, metrics, qa_objects, trends


@pytest.mark.parametrize("variant", ["s0", "revised_n1", "delete_q2", "known_n2", "s8"])
def test_hand_rows_match_separately_written_scenario_totals(variant):
    rows = crashes(variant)
    actual = metrics(rows)
    expected = load_expected()["scenario_totals"][variant]
    fields = {"crashes": "crash_count", "fatal_crashes": "fatal_crash_count",
              "fatalities": "fatality_count", "casualties": "casualty_count",
              "fatal_known": "fatal_crash_known_count", "fatality_known": "fatality_known_count",
              "casualty_known": "casualty_known_count"}
    assert {name: actual[field] for name, field in fields.items()} == {name: expected[name] for name in fields}
    assert sum(len(row["units"]) for row in rows) == expected["units"]
    assert map_coverage(rows)["point_count"] == expected["map_points"]
    if "coverage" in expected:
        assert map_coverage(rows)["coverage_percentage"] == Decimal(expected["coverage"])


def test_unknowns_zeros_and_unobserved_periods_are_distinct():
    n2 = metrics([row for row in crashes() if row["alias"] == "N2"])
    q2 = metrics([row for row in crashes() if row["alias"] == "Q2"])
    assert (n2["crash_count"], n2["fatality_known_count"], n2["fatality_count"]) == (1, 0, None)
    assert (q2["crash_count"], q2["fatality_known_count"], q2["fatality_count"]) == (1, 1, 0)
    empty = trends()["syn_nsw", 2024, None]
    assert (empty["crash_count"], empty["fatality_count"], empty["fatality_known_count"]) == (0, None, 0)
    assert map_coverage([])["coverage_percentage"] is None
    assert len(trends()) == 15 and len(trends(grain="month")) == 180
    monthly = trends(grain="month")
    assert sum(row["crash_count"] for row in monthly.values()) == 5
    assert monthly["syn_nsw", 2020, 1]["excluded_unknown_month_count"] == 1


@pytest.mark.parametrize("variant,total", [("s0", 63), ("s8", 77)])
def test_qa_coverage_uses_expected_resources_not_producer_output(variant, total):
    resources = list(load_expected()["resources"])
    if variant == "s8":
        resources.append("syn_sa_crash")
    identities = [{"resource_id": key, "file_sha256": "a" * 64, "parser_version": "test-only"}
                  for key in resources]
    groups = qa_objects(identities, variant)
    assert sum(map(len, groups.values())) == total
    if variant == "s0":
        assert {key: len(value) for key, value in groups.items()} == load_expected()["qa_rows"]
    with pytest.raises(AssertionError):
        qa_objects(identities[:-1], variant)
    assert all("batch" in objects for objects in groups.values())
