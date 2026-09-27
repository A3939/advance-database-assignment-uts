"""Prepare the existing seven official files without changing their identities."""
from pathlib import Path
from uuid import uuid4
import json

from .manifest import read_json
from .models import IntakeError
from .official_definitions import official_definitions
from .pipeline import prepare


def prepare_official_inputs(native_root, archive_root, project_root):
    """Archive pinned native files and retain a separate catalogue for this run."""
    root = Path(project_root).resolve()
    native = Path(native_root).resolve()
    output = Path(archive_root).resolve()
    definitions = official_definitions(root)
    expected = {row["id"]: row["content"]["input"] for row in definitions["contracts"]}
    catalogue = read_json(root / "config/native-inputs.json")
    entries = catalogue["resources"]
    ids = [row["resource_id"] for row in entries]
    if (catalogue["dataset_kind"] != "official" or len(ids) != len(set(ids))
            or set(ids) != set(expected)):
        raise IntakeError("OFFICIAL_INPUT", "The catalogue must contain the seven pinned resources")
    for entry in entries:
        frozen = expected[entry["resource_id"]]
        keys = set(entry) - {"path", "expected_sha256"}
        if (any(entry[key] != frozen[key] for key in keys)
                or entry["expected_sha256"] != frozen["file_sha256"]):
            raise IntakeError("OFFICIAL_INPUT", "Catalogue and source contract differ",
                              resource_id=entry["resource_id"])
        entry["path"] = str(native / Path(entry["path"]).name)
    directory = output / "catalogues"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (str(uuid4()) + ".json")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(catalogue, stream, indent=2)
        stream.write("\n")
    result = prepare(path, output)
    if result["status"] != "prepared":
        raise IntakeError("OFFICIAL_INPUT", "Native preparation failed; inspect the retained run",
                          run_dir=result["run_dir"], errors=result["errors"])
    return result
