"""Read saved JUnit reports without executing tests in the web process."""
from __future__ import annotations

from collections import Counter
from html import escape
import math
import os
from pathlib import Path
from urllib.parse import parse_qs
from xml.etree import ElementTree as ET

STATUSES = ("passed", "failed", "error", "skipped")
MAX_REPORT_BYTES = 10 * 1024 * 1024


def read_report(path: Path):
    with path.open("rb") as stream:
        data = stream.read(MAX_REPORT_BYTES + 1)
    if len(data) > MAX_REPORT_BYTES:
        raise ValueError("Report exceeds the 10 MiB limit.")
    # JUnit needs no DTDs or entity declarations. Reject them before parsing.
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper() or b"\x00" in data:
        raise ValueError("Unsupported XML declarations or encoding.")
    root = ET.fromstring(data)
    if root.tag not in {"testsuite", "testsuites"}:
        raise ValueError("Expected a JUnit testsuite or testsuites report.")
    cases = []
    for case in root.iter("testcase"):
        result = next((case.find(tag) for tag in ("error", "failure", "skipped")
                       if case.find(tag) is not None), None)
        status = {"failure": "failed", "error": "error", "skipped": "skipped"}.get(
            result.tag if result is not None else "", "passed")
        duration = float(case.get("time", "0"))
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("Invalid test duration.")
        detail = "" if result is None else "\n".join(
            part for part in (result.get("message", ""), result.text or "") if part)
        cases.append((case.get("classname", ""), case.get("name", "Unnamed test"),
                      status, duration, detail))
    timestamps = [suite.get("timestamp") for suite in root.iter("testsuite")
                  if suite.get("timestamp")]
    return cases, ", ".join(timestamps) or "Not recorded"


def render_test_results(query: str, css: str) -> tuple[str, int]:
    values = parse_qs(query, keep_blank_values=True)
    selected = values.get("status", ["all"])[0]
    status_code = 200
    content = ""
    if set(values) - {"status"} or len(values.get("status", [])) > 1 or selected not in ("all", *STATUSES):
        content = '<p class="state error">Invalid result filter.</p>'
        status_code = 400
    else:
        path = Path(os.environ.get("ARSIA_TEST_REPORT", "artifacts/test-results/latest.xml"))
        try:
            cases, timestamp = read_report(path)
        except FileNotFoundError:
            content = '<p class="state">No saved test report yet. Generate a pytest JUnit report using the README instructions, then refresh this page.</p>'
        except (OSError, ValueError, ET.ParseError):
            content = '<p class="state error">Test report is unreadable or invalid. Generate a new JUnit report and refresh.</p>'
            status_code = 503
        else:
            counts = Counter(case[2] for case in cases)
            total = len(cases)
            content = f'<p>Suite timestamps: {escape(timestamp)}</p><p>{total} test cases in this report. Counts describe this saved run only.</p>'
            content += '<section class="metrics">' + ''.join(
                f'<article class="result-{status}"><span>{status.title()}</span><strong>{counts[status]}</strong></article>'
                for status in STATUSES) + '</section>'
            if total:
                content += '<div class="result-bar" aria-label="Test outcome proportions">' + ''.join(
                    f'<span class="result-{status}" style="flex:{counts[status]}" title="{status}: {counts[status]}"></span>'
                    for status in STATUSES if counts[status]) + '</div>'
            content += '<nav class="result-filters" aria-label="Filter test results">' + ' '.join(
                f'<a href="/tests?status={status}"' + (' aria-current="page"' if selected == status else '') + f'>{status.title()}</a>'
                for status in ("all", *STATUSES)) + '</nav>'
            visible = [case for case in cases if selected == 'all' or case[2] == selected]
            if not visible:
                content += '<p>No test cases for this filter.</p>'
            else:
                content += '<div class="table-wrap"><table class="test-results"><thead><tr><th>Test case</th><th>Status</th><th>Seconds</th><th>Details</th></tr></thead><tbody>'
                for group, name, status, duration, detail in visible:
                    details = '<details><summary>Show details</summary><pre>' + escape(detail) + '</pre></details>' if detail else '—'
                    content += f'<tr><td>{escape(group)}<br><strong>{escape(name)}</strong></td><td class="result-{status}">{status.title()}</td><td>{duration:.3f}</td><td>{details}</td></tr>'
                content += '</tbody></table></div>'
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>ARSIA test results</title><style>{css}</style></head><body>'
            '<header class="hero"><div><h1>Test results</h1><p>Saved pytest results; opening this page does not run tests.</p></div></header>'
            '<main><nav aria-label="Dashboard navigation"><a href="/">Road safety dashboard</a></nav>'
            '<p>A partial run or skipped tests do not establish full project acceptance. '
            'The saved report may predate the running application.</p>' + content + '</main></body></html>', status_code)
