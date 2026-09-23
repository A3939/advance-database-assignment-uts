"""Assemble and freeze the team-v1.1 manifest; FP1 is a separate SQL call."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from urllib.parse import urlsplit

from .config import ID, SHA256
from .models import IntakeError
from .raw_load import FILE_FIELDS, VERSION, _PreparedRun
from .vic_restricted import PROTOCOL, QA_TEXT_SHA256, validate_profile


REQUIRED_CHECKS = (
    "QA01_INPUT", "QA02_RAW", "QA03_PROJECTED", "QA04_AUXILIARY",
    "QA05_SEMANTICS", "QA06_RECONCILIATION", "QA07_LOCATION",
)
COMPONENTS = (
    "intake", "raw", "runner", "project", "vault", "canonical", "dw",
    "qa", "publish", "analysis", "fp1",
)
ROOT_FIELDS = {"contract_version", "dataset_kind", "analysis", "sources", "files",
               "rules", "required_checks", "provenance"}
SOURCE_FIELDS = {"source_id", "jurisdiction_code", "source_name", "publisher",
                 "release_label", "release_scope", "resource_ids"}
RULE_FIELDS = {"contracts", "mappings", "severity", "qa_contract", "code_files", "schema_files"}
CONTRACT_SECTIONS = {"input", "identity", "semantics", "snapshot", "confirmation"}
QA_TEXT_HASHES = {
    "e88579759e6da7ef7955b5a31e504dc09b24e24b26f11c00cf752aea576167af",  # Chinese 04, section 3
    "80d22c707bae659a4a4151e75c97c3863e016fe508727f36d4c47c29637e4fbd",  # English equivalent
}


def _fail(message, **details):
    raise IntakeError("MANIFEST_INPUT", message, **details)


def _fields(value, fields):
    if not isinstance(value, dict) or value.keys() != fields:
        _fail("Missing or unexpected fields", expected=sorted(fields))


def _text(value):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        _fail("Expected non-empty text without NUL")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise IntakeError("MANIFEST_INPUT", "Invalid Unicode text") from exc
    return value


def _tree(value):
    if isinstance(value, dict):
        for key, item in value.items():
            _text(key)
            _tree(item)
    elif isinstance(value, list):
        for item in value:
            _tree(item)
    elif isinstance(value, str):
        if "\x00" in value:
            _fail("NUL is not valid PostgreSQL JSONB text")
        try:
            value.encode("utf-8")
        except UnicodeError as exc:
            raise IntakeError("MANIFEST_INPUT", "Invalid Unicode text") from exc
    elif value is not None and type(value) not in {int, bool}:
        _fail("Use integers for counts and decimal strings for fractional values")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("Duplicate JSON key", key=key)
        result[key] = value
    return result


def _number(value):
    _fail("JSON decimals and non-finite numbers must not be used", value=value)


def read_json(path):
    """Reject duplicates before JSON objects can discard them."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"),
                           object_pairs_hook=_pairs, parse_float=_number, parse_constant=_number)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntakeError("MANIFEST_INPUT", "Cannot read UTF-8 JSON", path=str(path)) from exc
    _tree(value)
    return value


def _list(value, key=None, *, empty=False):
    if not isinstance(value, list) or (not value and not empty):
        _fail("Expected a non-empty list")
    ids = []
    for item in value:
        identity = item.get(key) if isinstance(item, dict) and key else item
        _text(identity)
        ids.append(identity)
    if len(ids) != len(set(ids)):
        _fail("Duplicate list identity", field=key)
    return ids


def _version(value):
    if not VERSION.fullmatch(_text(value)):
        _fail("Invalid version token")


def _namespace(value, kind):
    prefix = "syn_" if kind == "synthetic" else "official_"
    if not ID.fullmatch(_text(value)) or not value.startswith(prefix) or value == prefix:
        _fail("ID does not match dataset_kind", value=value)


def _relative(value):
    _text(value)
    path = PurePosixPath(value)
    if (path.is_absolute() or not path.parts or any(p in {".", ".."} for p in value.split("/"))
            or "\\" in value or ":" in value or path.as_posix() != value):
        _fail("Expected a normalized relative POSIX path", path=value)
    return path


def _digest(root, relative):
    _relative(relative)
    root = Path(root).resolve()
    path = root / relative
    if not path.resolve().is_relative_to(root) or any(p.is_symlink() for p in [path, *path.parents] if p != root and p.is_relative_to(root)):
        _fail("Build inputs must stay inside the project without symlinks", path=relative)
    try:
        with path.open("rb") as stream:
            prefix = stream.read(200)
            if prefix.startswith(b"version https://git-lfs.github.com/spec/v1"):
                _fail("Unresolved LFS pointer in build inputs", path=relative)
            stream.seek(0)
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError as exc:
        raise IntakeError("MANIFEST_VERSION_MISSING", "Required build file is unavailable", path=relative) from exc


def _code_path(path, *, schema=False):
    relative = _relative(path)
    excluded = {"docs", "evidence", "artifacts", "tests", "raw_datasource", "Resources",
                ".git", ".venv", "__pycache__", "node_modules"}
    allowed = {".sql"} if schema else {".py", ".sql", ".toml", ".lock", ".json", ".yaml", ".yml", ".sh"}
    dependency = not schema and relative.name in {"requirements.txt", "requirements-dev.txt"}
    if excluded.intersection(relative.parts) or (relative.suffix not in allowed and not dependency) or relative.name.startswith(".env"):
        _fail("Code/schema lists cannot contain raw data, documentation or runtime output", path=path)


def digest_inventory(project_root, inventory):
    """Require the full build inventory and hash actual bytes, not caller digests."""
    _fields(inventory, {"components", "schema_files"})
    if not isinstance(inventory["components"], dict) or not set(COMPONENTS) <= inventory["components"].keys():
        raise IntakeError("MANIFEST_VERSION_MISSING", "Supply code paths for every build component", required=list(COMPONENTS))
    code = set()
    for component, paths in inventory["components"].items():
        _text(component)
        _list(paths)
        code.update(paths)
    schema = _list(inventory["schema_files"])
    if code.intersection(schema):
        _fail("A path cannot be both code and schema")
    result = {}
    for name, paths in (("code_files", code), ("schema_files", schema)):
        result[name] = []
        for path in sorted(paths):
            _code_path(path, schema=name == "schema_files")
            result[name].append({"path": path, "sha256": _digest(project_root, path)})
    return result


def _document(entry, extra=()):
    _fields(entry, {"id", "version", "content", *extra})
    if not ID.fullmatch(_text(entry["id"])):
        _fail("Invalid contract or mapping ID")
    _version(entry["version"])
    if not isinstance(entry["content"], dict) or not entry["content"]:
        _fail("Full versioned content is required", id=entry["id"])


def _qa_contract(entry):
    _document(entry)
    _fields(entry["content"], {"text"})
    body = _text(entry["content"]["text"])
    allowed = {"team-v1.1": QA_TEXT_HASHES, PROTOCOL: {QA_TEXT_SHA256}}
    if (entry["id"] != "team_qa"
            or hashlib.sha256(body.encode("utf-8")).hexdigest() not in allowed.get(entry["version"], set())):
        _fail("Use the complete agreed v1.1 QA text; protocol changes need a reviewed version")


def _url(value):
    parts = urlsplit(_text(value))
    if parts.scheme not in {"https", "http"} or not parts.netloc or parts.username or parts.password:
        _fail("Expected a download URL without credentials")


def _no_runtime(value):
    if isinstance(value, dict):
        for key, item in value.items():
            # Protocols may describe these fields; actual run values do not belong here.
            if key in {"batch_id", "raw_record_id", "run_id"} and isinstance(item, str) and re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", item):
                _fail("Run UUIDs belong outside the fingerprint", field=key)
            if key == "input_fingerprint" and isinstance(item, str) and SHA256.fullmatch(item):
                _fail("A manifest cannot contain its own fingerprint")
            if key in {"prepared_at", "started_at", "finished_at"} and isinstance(item, str):
                try:
                    datetime.fromisoformat(item)
                except ValueError:
                    pass
                else:
                    _fail("Run timestamps belong in provenance", field=key)
            if key == "path" or key.endswith("_path") or key == "run_dir":
                if isinstance(item, str):
                    _relative(item)
            _no_runtime(item)
    elif isinstance(value, list):
        for item in value:
            _no_runtime(item)


def validate_manifest(value):
    """Validate the frozen transport contract without executing business rules."""
    _tree(value)
    _fields(value, ROOT_FIELDS)
    kind = value["dataset_kind"]
    if value["contract_version"] != "team-v1.1" or kind not in ("official", "synthetic"):
        _fail("Expected team-v1.1 and an explicit dataset_kind")
    analysis = value["analysis"]
    _fields(analysis, {"year_from", "year_to"})
    if any(type(v) is not int for v in analysis.values()) or not 1 <= analysis["year_from"] <= analysis["year_to"] <= 9999:
        _fail("Expected an inclusive calendar-year interval")
    sources, files = value["sources"], value["files"]
    source_ids = _list(sources, "source_id")
    file_ids = _list(files, "resource_id")
    for source in sources:
        _fields(source, SOURCE_FIELDS)
        for key in SOURCE_FIELDS - {"resource_ids"}:
            _text(source[key])
        _namespace(source["source_id"], kind)
        ids = _list(source["resource_ids"])
        if set(ids) != {f["resource_id"] for f in files if f.get("source_id") == source["source_id"]}:
            _fail("Every selected source needs its complete resource set")
    for file in files:
        _fields(file, FILE_FIELDS)
        for key in ("source_id", "resource_id"):
            _namespace(file[key], kind)
        if file["source_id"] not in source_ids or file["entity_kind"] not in ("crash", "unit", "person_raw", "node_raw"):
            _fail("Unknown file source or entity kind")
        _text(file["resource_role"])
        for key in ("parser_version", "locator_version"):
            _version(file[key])
        if not SHA256.fullmatch(_text(file["file_sha256"])):
            _fail("Invalid source-file digest")
        if type(file["raw_count"]) is not int or file["raw_count"] < 0 or type(file["header_row"]) is not int or file["header_row"] != 1:
            _fail("Invalid raw_count or header_row")
        _list(file["header"])
        if file["format"] == "csv":
            valid = file["encoding"] == "utf-8" and file["sheet"] is None and file["locator_version"] == "csv-logical-v1"
        elif file["format"] == "xlsx":
            _text(file["sheet"])
            valid = file["encoding"] is None and file["locator_version"] == "xlsx-physical-v1"
        else:
            valid = False
        if not valid:
            _fail("Unsupported native format/locator combination")
    rules = value["rules"]
    _fields(rules, RULE_FIELDS)
    if set(_list(rules["contracts"], "id")) != set(file_ids):
        _fail("Provide one complete contract per selected resource")
    mappings = set(_list(rules["mappings"], "id", empty=True))
    _qa_contract(rules["qa_contract"])
    restricted_ids = {f["resource_id"] for f in files if f["source_id"] == "official_vic"}
    if rules["qa_contract"]["version"] != PROTOCOL:
        restricted_ids = set()
    referenced = set()
    for contract in rules["contracts"]:
        _document(contract, {"status", "mapping_ids"})
        expected_status = "confirmed" if kind == "official" else "synthetic_defined"
        if contract["id"] in restricted_ids:
            expected_status = "restricted"
        if contract["status"] != expected_status:
            raise IntakeError("MANIFEST_UNCONFIRMED", "A build needs confirmed source contracts or explicit synthetic definitions", resource_id=contract["id"])
        content = contract["content"]
        if not CONTRACT_SECTIONS <= content.keys() or any(not isinstance(content[k], dict) or not content[k] for k in CONTRACT_SECTIONS):
            _fail("Source contract is missing a section from document 05", required=sorted(CONTRACT_SECTIONS))
        selected = next(f for f in files if f["resource_id"] == contract["id"])
        if content["input"] != selected:
            _fail("Contract input must match the prepared file", resource_id=contract["id"])
        identity = content["identity"]
        source = next(s for s in sources if s["source_id"] == selected["source_id"])
        for key in ("release_label", "release_scope", "resource_ids"):
            actual, expected = identity.get(key), source[key]
            if key == "resource_ids":
                actual = sorted(_list(actual))
                expected = sorted(expected)
            if actual != expected:
                _fail("Contract release differs from frozen source", resource_id=contract["id"], field=key)
        for key in ("key", "coverage", "bundle_basis", "scope_filter"):
            if key not in identity or identity[key] in (None, "", {}, []):
                _fail("Contract identity/coverage is incomplete", field=key)
        if "parent" not in identity:
            _fail("Contract must state the parent relation, including null when absent")
        snapshot = content["snapshot"]
        _text(snapshot.get("policy"))
        if "change" not in snapshot:
            _fail("State snapshot changes explicitly; null denotes the baseline")
        confirmation = content["confirmation"]
        if confirmation.get("status") != contract["status"]:
            _fail("Contract confirmation status disagrees")
        if kind == "official":
            for key in ("owner", "reviewed_by", "licence", "checked_at"):
                _text(confirmation.get(key))
            _list(confirmation.get("references"))
            try:
                datetime.fromisoformat(confirmation["checked_at"])
            except ValueError as exc:
                raise IntakeError("MANIFEST_INPUT", "Expected an ISO review date") from exc
            if "unresolved" not in confirmation or not isinstance(confirmation["unresolved"], list):
                _fail("Record official unresolved issues and their dispositions")
        referenced.update(_list(contract["mapping_ids"], empty=True))
    if referenced != mappings:
        _fail("Mapping inventory must exactly match contract references")
    for mapping in rules["mappings"]:
        _document(mapping)
    _qa_contract(rules["qa_contract"])
    severity = rules["severity"]
    if not isinstance(severity, list) or not severity:
        _fail("Complete severity definitions are required")
    seen, versions = set(), {}
    for item in severity:
        _fields(item, {"source_id", "severity_code", "severity_label", "definition_version", "definition_text", "is_fatal_crash"})
        for key in item.keys() - {"is_fatal_crash"}:
            _text(item[key])
        _version(item["definition_version"])
        pair = item["source_id"], item["severity_code"]
        if pair in seen or item["source_id"] not in source_ids:
            _fail("Duplicate or unknown source severity definition")
        seen.add(pair)
        previous = versions.setdefault(item["source_id"], item["definition_version"])
        if previous != item["definition_version"] or (item["is_fatal_crash"] is not None and type(item["is_fatal_crash"]) is not bool):
            _fail("Inconsistent severity version or fatal classification")
    if any((sid, "__MISSING__") not in seen for sid in source_ids):
        _fail("Each source needs an explicit missing severity category")
    for contract in rules["contracts"]:
        semantics = contract["content"]["semantics"]
        codes = set(_list(semantics.get("severity_codes")))
        sid = contract["content"]["input"]["source_id"]
        if codes != {code for source, code in seen if source == sid} or semantics.get("severity_definition_version") != versions[sid]:
            _fail("Severity must include every declared category, including unobserved ones", source_id=sid)
    paths = set()
    for group in ("code_files", "schema_files"):
        _list(rules[group], "path")
        for item in rules[group]:
            _fields(item, {"path", "sha256"})
            _code_path(item["path"], schema=group == "schema_files")
            if item["path"] in paths or not SHA256.fullmatch(_text(item["sha256"])):
                _fail("Duplicate code/schema path or invalid hash")
            paths.add(item["path"])
    if value["required_checks"] != list(REQUIRED_CHECKS):
        _fail("All seven required checks must remain in contract order")
    provenance = value["provenance"]
    _fields(provenance, {"prepared_at", "prepared_by", "files"})
    _text(provenance["prepared_by"])
    stamp = _text(provenance["prepared_at"])
    try:
        parsed = datetime.fromisoformat(stamp)
        if "T" not in stamp or parsed.utcoffset() != timedelta(0):
            raise ValueError
    except ValueError as exc:
        raise IntakeError("MANIFEST_INPUT", "prepared_at must be UTC ISO 8601") from exc
    if set(_list(provenance["files"], "resource_id")) != set(file_ids):
        _fail("Provenance must cover every selected resource")
    for item in provenance["files"]:
        _fields(item, {"resource_id", "file_sha256", "archive_relpath", "original_filename", "download_url", "evidence_ref"})
        file = next(f for f in files if f["resource_id"] == item["resource_id"])
        digest = file["file_sha256"]
        if item["file_sha256"] != digest or item["archive_relpath"] != f"{kind}/archive/sha256/{digest[:2]}/{digest}":
            _fail("Provenance hash/archive does not match selected input")
        if PurePosixPath(_text(item["original_filename"])).name != item["original_filename"] or "\\" in item["original_filename"]:
            _fail("Original filename must not contain a directory")
        _text(item["evidence_ref"])
        if item["download_url"] is None and kind == "synthetic":
            continue
        _url(item["download_url"])
    validate_profile(_normalize(value))
    _no_runtime({k: v for k, v in value.items() if k != "provenance"})


def _normalize(value):
    value = deepcopy(value)
    value["sources"].sort(key=lambda s: s["source_id"])
    for source in value["sources"]:
        source["resource_ids"].sort()
    value["files"].sort(key=lambda f: f["resource_id"])
    rules = value["rules"]
    for key in ("contracts", "mappings"):
        rules[key].sort(key=lambda item: item["id"])
    for contract in rules["contracts"]:
        contract["mapping_ids"].sort()
        contract["content"]["identity"]["resource_ids"].sort()
        contract["content"]["semantics"]["severity_codes"].sort()
    for key in ("code_files", "schema_files"):
        rules[key].sort(key=lambda item: item["path"])
    rules["severity"].sort(key=lambda item: (item["source_id"], item["severity_code"]))
    value["provenance"]["files"].sort(key=lambda item: item["resource_id"])
    return value


@dataclass(frozen=True)
class FrozenManifest:
    """Immutable JSON snapshot. Returned dictionaries are disposable copies."""

    _json: str

    def __post_init__(self):
        value = json.loads(self._json, object_pairs_hook=_pairs, parse_float=_number, parse_constant=_number)
        validate_manifest(value)
        object.__setattr__(self, "_json", json.dumps(_normalize(value), ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n")

    def as_dict(self):
        return json.loads(self._json)

    def fingerprint_input(self):
        value = self.as_dict()
        del value["provenance"]
        return value

    def write(self, path):
        """Atomically create a new file; never replace an existing snapshot."""
        path = Path(path)
        kind = self.as_dict()["dataset_kind"]
        if path.parent.name != "manifests" or path.parent.parent.name != kind:
            _fail("Write under <output>/<dataset_kind>/manifests/<name>.json")
        if any(parent.is_symlink() for parent in (path.parent, path.parent.parent)):
            _fail("Manifest output directories must not be symlinks")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(self._json.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return path


def freeze_manifest(value, *, project_root, inventory):
    """Verify real build bytes before freezing; no filesystem output or DB call."""
    validate_manifest(value)
    digests = digest_inventory(project_root, inventory)
    for group, expected in digests.items():
        if sorted(value["rules"][group], key=lambda item: item["path"]) != expected:
            raise IntakeError("MANIFEST_VERSION_CHANGED", "Build inventory differs from manifest", group=group)
    return FrozenManifest(json.dumps(value, ensure_ascii=False, allow_nan=False))


def build_manifest(run_dir, *, sources, contracts, mappings, severity, qa_contract,
                   inventory, project_root, prepared_by, origins, analysis=None):
    """Combine a completed native run with explicit, versioned build definitions."""
    run = _PreparedRun(run_dir)
    run.check_files()
    _fields(origins, {file["resource_id"] for file in run.files})
    provenance = []
    for file in run.files:
        rid = file["resource_id"]
        origin = origins[rid]
        _fields(origin, {"download_url", "evidence_ref"})
        recorded = run.provenance[rid]
        provenance.append({key: recorded[key] for key in ("resource_id", "file_sha256", "archive_relpath", "original_filename")} | origin)
    value = {
        "contract_version": "team-v1.1", "dataset_kind": run.kind,
        "analysis": analysis if analysis is not None else {"year_from": 2020, "year_to": 2024},
        "sources": sources, "files": run.files,
        "rules": {"contracts": contracts, "mappings": mappings, "severity": severity,
                  "qa_contract": qa_contract, **digest_inventory(project_root, inventory)},
        "required_checks": list(REQUIRED_CHECKS),
        "provenance": {"prepared_at": run.run["finished_at"], "prepared_by": prepared_by, "files": provenance},
    }
    return freeze_manifest(value, project_root=project_root, inventory=inventory)


def s0_definitions(contract_path):
    """Wrap generated S0/S8 definitions and variants without inventing mappings."""
    definition = read_json(contract_path)
    if (definition.get("team_contract_version") != "team-v1.1" or definition.get("dataset_kind") != "synthetic"
            or definition.get("definition_status") != "synthetic_defined"):
        _fail("Expected a generated B07 synthetic contract")
    contracts, mappings, severity = [], [], []
    sources = definition["sources"]
    for resource in definition["resources"]:
        rid = resource["resource_id"]
        native = resource["native"]
        file = {key: resource[key] for key in ("source_id", "resource_id", "resource_role", "entity_kind", "raw_count", "parser_version", "locator_version")}
        file.update({key: native[key] for key in ("format", "encoding", "sheet", "header_row", "header")})
        file["file_sha256"] = native["expected_sha256"]
        source = next(s for s in sources if s["source_id"] == resource["source_id"])
        mapping_id = rid + "_mapping"
        common_rules = resource.get("common_rules", definition["common_rules"])
        mappings.append({"id": mapping_id, "version": definition["definition_version"], "content": resource["mapping"]})
        contracts.append({
            "id": rid, "version": resource.get("fixture_version", definition["fixture_version"]),
            "status": "synthetic_defined", "mapping_ids": [mapping_id],
            "content": {
                "input": file,
                "identity": {**{k: source[k] for k in ("release_label", "release_scope", "resource_ids")},
                             "key": resource["key"], "parent": resource["parent"], "coverage": resource.get("coverage", definition["coverage"]),
                             **{k: common_rules[k] for k in ("bundle_basis", "scope_filter")}},
                "semantics": {"common_rules": common_rules, "used_fields": resource["used_fields"],
                              "unused_fields": resource["unused_fields"],
                              "severity_codes": [c["severity_code"] for c in definition["severity"]["categories"]],
                              "severity_definition_version": definition["severity"]["definition_version"]},
                "snapshot": {"policy": common_rules["snapshot_policy"], "change": definition.get("snapshot_change")},
                "confirmation": {"status": definition["definition_status"], "basis": resource.get(
                    "confirmation_basis", "B07 synthetic fixture definition; team-v1.1 section 4")},
            },
        })
    for source_id in definition["severity"]["applies_to"]:
        for item in definition["severity"]["categories"]:
            severity.append({"source_id": source_id, **item,
                             "definition_version": definition["severity"]["definition_version"],
                             "definition_text": definition["severity"]["rule"]})
    return {"sources": sources, "analysis": definition["analysis"], "contracts": contracts, "mappings": mappings, "severity": severity}


def team_qa_contract(path):
    """Read the existing Chinese or English v1.1 QA section in full."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise IntakeError("MANIFEST_VERSION_MISSING", "Team QA contract is unavailable") from exc
    section = re.search(r"^## 3\. (?:QA具体对象与发布门槛|QA objects and publication gate)\n(.*?)^## 4\.", text, re.M | re.S)
    if not section:
        _fail("Expected the complete team-v1.1 QA section; review changed contracts explicitly")
    entry = {"id": "team_qa", "version": "team-v1.1", "content": {"text": section[1].strip()}}
    _qa_contract(entry)
    return entry
