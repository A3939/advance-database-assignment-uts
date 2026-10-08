"""Ordinary pytest cannot invoke real data-processing models.

Real-source model experiments use explicit acceptance CLIs, never pytest. The
database module additionally validates managed ownership before its first write.
"""
import http.client
import pytest


def pytest_addoption(parser):
    parser.addoption('--executor-image', default=None, help='Explicit isolated adapter image for real container tests; never builds or replaces an image')


def pytest_configure(config):
    image=config.getoption('--executor-image')
    if image:
        from arsia_pipeline import isolated_executor
        result=isolated_executor.docker(['image','inspect',image,'--format','{{.Id}}'])
        if result.returncode:raise pytest.UsageError('Explicit executor image is unavailable')
        isolated_executor.IMAGE=result.stdout.strip()


@pytest.fixture(autouse=True)
def forbid_real_data_models(monkeypatch):
    original = http.client.HTTPConnection.request

    def guarded(connection, method, url, *args, **kwargs):
        if url in {'/api/imports/agent-model', '/api/imports/codex-model'}:
            raise AssertionError('Ordinary pytest cannot invoke a real data-processing model')
        return original(connection, method, url, *args, **kwargs)

    monkeypatch.setattr(http.client.HTTPConnection, 'request', guarded)
    from arsia_pipeline.codex_runtime import CodexRuntime

    def forbidden(*args, **kwargs):
        raise AssertionError('Real Codex experiments require the explicit acceptance CLI')

    monkeypatch.setattr(CodexRuntime, 'run', forbidden)


@pytest.fixture(autouse=True)
def forbid_business_database(monkeypatch):
    from arsia_pipeline import store
    original = store.connect

    def guarded(config=None, *args, **kwargs):
        if config is None:
            from arsia_pipeline.config import read_config
            config = read_config()
        if not (config.get('test_session_id') and config.get('storage_policy', {}).get('enabled') is True):
            raise AssertionError('Pytest database access requires a managed test session; business runtimes are forbidden')
        return original(config, *args, **kwargs)

    monkeypatch.setattr(store, 'connect', guarded)
