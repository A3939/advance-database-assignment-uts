from __future__ import annotations

import pytest

from arsia_c.projections.nsw import (
    _contract_by_id,
    _mapping_by_id,
    _validate_relationship_counts,
)


def _manifest() -> dict:
    return {
        "rules": {
            "contracts": [
                {
                    "id": "official_nsw_crash",
                    "mapping_ids": [
                        "nsw-crash-projection-v1"
                    ],
                },
                {
                    "id": "official_nsw_traffic_unit",
                    "mapping_ids": [
                        "nsw-traffic-unit-projection-v1"
                    ],
                },
            ],
            "mappings": [
                {
                    "id": "nsw-crash-projection-v1",
                    "content": {},
                },
                {
                    "id": "nsw-traffic-unit-projection-v1",
                    "content": {
                        "statistical_scope":
                            "NSW traffic units"
                    },
                },
            ],
        }
    }


def test_contract_by_id_returns_exact_contract():
    manifest = _manifest()

    contract = _contract_by_id(
        manifest,
        "official_nsw_crash",
    )

    assert contract["id"] == "official_nsw_crash"


def test_contract_by_id_rejects_missing_contract():
    manifest = _manifest()

    with pytest.raises(
        ValueError,
        match="expected exactly one contract",
    ):
        _contract_by_id(
            manifest,
            "missing_resource",
        )


def test_contract_by_id_rejects_duplicate_contract():
    manifest = _manifest()

    manifest["rules"]["contracts"].append(
        {
            "id": "official_nsw_crash",
            "mapping_ids": [
                "duplicate-mapping"
            ],
        }
    )

    with pytest.raises(
        ValueError,
        match="expected exactly one contract",
    ):
        _contract_by_id(
            manifest,
            "official_nsw_crash",
        )


def test_mapping_by_id_returns_exact_mapping():
    manifest = _manifest()

    mapping = _mapping_by_id(
        manifest,
        "nsw-traffic-unit-projection-v1",
    )

    assert (
        mapping["content"]["statistical_scope"]
        == "NSW traffic units"
    )


def test_mapping_by_id_rejects_missing_mapping():
    manifest = _manifest()

    with pytest.raises(
        ValueError,
        match="expected exactly one mapping",
    ):
        _mapping_by_id(
            manifest,
            "missing-mapping",
        )


def test_relationship_validation_accepts_zero_counts():
    _validate_relationship_counts(
        (0, 0, 0, 0, 0)
    )


@pytest.mark.parametrize(
    "counts",
    [
        (1, 0, 0, 0, 0),
        (0, 1, 0, 0, 0),
        (0, 0, 1, 0, 0),
        (0, 0, 0, 1, 0),
        (0, 0, 0, 0, 1),
    ],
)
def test_relationship_validation_blocks_nonzero_counts(
    counts,
):
    with pytest.raises(
        ValueError,
        match="NSW relationship validation failed",
    ):
        _validate_relationship_counts(counts)


def test_relationship_validation_rejects_no_result():
    with pytest.raises(
        ValueError,
        match="returned no result",
    ):
        _validate_relationship_counts(None)
