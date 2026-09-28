"""Exercise Git-to-context binding without needing Git inside the image."""

import hashlib
import importlib.util
from pathlib import Path

import pytest


MODULE = Path(__file__).resolve().parents[1] / "docker/team/provenance.py"
spec = importlib.util.spec_from_file_location("team_provenance", MODULE)
provenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provenance)


CONTEXT_FILES = {
    "pyproject.toml": b"[project]\nname = 'provenance-fixture'\n",
    "tools/verify_b14_postgres.py": b"def verify():\n    return True\n",
    "tests/test_team_cli.py": b"def test_receipt():\n    assert True\n",
    "src/arsia_ingest/__init__.py": b"VERSION = 'original'\n",
    "docker/team/cli.py": b"def info():\n    return {'verified': True}\n",
    "docker/team/acceptance.py": b"def require_isolation():\n    return True\n",
    "docker/team/provenance.py": b"def verify_inputs():\n    return True\n",
    "docker/team/requirements.lock": b"# Empty deterministic fixture lock.\n",
}


def _git_id(kind, payload):
    header = f"{kind} {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def _metadata(files):
    """Construct genuine Git object bytes; omit all file blob payloads."""
    directory = {}
    for path, payload in files.items():
        cursor = directory
        parts = path.split("/")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = payload
    objects = []

    def tree(entries):
        records = []
        for name, value in sorted(entries.items(), key=lambda item: (
                item[0] + ("/" if isinstance(item[1], dict) else "")).encode("utf-8")):
            if isinstance(value, dict):
                mode, oid = "40000", tree(value)
            else:
                mode, oid = "100644", _git_id("blob", value)
            records.append(f"{mode} {name}\0".encode("utf-8") + bytes.fromhex(oid))
        payload = b"".join(records)
        oid = _git_id("tree", payload)
        objects.append((oid, "tree", payload))
        return oid

    tree_id = tree(directory)
    commit = (f"tree {tree_id}\n"
              "author Provenance Test <test@example.invalid> 1 +0000\n"
              "committer Provenance Test <test@example.invalid> 1 +0000\n"
              "\nDeterministic provenance fixture.\n").encode("ascii")
    revision = _git_id("commit", commit)
    return revision, tree_id, [(revision, "commit", commit), *objects]


def _batch(objects):
    return b"".join(f"{oid} {kind} {len(payload)}\n".encode("ascii") + payload + b"\n"
                    for oid, kind, payload in objects)


@pytest.fixture
def committed_context(tmp_path):
    root = tmp_path / "context"
    root.mkdir()
    for relative, payload in CONTEXT_FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    # These tracked files are outside the Docker context, but remain bound by
    # the commit's tree. Their absence must not prevent an exact context build.
    committed = {**CONTEXT_FILES,
                 "docs/team-docker.md": b"Documentation excluded from the image.\n",
                 ".env": b"EXAMPLE_ONLY=excluded\n"}
    revision, tree_id, objects = _metadata(committed)
    proof = tmp_path / "git-objects.batch"
    proof.write_bytes(_batch(objects))
    return root, proof, revision, tree_id, objects


def test_exact_committed_context_has_verified_revision_and_file_hashes(committed_context):
    root, proof, revision, tree_id, _ = committed_context
    before = {p.relative_to(root).as_posix(): p.read_bytes()
              for p in root.rglob("*") if p.is_file()}
    result = provenance.verify(root, proof, revision)
    assert result["revision"] == revision
    assert result["tree"] == tree_id
    records = {row["path"]: row for row in result["files"]}
    assert set(records) == set(CONTEXT_FILES)
    for path, payload in CONTEXT_FILES.items():
        assert records[path]["git_blob_sha1"] == _git_id("blob", payload)
        assert records[path]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert before == {p.relative_to(root).as_posix(): p.read_bytes()
                      for p in root.rglob("*") if p.is_file()}


def test_valid_looking_but_wrong_revision_is_rejected(committed_context):
    root, proof, revision, _, _ = committed_context
    wrong = ("0" if revision[0] != "0" else "1") + revision[1:]
    with pytest.raises(ValueError):
        provenance.verify(root, proof, wrong)


@pytest.mark.parametrize("revision", ("", "working-tree", "a" * 7, "G" * 40, "a" * 41))
def test_revision_must_be_a_full_lowercase_git_sha(committed_context, revision):
    root, proof, _, _, _ = committed_context
    with pytest.raises(ValueError):
        provenance.verify(root, proof, revision)


@pytest.mark.parametrize("path", (
    "tools/verify_b14_postgres.py",
    "docker/team/cli.py",
    "docker/team/acceptance.py",
    "docker/team/provenance.py",
    "tests/test_team_cli.py",
    "src/arsia_ingest/__init__.py",
    "docker/team/requirements.lock",
))
def test_dirty_build_input_cannot_claim_original_revision(committed_context, path):
    root, proof, revision, _, _ = committed_context
    target = root / path
    target.write_bytes(target.read_bytes() + b"# Uncommitted modification.\n")
    with pytest.raises(ValueError):
        provenance.verify(root, proof, revision)


def test_untracked_included_file_is_rejected(committed_context):
    root, proof, revision, _, _ = committed_context
    (root / "tools/untracked.py").write_bytes(b"print('unexpected input')\n")
    with pytest.raises(ValueError):
        provenance.verify(root, proof, revision)


def test_missing_committed_input_is_rejected(committed_context):
    root, proof, revision, _, _ = committed_context
    (root / "tests/test_team_cli.py").unlink()
    with pytest.raises(ValueError):
        provenance.verify(root, proof, revision)


def test_excluded_secret_must_never_reach_actual_context(committed_context):
    root, proof, revision, _, _ = committed_context
    # Docker normally filters this out. The verifier must not silently ignore
    # it if it nevertheless arrives in the directory being built.
    (root / ".env").write_bytes(b"EXAMPLE_ONLY=excluded\n")
    with pytest.raises(ValueError):
        provenance.verify(root, proof, revision)


def test_symlink_cannot_stand_in_for_a_committed_regular_file(committed_context, tmp_path):
    root, proof, revision, _, _ = committed_context
    target = root / "tests/test_team_cli.py"
    outside = tmp_path / "outside-test.py"
    outside.write_bytes(target.read_bytes())
    target.unlink()
    try:
        target.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"The host does not permit creation of a test symlink: {exc}")
    with pytest.raises(ValueError):
        provenance.verify(root, proof, revision)


def test_corrupted_commit_payload_does_not_authenticate(committed_context):
    root, proof, revision, _, _ = committed_context
    original = proof.read_bytes()
    changed = original.replace(b"Deterministic provenance", b"Unauthorized! provenance", 1)
    assert changed != original
    proof.write_bytes(changed)
    with pytest.raises(ValueError):
        provenance.verify(root, proof, revision)


@pytest.mark.parametrize("damage", ("wrong-type", "bad-size", "truncated", "trailing-junk"))
def test_malformed_object_stream_is_rejected(committed_context, damage):
    root, proof, revision, _, _ = committed_context
    original = proof.read_bytes()
    if damage == "wrong-type":
        changed = original.replace(b" commit ", b" blob ", 1)
    elif damage == "bad-size":
        header, rest = original.split(b"\n", 1)
        changed = header.rsplit(b" ", 1)[0] + b" nonsense\n" + rest
    elif damage == "truncated":
        changed = original[:-5]
    else:
        changed = original + b"not a Git object\n"
    proof.write_bytes(changed)
    with pytest.raises(ValueError):
        provenance.verify(root, proof, revision)


def test_missing_descendant_tree_is_rejected(committed_context):
    root, proof, revision, tree_id, objects = committed_context
    missing = next(oid for oid, kind, _ in objects if kind == "tree" and oid != tree_id)
    proof.write_bytes(_batch([obj for obj in objects if obj[0] != missing]))
    with pytest.raises(ValueError):
        provenance.verify(root, proof, revision)


def test_corrupted_descendant_tree_does_not_authenticate(committed_context):
    root, proof, revision, tree_id, objects = committed_context
    altered = []
    changed = False
    for oid, kind, payload in objects:
        if kind == "tree" and oid != tree_id and not changed:
            payload = payload[:-1] + bytes([payload[-1] ^ 1])
            changed = True
        altered.append((oid, kind, payload))
    assert changed
    proof.write_bytes(_batch(altered))
    with pytest.raises(ValueError):
        provenance.verify(root, proof, revision)
