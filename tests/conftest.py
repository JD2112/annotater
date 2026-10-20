"""Fail-closed guards for the opt-in real-browser regression job.

The browser suite is normally skipped unless ``ANNOTATER_BROWSER_TESTS=1`` so
local developer runs do not need Playwright and a built frontend. CI sets
``ANNOTATER_BROWSER_REQUIRED=1`` to promise that the suite actually gates the
merge. In that mode a disabled suite, a collection that produces no browser
tests, or a skipped browser test must all fail rather than quietly turn the
job green.
"""

from __future__ import annotations

import os

import pytest

_BROWSER_MODULE = "tests/test_browser_multi_tab.py"
_REQUIRED = os.environ.get("ANNOTATER_BROWSER_REQUIRED") == "1"
_skipped_browser_tests: list[str] = []


def _targets_browser_module(config: pytest.Config) -> bool:
    return any("test_browser_multi_tab.py" in str(argument) for argument in config.args)


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if not _REQUIRED or not _targets_browser_module(config):
        return
    browser_items = [
        item for item in items if item.nodeid.startswith(f"{_BROWSER_MODULE}::")
    ]
    if not browser_items:
        raise pytest.UsageError(
            "ANNOTATER_BROWSER_REQUIRED=1 but no browser regression tests "
            "were collected; refusing to report a green run."
        )


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if not _REQUIRED:
        return
    if report.skipped and report.nodeid.startswith(f"{_BROWSER_MODULE}::"):
        _skipped_browser_tests.append(report.nodeid)


def pytest_sessionfinish(
    session: pytest.Session, exitstatus: int | pytest.ExitCode
) -> None:
    if not _REQUIRED or not _skipped_browser_tests:
        return
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(
            "ANNOTATER_BROWSER_REQUIRED=1, but these browser tests skipped:",
            red=True,
        )
        for nodeid in _skipped_browser_tests:
            reporter.write_line(f"  {nodeid}", red=True)
