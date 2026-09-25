"""Load and validate the native input catalogue."""
import json
import re
from pathlib import Path

from .models import IntakeConfig, IntakeError, ResourceSpec

ROOT_KEYS = {"config_version", "dataset_kind", "resources"}
RESOURCE_KEYS = {
    "source_id", "resource_id", "resource_role", "entity_kind", "path", "format",
    "header", "encoding", "sheet", "header_row", "expected_sha256",
}
REQUIRED_RESOURCE_KEYS = RESOURCE_KEYS - {"expected_sha256"}
ID = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        try:
            key.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise IntakeError("CONFIG_TYPE", "JSON keys must contain valid Unicode text") from exc
        if key in result:
            raise IntakeError("CONFIG_DUPLICATE_KEY", "Duplicate JSON object key", key=key)
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise IntakeError("CONFIG_NONFINITE", "Non-finite JSON numbers are not permitted", value=value)


def _keys(value: object, allowed: set[str], required: set[str], where: str) -> dict:
    if not isinstance(value, dict):
        raise IntakeError("CONFIG_TYPE", "Expected an object", location=where)
    missing, unknown = required - value.keys(), value.keys() - allowed
    if missing or unknown:
        raise IntakeError("CONFIG_FIELDS", "Unexpected or missing configuration fields",
                          location=where, missing=sorted(missing), unknown=sorted(unknown))
    return value


def _text(value: object, field: str, where: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise IntakeError("CONFIG_TYPE", "Expected non-empty text without NUL", location=where, field=field)
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise IntakeError("CONFIG_TYPE", "Expected text that can be encoded as UTF-8", location=where, field=field) from exc
    return value


def load_config(path: str | Path) -> IntakeConfig:
    """Read a UTF-8 JSON catalogue, resolving input paths relative to it."""
    path = Path(path).resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object,
                          parse_constant=_nonfinite)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntakeError("CONFIG_READ", "Cannot read valid UTF-8 JSON configuration",
                          path=str(path), reason=str(exc)) from exc
    data = _keys(data, ROOT_KEYS, ROOT_KEYS, "root")
    if data["config_version"] != "intake-v1":
        raise IntakeError("CONFIG_VERSION", "Only intake-v1 is supported")
    kind = data["dataset_kind"]
    if not isinstance(kind, str) or kind not in {"official", "synthetic"}:
        raise IntakeError("CONFIG_DATASET_KIND", "dataset_kind must be official or synthetic")
    entries = data["resources"]
    if not isinstance(entries, list) or not entries:
        raise IntakeError("CONFIG_RESOURCES", "At least one resource is required")
    resources: list[ResourceSpec] = []
    ids: set[str] = set()
    prefix = "official_" if kind == "official" else "syn_"
    for number, entry in enumerate(entries):
        where = f"resources[{number}]"
        entry = _keys(entry, RESOURCE_KEYS, REQUIRED_RESOURCE_KEYS, where)
        for key in ("source_id", "resource_id", "resource_role", "entity_kind", "path", "format"):
            _text(entry[key], key, where)
        for key in ("source_id", "resource_id"):
            value = entry[key]
            if not ID.fullmatch(value) or not value.startswith(prefix) or value == prefix:
                raise IntakeError("CONFIG_NAMESPACE", f"{key} must use the {prefix} namespace",
                                  location=where, field=key, value=value)
        rid = entry["resource_id"]
        if rid.casefold() in ids:
            raise IntakeError("CONFIG_DUPLICATE_RESOURCE", "Resource IDs must also be unique on case-insensitive filesystems", resource_id=rid)
        ids.add(rid.casefold())
        if entry["entity_kind"] not in {"crash", "unit", "person_raw", "node_raw"}:
            raise IntakeError("CONFIG_ENTITY_KIND", "Unsupported phase-one entity kind", resource_id=rid)
        fmt = entry["format"]
        if fmt not in {"csv", "xlsx"}:
            raise IntakeError("CONFIG_FORMAT", "Only csv and xlsx are supported", resource_id=rid)
        if type(entry["header_row"]) is not int or entry["header_row"] != 1:
            raise IntakeError("CONFIG_HEADER_ROW", "The native contract requires header_row=1", resource_id=rid)
        header = entry["header"]
        if not isinstance(header, list) or not header:
            raise IntakeError("CONFIG_HEADER", "Expected a non-empty ordered header list", resource_id=rid)
        for name in header:
            _text(name, "header", where)
        if len(header) != len(set(header)):
            raise IntakeError("CONFIG_HEADER", "Duplicate expected header names", resource_id=rid)
        if fmt == "csv":
            if entry["encoding"] != "utf-8" or entry["sheet"] is not None:
                raise IntakeError("CONFIG_CSV", "CSV requires encoding=utf-8 and sheet=null", resource_id=rid)
        elif entry["encoding"] is not None or not isinstance(entry["sheet"], str) or not entry["sheet"].strip():
            raise IntakeError("CONFIG_XLSX", "XLSX requires encoding=null and a named sheet", resource_id=rid)
        if fmt == "xlsx":
            _text(entry["sheet"], "sheet", where)
        expected = entry.get("expected_sha256")
        if expected is not None and (not isinstance(expected, str) or not SHA256.fullmatch(expected)):
            raise IntakeError("CONFIG_HASH", "expected_sha256 must be 64 lowercase hex characters or null", resource_id=rid)
        source_path = Path(entry["path"]).expanduser()
        if not source_path.is_absolute():
            source_path = path.parent / source_path
        resources.append(ResourceSpec(**{**entry, "path": source_path.resolve(), "header": tuple(header)}))
    return IntakeConfig(kind, tuple(resources), path)
