"""Fail-closed guards for the opt-in real-browser regression job.

The browser suite is normally skipped unless ``ANNOTATER_BROWSER_TESTS=1`` so
local developer runs do not need Playwright and a built frontend. CI sets
``ANNOTATER_BROWSER_REQUIRED=1`` to promise that the suite actually gates the
merge. In that mode the collected browser tests must match the explicit
inventory in ``tests/browser_test_inventory.py`` exactly, and every expected
test must actually run and pass: a disabled suite, a dropped/renamed/deselected
test, a collection-only run, or a skipped/xfailed/failed test all fail rather
than quietly turn the job green.
"""

from __future__ import annotations

import pytest

from tests.browser_contract import (
    format_inventory_error,
    inventory_problems,
    required_mode_enabled,
    targets_browser_module,
)
from tests.browser_test_inventory import BROWSER_TEST_MODULE, EXPECTED_BROWSER_TESTS

_skipped_or_xfailed: list[str] = []
_passed: set[str] = set()
_enforced = False


def pytest_sessionstart(session: pytest.Session) -> None:
    global _enforced
    _enforced = False
    _skipped_or_xfailed.clear()
    _passed.clear()


def pytest_collection_finish(session: pytest.Session) -> None:
    global _enforced
    if not required_mode_enabled():
        return
    browser_items = [
        item
        for item in session.items
        if item.nodeid.startswith(f"{BROWSER_TEST_MODULE}::")
    ]
    if not browser_items and not targets_browser_module(session.config.args):
        return
    problems = inventory_problems(item.nodeid for item in browser_items)
    if problems:
        raise pytest.UsageError(format_inventory_error(problems))
    _enforced = True


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if not required_mode_enabled():
        return
    if not report.nodeid.startswith(f"{BROWSER_TEST_MODULE}::"):
        return
    if report.skipped:
        kind = "xfailed" if hasattr(report, "wasxfail") else "skipped"
        entry = f"{report.nodeid} ({kind})"
        if entry not in _skipped_or_xfailed:
            _skipped_or_xfailed.append(entry)
    if report.when == "call" and report.passed:
        _passed.add(report.nodeid)


def pytest_sessionfinish(
    session: pytest.Session, exitstatus: int | pytest.ExitCode
) -> None:
    if not required_mode_enabled() or not _enforced:
        return
    not_passed = [nodeid for nodeid in EXPECTED_BROWSER_TESTS if nodeid not in _passed]
    if not _skipped_or_xfailed and not not_passed:
        return
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        if _skipped_or_xfailed:
            reporter.write_line(
                "ANNOTATER_BROWSER_REQUIRED=1, but these browser tests "
                "were skipped or xfailed:",
                red=True,
            )
            for entry in _skipped_or_xfailed:
                reporter.write_line(f"  {entry}", red=True)
        if not_passed:
            reporter.write_line(
                "ANNOTATER_BROWSER_REQUIRED=1, but these browser tests "
                "did not run and pass:",
                red=True,
            )
            for nodeid in not_passed:
                reporter.write_line(f"  {nodeid}", red=True)
