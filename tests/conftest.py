"""Stable suite categories; explicit test-level markers can add detail."""
import pytest


def pytest_collection_modifyitems(items):
    for item in items:
        name = item.path.name
        if 'browser' in name:
            category = 'browser'
        elif 'postgres' in name:
            category = 'postgres'
        elif 'docker' in name or 'prepare_build' in name:
            category = 'docker'
        else:
            category = 'unit'
        item.add_marker(getattr(pytest.mark, category))
        if 'official' in name:
            item.add_marker(pytest.mark.official)
        if category in {'postgres', 'browser'}:
            item.add_marker(pytest.mark.slow)
