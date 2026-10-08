from types import SimpleNamespace

import pytest

from arsia_pipeline import codex_sandbox
from arsia_pipeline.codex_runtime import CodexRuntime
from arsia_pipeline.errors import ModelUnavailable


def test_missing_fixed_runtime_is_system_dependency_before_bridge(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_sandbox, 'BINARY', tmp_path / 'absent-codex')
    runtime = object.__new__(CodexRuntime)
    runtime.session = SimpleNamespace()
    with pytest.raises(ModelUnavailable) as failed:
        runtime.prepare()
    assert failed.value.questions == []
    assert failed.value.details['kind'] == 'environment_dependency'
    assert failed.value.details['responsible_party'] == 'system'
    assert 'supplied Codex runtime' in failed.value.details['missing']
    assert list(tmp_path.iterdir()) == []


def test_unsupported_host_cannot_start_unconfined_runtime(monkeypatch):
    monkeypatch.setattr(codex_sandbox.platform, 'system', lambda: 'Linux')
    with pytest.raises(ModelUnavailable) as failed:
        codex_sandbox.check_runtime()
    assert 'macOS arm64 isolation' in failed.value.details['missing']
