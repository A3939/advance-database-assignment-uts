"""Restoration boundary for explicit browser tests; no servers or models."""
from types import SimpleNamespace
import json

import pytest

from tools.browser_acceptance_binding import BrowserBinding


def binding(tmp_path):
    previous = b'{"purpose":"old-test"}\n'
    installed = b'{"purpose":"this-test"}\n'
    path = tmp_path / 'manual-test.json'
    path.write_bytes(installed)
    path.chmod(0o600)
    out = tmp_path / 'evidence'
    out.mkdir()
    result = BrowserBinding(None, {}, out, path, BrowserBinding.sha(previous))
    result.before, result.installed, result.bound = previous, installed, True
    result.server = SimpleNamespace(should_exit=False)
    return result


def test_restores_exact_old_bytes_and_permissions(tmp_path):
    value = binding(tmp_path)
    value.close()
    assert value.path.read_bytes() == value.before
    assert value.path.stat().st_mode & 0o077 == 0
    assert value.server.should_exit
    assert json.loads((value.output/'browser-binding-restored.json').read_text())['previous_bytes_restored']


def test_concurrent_change_is_not_overwritten_and_api_is_stopped(tmp_path):
    value = binding(tmp_path)
    other = b'{"purpose":"another-operator"}\n'
    value.path.write_bytes(other)
    with pytest.raises(AssertionError, match='another operator'):
        value.close()
    assert value.path.read_bytes() == other
    assert value.server.should_exit
    assert not (value.output/'browser-binding-restored.json').exists()


def test_stale_expected_hash_fails_before_starting_api_or_binding(tmp_path):
    value = binding(tmp_path)
    value.bound = False
    with pytest.raises(AssertionError, match='Test configuration changed'):
        value.start()
    assert value.path.read_bytes() == value.installed
    assert not (value.output/'browser-ready.json').exists()
