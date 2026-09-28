"""Check source binding with saved replay identities, not simulated database passes."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("e_summary", ROOT / "tools/summarize_e_acceptance.py")
summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summary)
RECORDED = json.loads((ROOT / "docs/role-e-acceptance/results.json").read_text(encoding="utf-8"))["runs"]


def identities(mode):
    run = RECORDED[mode]
    return deepcopy({"versions": run["tested_versions"], "verifier_sha256": run["verifier_sha256"],
                     "acceptance_files": run["acceptance_files"]})


class CurrentSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name)
        paths = {"tools/verify_e_acceptance.py", "config/e-acceptance-versions.json"}
        paths.update(item["path"] for run in RECORDED.values() for item in run["acceptance_files"])
        for relative in paths:
            target = self.source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)

    def reject(self, receipt, mode, message):
        with self.assertRaisesRegex(ValueError, message):
            summary.current_source(receipt, mode, self.source)

    def test_recorded_source_identities_match_current_checkout(self):
        for mode in ("synthetic", "official"):
            with self.subTest(mode=mode):
                result = summary.current_source(identities(mode), mode, self.source)
                self.assertEqual("matched", result["status"])
                self.assertEqual(RECORDED[mode]["acceptance_files"], result["files"])

    def test_changed_oracle_test_driver_and_config_are_rejected(self):
        targets = {
            "acceptance/e/expected.py": "synthetic",
            "acceptance/e/test_e07_postgres.py": "synthetic",
            "acceptance/e/test_e08_postgres.py": "synthetic",
            "acceptance/e/test_expectations.py": "synthetic",
            "acceptance/e/run_database.py": "synthetic",
            "config/e-acceptance-s0-v1.json": "synthetic",
            "acceptance/e/official_expected.py": "official",
            "acceptance/e/test_e09_official_postgres.py": "official",
        }
        for relative, mode in targets.items():
            with self.subTest(path=relative):
                path = self.source / relative
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                self.reject(identities(mode), mode, "Current acceptance file differs")
                path.write_bytes(original)

    def test_changed_verifier_is_rejected_without_running_it(self):
        path = self.source / "tools/verify_e_acceptance.py"
        path.write_text(path.read_text(encoding="utf-8") + "\nraise RuntimeError('must not execute')\n", encoding="utf-8")
        for mode in ("synthetic", "official"):
            self.reject(identities(mode), mode, "Current replay verifier differs")

    def test_changed_version_pin_and_metadata_are_rejected(self):
        path = self.source / "config/e-acceptance-versions.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        for key, value in (("runtime_commit", "0" * 40), ("contract_sha256", "0" * 64),
                           ("execution_owner", "A different person"),
                           ("independent_member_signoff", 0), ("final_platform_accepted", 0)):
            with self.subTest(key=key):
                changed = {**original, key: value}
                path.write_text(json.dumps(changed), encoding="utf-8")
                for mode in ("synthetic", "official"):
                    self.reject(identities(mode), mode, "Current version configuration differs")

    def test_version_json_formatting_does_not_change_its_identity(self):
        path = self.source / "config/e-acceptance-versions.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        for mode in ("synthetic", "official"):
            self.assertEqual("matched", summary.current_source(identities(mode), mode, self.source)["status"])

    def test_missing_extra_and_duplicate_records_are_rejected(self):
        for mode in ("synthetic", "official"):
            for fault in ("missing", "extra", "duplicate"):
                with self.subTest(mode=mode, fault=fault):
                    receipt = identities(mode)
                    rows = receipt["acceptance_files"]
                    if fault == "missing":
                        rows.pop()
                    elif fault == "extra":
                        rows.append({"path": "extra.py", "runtime_path": "tests/extra.py", "sha256": "0" * 64})
                    else:
                        rows[-1] = deepcopy(rows[0])
                    self.reject(receipt, mode, "wrong length|Duplicate")

    def test_missing_listed_source_file_is_rejected(self):
        for mode, relative in (("synthetic", "acceptance/e/expected.py"),
                               ("official", "acceptance/e/official_expected.py")):
            with self.subTest(mode=mode):
                (self.source / relative).unlink()
                self.reject(identities(mode), mode, "Missing current source file")

    def test_unknown_source_and_wrong_runtime_mapping_are_rejected(self):
        for mode in ("synthetic", "official"):
            for field, value in (("path", "acceptance/e/unknown.py"),
                                  ("runtime_path", "tests/other.py"),
                                  ("runtime_path", "../outside.py")):
                with self.subTest(mode=mode, field=field, value=value):
                    receipt = identities(mode)
                    receipt["acceptance_files"][0][field] = value
                    self.reject(receipt, mode, "Unexpected acceptance-file path or runtime mapping")

    def test_recorded_hash_cannot_be_missing_or_replaced(self):
        for mode in ("synthetic", "official"):
            for value in (None, "not-a-hash", "0" * 64):
                with self.subTest(mode=mode, hash=value):
                    receipt = identities(mode)
                    receipt["acceptance_files"][0]["sha256"] = value
                    self.reject(receipt, mode, "Invalid acceptance-file hash|Current acceptance file differs")


if __name__ == "__main__":
    unittest.main()
