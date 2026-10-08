"""Trusted, versioned experiment settings. Never selected from upload contents."""
import copy
import hashlib
import json
from pathlib import Path

POLICY_FILE = Path(__file__).parent / "profiles/agent-policies.json"


def policy(profile="baseline-v1"):
    source = POLICY_FILE.read_bytes()
    profiles = json.loads(source)["profiles"]
    if profile not in profiles:
        raise ValueError("Unknown import agent policy profile")
    return {"profile": profile, "catalog_sha256": hashlib.sha256(source).hexdigest(), **copy.deepcopy(profiles[profile])}


def session_policy(config, checkpoint=None):
    saved = checkpoint or {}
    if saved.get("agent_policy"):
        result = copy.deepcopy(saved["agent_policy"])
        if result["catalog_sha256"] != policy(result["profile"])["catalog_sha256"]:
            raise ValueError("Agent policy changed since this session started; preserve this session and create a new experiment")
        return result
    # Old sessions retain baseline settings unless an operator explicitly extends
    # their budget. A new default does not silently change historical experiments.
    result = policy("baseline-v1" if saved else config.get("agent_profile", "baseline-v1"))
    overrides = config.get("agent_budget", {})
    if not isinstance(overrides, dict) or set(overrides) - set(result["budget"]):
        raise ValueError("Unknown agent budget setting")
    for key, value in overrides.items():
        if type(value) is not int or value <= 0:
            raise ValueError("Agent budgets must be positive integers")
        result["budget"][key] = value
    return result
