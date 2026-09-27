#!/usr/bin/env python3
"""Refresh actual hashes after reviewing code changes; never change source rules."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def records(paths):
    return [{"path": p, "sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest()}
            for p in sorted(set(paths))]


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    for path in sorted((ROOT / "config").glob("*-inventory.json")):
        if path.name == "build-inventory.json":
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        for group in ("code_files", "schema_files"):
            if group in value:
                for item in value[group]:
                    item["sha256"] = hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest()
        write(path, value)
    cd = json.loads((ROOT / "config/cd-inventory.json").read_text(encoding="utf-8"))
    analysis = json.loads((ROOT / "config/analysis-inventory.json").read_text(encoding="utf-8"))
    dependencies = ["pyproject.toml", "requirements.txt", "requirements-db.txt", "requirements-dev.txt"]
    b_core = [str(p.relative_to(ROOT)) for p in (ROOT / "src/arsia_ingest").glob("*.py")
              if p.name not in {"publication.py", "publication_checks.py"}]
    shared = sorted(set(dependencies + b_core + cd["interface_code_paths"]))
    components = {name: sorted(set(paths + shared)) for name, paths in cd["components"].items()}
    components.update(intake=shared, raw=shared, runner=shared,
                      analysis=sorted(set(analysis["components"]["analysis"] + shared)),
                      publish=sorted(set(shared + ["src/arsia_ingest/publication.py",
                                                   "src/arsia_ingest/publication_checks.py"])),
                      fp1=dependencies + ["sql/e/fp1.sql", "src/arsia_ingest/sql/fp1.sql"])
    components["qa"] = sorted(set(components["qa"] + ["config/qa-team-v1.1.json"]))
    paths = {p for group in components.values() for p in group}
    runtime = {str(p.relative_to(ROOT)) for p in (ROOT / "src").rglob("*")
               if p.suffix in {".py", ".sql", ".json"}}
    missing = runtime - paths
    if missing:
        raise ValueError("Unlisted runtime files: " + ", ".join(sorted(missing)))
    write(ROOT / "config/build-inventory.json", {
        "version": "b-s0-build-v1", "complete_build": True, "final_platform": False,
        "scope": "Complete three-source S0 build and D05-D08 query dependencies. D09, official admission and independent E acceptance are separate.",
        "components": components, "code_files": records(paths),
        "schema_files": cd["schema_files"],
        "upstream": {"a": "c0824da06b6e7b3f73c4ddeab2114d10b7156913",
                     "c": "6987e604bb93809aa94a736085c3e8320452461d",
                     "d": "d57c3f4ff2fb57eb84ebc414ef77911073c0de06",
                     "e": "aec3b4692382e48ea4f778f04a31a4ca5ba5fa57"},
        "remaining": ["D09 reader/UI integration", "Official source admission and replay",
                      "E's independent expectations and platform acceptance"]})


if __name__ == "__main__":
    main()
