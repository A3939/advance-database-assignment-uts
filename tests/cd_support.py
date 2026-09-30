"""Real B interfaces with a partial C/D component inventory."""

import json

from arsia_ingest.components import bindings
from arsia_ingest.manifest import FrozenManifest, read_json
from d02_support import ROOT, interface_manifest as d02_manifest


def fragment():
    return read_json(ROOT / "config/cd-inventory.json")


def interface_manifest(prepared):
    """Use real validation without claiming the final platform freeze."""
    value = d02_manifest(prepared).as_dict()
    declared = fragment()
    for group in ("code_files", "schema_files"):
        value["rules"][group] = declared[group]
    value["provenance"]["prepared_by"] = (
        "C/D component interface test; partial inventory; no FP1 or publication"
    )
    return FrozenManifest(json.dumps(value))


def inventory():
    value = fragment()
    return {"components": value["components"],
            "schema_files": [entry["path"] for entry in value["schema_files"]]}
