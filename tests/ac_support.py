"""Real B interfaces for the partial NSW integration."""

import importlib
import json

from arsia_ingest.manifest import FrozenManifest, read_json
from arsia_ingest.runner import ModuleBinding
from d02_support import ROOT, interface_manifest as d02_manifest


def fragment():
    return read_json(ROOT / "config/ac-inventory.json")


def interface_manifest(prepared):
    """Validate a real object without claiming a full platform freeze."""
    value = d02_manifest(prepared).as_dict()
    declared = fragment()
    for group in ("code_files", "schema_files"):
        value["rules"][group] = declared[group]
    value["provenance"]["prepared_by"] = (
        "NSW interface test; partial inventory; no FP1 or publication"
    )
    return FrozenManifest(json.dumps(value))


def inventory():
    value = fragment()
    return {
        "components": value["components"],
        "schema_files": [entry["path"] for entry in value["schema_files"]],
    }


def bindings():
    result = {}
    for stage, declared in fragment()["bindings"].items():
        module, name = declared["callback"].split(":")
        callback = getattr(importlib.import_module(module), name)
        result[stage] = ModuleBinding(
            callback, declared["code_path"], declared["version"]
        )
    return result
