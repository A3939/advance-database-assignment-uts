"""Opt-in PostgreSQL checks for A06's five-table Vault loader."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from arsia_ingest.models import IntakeError
from arsia_ingest.vault_load import iter_satellites, load_vault
from test_raw_load_postgres import connection


pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="Real PostgreSQL Vault tests require A's migrated database and ARSIA_TEST_DSN",
)


@dataclass
class Evidence:
    values: dict

    def write_json(self, name, value):
        assert name not in self.values
        self.values[name] = value
        return {"path": name}


class Manifest:
    def __init__(self, value):
        self.value = value

    def as_dict(self):
        return json.loads(json.dumps(self.value))


def create_projection_tables(connection):
    connection.execute(
        """CREATE TEMP TABLE arsia_i_crash (
            batch_id uuid NOT NULL,
            source_id text NOT NULL,
            release_scope text NOT NULL,
            crash_key text NOT NULL,
            raw_record_id uuid NOT NULL,
            occurrence_year integer NOT NULL,
            occurrence_month integer,
            occurrence_date date,
            date_precision text NOT NULL,
            severity_raw text,
            severity_code text NOT NULL,
            severity_definition_version text NOT NULL,
            is_fatal_crash boolean,
            fatality_count integer,
            casualty_count integer,
            fatal_crash_eligible boolean NOT NULL,
            fatality_eligible boolean NOT NULL,
            casualty_eligible boolean NOT NULL,
            latitude numeric(10, 7),
            longitude numeric(10, 7),
            location_crs text,
            map_eligible boolean NOT NULL,
            location_record_id uuid,
            quality_notes jsonb NOT NULL
        )"""
    )
    connection.execute(
        """CREATE TEMP TABLE arsia_i_unit (
            batch_id uuid NOT NULL,
            source_id text NOT NULL,
            release_scope text NOT NULL,
            unit_key text NOT NULL,
            crash_key text NOT NULL,
            raw_record_id uuid NOT NULL,
            unit_type_raw text,
            unit_type_code text,
            statistical_scope text NOT NULL,
            count_eligible boolean NOT NULL,
            quality_notes jsonb NOT NULL
        )"""
    )


@pytest.fixture
def projection(connection):
    suffix = uuid4().hex
    source_id = f"syn_a06_{suffix}"
    crash_resource = f"{source_id}_crash"
    unit_resource = f"{source_id}_unit"
    batch_id = uuid4()
    crash_raw_id = uuid4()
    unit_raw_id = uuid4()

    connection.execute(
        "INSERT INTO meta.source(source_id, jurisdiction_code, source_name, publisher) "
        "VALUES (%s, 'TEST', 'A06 synthetic source', 'ARSIA tests')",
        (source_id,),
    )
    with connection.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO meta.resource(resource_id, source_id, resource_role, entity_kind) "
            "VALUES (%s, %s, %s, %s)",
            [
                (crash_resource, source_id, "crash", "crash"),
                (unit_resource, source_id, "unit", "unit"),
            ],
        )
        cursor.executemany(
            """INSERT INTO raw.record(
                   raw_record_id, resource_id, source_id, file_sha256,
                   parser_version, row_locator, payload)
               VALUES (%s, %s, %s, %s, 'a06-test-v1', %s, %s::jsonb)""",
            [
                (crash_raw_id, crash_resource, source_id, "a" * 64,
                 "test:crash:1", json.dumps({"Crash ID": "0001"})),
                (unit_raw_id, unit_resource, source_id, "b" * 64,
                 "test:unit:1", json.dumps({"Crash ID": "0001", "Unit ID": "01"})),
            ],
        )
    connection.execute(
        """INSERT INTO meta.batch(
               batch_id, dataset_kind, input_fingerprint, manifest)
           VALUES (%s, 'synthetic', %s, '{}'::jsonb)""",
        (batch_id, "c" * 64),
    )
    create_projection_tables(connection)
    connection.execute(
        """INSERT INTO arsia_i_crash VALUES (
            %s, %s, 's0', '["0001"]', %s,
            2020, 1, NULL, 'month', 'F', 'F', 'syn-1', TRUE,
            2, 3, TRUE, TRUE, TRUE,
            %s, %s, 'EPSG:4326', TRUE, %s, '{}'::jsonb
        )""",
        (batch_id, source_id, crash_raw_id, Decimal("-33.8600000"),
         Decimal("151.2000000"), crash_raw_id),
    )
    connection.execute(
        """INSERT INTO arsia_i_unit VALUES (
            %s, %s, 's0', '["0001", "01"]', '["0001"]', %s,
            'CAR', 'CAR', 'synthetic_traffic_unit', TRUE, '{}'::jsonb
        )""",
        (batch_id, source_id, unit_raw_id),
    )
    manifest = {
        "sources": [{"source_id": source_id, "release_scope": "s0"}],
        "files": [
            {"source_id": source_id, "resource_id": crash_resource,
             "entity_kind": "crash", "file_sha256": "a" * 64,
             "parser_version": "a06-test-v1"},
            {"source_id": source_id, "resource_id": unit_resource,
             "entity_kind": "unit", "file_sha256": "b" * 64,
             "parser_version": "a06-test-v1"},
        ],
    }
    context = SimpleNamespace(
        batch_id=str(batch_id), manifest=Manifest(manifest), evidence=Evidence({}),
    )
    return context


def test_vault_loads_five_tables_and_preserves_types(connection, projection):
    result = load_vault(connection, projection)

    assert result.__dict__ == {
        "crash_count": 1,
        "unit_count": 1,
        "crash_hubs_inserted": 1,
        "unit_hubs_inserted": 1,
        "crash_satellites_inserted": 1,
        "unit_satellites_inserted": 1,
        "links_inserted": 1,
    }
    assert projection.evidence.values == {"counts.json": result.__dict__}
    counts = connection.execute(
        """SELECT
             (SELECT count(*) FROM rv.hub_crash WHERE first_seen_batch_id = %s),
             (SELECT count(*) FROM rv.hub_unit WHERE first_seen_batch_id = %s),
             (SELECT count(*) FROM rv.sat_crash WHERE batch_id = %s),
             (SELECT count(*) FROM rv.sat_unit WHERE batch_id = %s),
             (SELECT count(*) FROM rv.link_crash_unit WHERE batch_id = %s)""",
        (projection.batch_id,) * 5,
    ).fetchone()
    assert counts == (1, 1, 1, 1, 1)

    crash_attributes = connection.execute(
        "SELECT attributes FROM rv.sat_crash WHERE batch_id = %s",
        (projection.batch_id,),
    ).fetchone()[0]
    assert crash_attributes["occurrence_year"] == 2020
    assert crash_attributes["occurrence_date"] is None
    assert crash_attributes["fatal_crash_eligible"] is True
    assert crash_attributes["fatality_count"] == 2
    assert "batch_id" not in crash_attributes
    assert "raw_record_id" not in crash_attributes

    unit_attributes = connection.execute(
        "SELECT attributes FROM rv.sat_unit WHERE batch_id = %s",
        (projection.batch_id,),
    ).fetchone()[0]
    assert unit_attributes["crash_key"] == '["0001"]'
    assert unit_attributes["count_eligible"] is True

    crashes = list(iter_satellites(connection, projection, "crash", fetch_size=1))
    units = list(iter_satellites(connection, projection, "unit", fetch_size=1))
    assert len(crashes) == len(units) == 1
    assert crashes[0]["crash_key"] == units[0]["crash_key"] == '["0001"]'
    assert units[0]["unit_key"] == '["0001", "01"]'


def test_vault_rejects_foreign_batch_without_writes(connection, projection):
    connection.execute("UPDATE arsia_i_crash SET batch_id = %s", (uuid4(),))

    with pytest.raises(IntakeError) as error:
        load_vault(connection, projection)

    assert error.value.code == "VAULT_SCOPE"
    assert connection.execute(
        "SELECT count(*) FROM rv.hub_crash WHERE first_seen_batch_id = %s",
        (projection.batch_id,),
    ).fetchone()[0] == 0


def test_vault_rejects_orphan_unit_without_writes(connection, projection):
    connection.execute(
        "UPDATE arsia_i_unit SET unit_key = %s, crash_key = %s",
        ('["0999", "01"]', '["0999"]'),
    )

    with pytest.raises(IntakeError) as error:
        load_vault(connection, projection)

    assert error.value.code == "VAULT_ORPHAN_UNIT"
    assert connection.execute(
        "SELECT count(*) FROM rv.hub_crash WHERE first_seen_batch_id = %s",
        (projection.batch_id,),
    ).fetchone()[0] == 0


def test_vault_rejects_raw_row_from_different_frozen_file(connection, projection):
    projection.manifest.value["files"][0]["file_sha256"] = "d" * 64

    with pytest.raises(IntakeError) as error:
        load_vault(connection, projection)

    assert error.value.code == "VAULT_LINEAGE"


def test_vault_rejects_out_of_range_map_coordinates(connection, projection):
    connection.execute("UPDATE arsia_i_crash SET latitude = 91")

    with pytest.raises(IntakeError) as error:
        load_vault(connection, projection)

    assert error.value.code == "VAULT_INVALID_PROJECTION"


def test_vault_rejects_duplicate_projection_keys(connection, projection):
    connection.execute("INSERT INTO arsia_i_crash SELECT * FROM arsia_i_crash")

    with pytest.raises(IntakeError) as error:
        load_vault(connection, projection)

    assert error.value.code == "VAULT_DUPLICATE_KEY"


def test_existing_hub_keeps_first_seen_batch(connection, projection):
    first = load_vault(connection, projection)
    first_batch = projection.batch_id
    second_batch = str(uuid4())
    connection.execute(
        """INSERT INTO meta.batch(
               batch_id, dataset_kind, input_fingerprint, manifest)
           VALUES (%s, 'synthetic', %s, '{}'::jsonb)""",
        (second_batch, "e" * 64),
    )
    connection.execute("UPDATE arsia_i_crash SET batch_id = %s", (second_batch,))
    connection.execute("UPDATE arsia_i_unit SET batch_id = %s", (second_batch,))
    second_context = SimpleNamespace(
        batch_id=second_batch,
        manifest=projection.manifest,
        evidence=Evidence({}),
    )

    second = load_vault(connection, second_context)

    assert first.crash_hubs_inserted == first.unit_hubs_inserted == 1
    assert second.crash_hubs_inserted == second.unit_hubs_inserted == 0
    assert second.crash_satellites_inserted == 1
    assert second.unit_satellites_inserted == 1
    assert second.links_inserted == 1
    first_seen = connection.execute(
        "SELECT first_seen_batch_id::text FROM rv.hub_crash "
        "WHERE first_seen_batch_id = %s",
        (first_batch,),
    ).fetchone()[0]
    assert first_seen == first_batch
