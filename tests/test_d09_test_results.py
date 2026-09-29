"""Saved test reports must remain truthful and safely rendered."""
import pytest

from arsia_d09.test_results import read_report, render_test_results


@pytest.fixture
def report(tmp_path, monkeypatch):
    path = tmp_path / 'latest.xml'
    monkeypatch.setenv('ARSIA_TEST_REPORT', str(path))
    path.write_text('''<testsuites><testsuite timestamp="2026-09-29T12:00:00">
      <testcase classname="suite" name="passes" time="0.25"/>
      <testcase name="fails"><failure message="&lt;script&gt;">assert 1 == 2</failure></testcase>
      <testcase name="errors"><error message="setup failed"/></testcase>
      <testcase name="skips"><skipped message="missing database"/></testcase>
    </testsuite></testsuites>''')
    return path


def test_outcomes_details_and_filter(report):
    cases, timestamp = read_report(report)
    assert [case[2] for case in cases] == ['passed', 'failed', 'error', 'skipped']
    assert timestamp == '2026-09-29T12:00:00'
    page, status = render_test_results('status=failed', '')
    assert status == 200
    assert '4 test cases' in page
    assert 'assert 1 == 2' in page
    assert '&lt;script&gt;' in page and '<script>' not in page
    assert '<strong>passes</strong>' not in page
    assert 'saved report may predate' in page


@pytest.mark.parametrize('query', ['status=unknown', 'status=failed&status=passed', 'path=/etc/passwd'])
def test_invalid_filters(report, query):
    assert render_test_results(query, '')[1] == 400


def test_missing_report_is_not_a_pass(report):
    report.unlink()
    page, status = render_test_results('', '')
    assert status == 200 and 'No saved test report' in page
    assert 'result-bar' not in page


@pytest.mark.parametrize('xml', ['<broken', '<other/>', '<!DOCTYPE testsuite><testsuite/>',
    '<testsuite><testcase time="nan"/></testsuite>',
    '<testsuite><testcase time="-1"/></testsuite>'])
def test_bad_report_is_unavailable(report, xml):
    report.write_text(xml)
    page, status = render_test_results('', '')
    assert status == 503 and 'unreadable or invalid' in page


def test_empty_report(report):
    report.write_text('<testsuite/>')
    page, status = render_test_results('', '')
    assert status == 200 and '0 test cases' in page
    assert 'No test cases' in page


def test_size_limit(report):
    report.write_bytes(b'x' * (10 * 1024 * 1024 + 1))
    assert render_test_results('', '')[1] == 503


def test_results_http_without_database(report):
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from urllib.request import urlopen
    from arsia_d09.web import make_handler

    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(None, False))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f'http://127.0.0.1:{server.server_port}/tests?status=error', timeout=5) as response:
            assert response.status == 200
            assert response.headers['Cache-Control'] == 'no-store'
            page = response.read().decode()
            assert 'setup failed' in page
            assert '<strong>passes</strong>' not in page
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
