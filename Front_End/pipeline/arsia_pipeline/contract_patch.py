"""Bounded JSON Pointer edits of a proposed contract, before normal validation."""
import json
import re

from .registry import digest_json

ROOTS = {"source", "update", "resources", "retained_resources", "lookup_tables", "relations", "evidence", "definitions", "contract_version"}
PROTECTED = {"documents", "confirmed", "native_context", "native_transition", "admission", "policy_version",
             "trusted_implementation", "permissions", "executor_limits", "agent_budget"}


def patch_contract(contract, expected_contract_sha256, patches, reason):
    current = digest_json(contract)
    if not contract:
        raise ValueError("Set an initial source contract before patching it")
    if expected_contract_sha256 != current:
        raise ValueError("Contract changed or expected hash is incorrect; current_contract_sha256=" + current)
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
        raise ValueError("A nonempty patch reason of at most 1000 characters is required")
    if not isinstance(patches, list) or not 1 <= len(patches) <= 8:
        raise ValueError("Provide 1–8 explicit contract patch operations")
    encoded = json.dumps({"expected_contract_sha256": expected_contract_sha256, "patches": patches, "reason": reason}, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode()) > 16384:
        raise ValueError("Contract patch exceeds 16 KiB; use smaller explicit changes")
    candidate = json.loads(json.dumps(contract, allow_nan=False))
    for number, patch in enumerate(json.loads(encoded)["patches"]):
        if not isinstance(patch, dict) or set(patch) - {"op", "path", "value"}:
            raise ValueError(f"Patch {number}: only op, path and value are supported")
        op, path = patch.get("op"), patch.get("path")
        if op not in {"add", "replace", "remove"} or not isinstance(path, str) or not path.startswith("/") or len(path) > 1024:
            raise ValueError(f"Patch {number}: use add/replace/remove with a non-root JSON Pointer")
        if re.search(r"~(?![01])", path):
            raise ValueError(f"Patch {number}: invalid JSON Pointer escape")
        tokens = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
        if tokens[0] not in ROOTS or any(token in PROTECTED for token in tokens):
            raise ValueError(f"Patch {number}: host authority and non-contract roots cannot be patched")
        if op != "remove" and "value" not in patch:
            raise ValueError(f"Patch {number}: {op} needs an explicit value")
        if op == "remove" and "value" in patch:
            raise ValueError(f"Patch {number}: remove must not contain value")
        parent = candidate
        try:
            for token in tokens[:-1]:
                if isinstance(parent, dict):
                    parent = parent[token]
                elif isinstance(parent, list) and re.fullmatch(r"0|[1-9][0-9]*", token):
                    parent = parent[int(token)]
                else:
                    raise KeyError(token)
            key = tokens[-1]
            if isinstance(parent, dict):
                if op != "add" and key not in parent:
                    raise KeyError(key)
                if op == "remove": del parent[key]
                else: parent[key] = patch["value"]
            elif isinstance(parent, list):
                if key == "-" and op == "add": index = len(parent)
                elif re.fullmatch(r"0|[1-9][0-9]*", key): index = int(key)
                else: raise KeyError(key)
                if index >= len(parent) + (op == "add"):
                    raise IndexError(index)
                if op == "add": parent.insert(index, patch["value"])
                elif op == "remove": parent.pop(index)
                else: parent[index] = patch["value"]
            else:
                raise KeyError(key)
        except (KeyError, IndexError, TypeError):
            raise ValueError(f"Patch {number}: path does not address an existing parent/value: {path}; current_contract_sha256={current}") from None
    return candidate
