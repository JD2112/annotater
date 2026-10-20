"""Shared fail-closed contract for the required real-browser regression run.

Kept separate from ``conftest.py`` so the workflow/inventory contract tests can
exercise the exact same inventory without importing pytest's conftest module.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import PurePosixPath

from tests.browser_test_inventory import (
    BROWSER_OPT_IN_ENV,
    BROWSER_REQUIRED_ENV,
    BROWSER_TEST_MODULE,
    EXPECTED_BROWSER_TESTS,
)

INVENTORY_ERROR_PREFIX = "ANNOTATER_BROWSER_REQUIRED=1 browser test inventory mismatch"


def required_mode_enabled() -> bool:
    return os.environ.get(BROWSER_REQUIRED_ENV) == "1"


def opt_in_enabled() -> bool:
    return os.environ.get(BROWSER_OPT_IN_ENV) == "1"


def targets_browser_module(arguments: Iterable[object]) -> bool:
    module = BROWSER_TEST_MODULE
    for argument in arguments:
        value = PurePosixPath(str(argument).replace("\\", "/")).as_posix()
        if value == module or value.startswith(f"{module}::"):
            return True
    return False


def inventory_problems(selected_nodeids: Iterable[str]) -> list[str]:
    """Compare the selected browser items with the explicit expected inventory."""
    selected = {
        nodeid
        for nodeid in selected_nodeids
        if nodeid.startswith(f"{BROWSER_TEST_MODULE}::")
    }
    expected = set(EXPECTED_BROWSER_TESTS)
    problems: list[str] = []
    missing = [nodeid for nodeid in EXPECTED_BROWSER_TESTS if nodeid not in selected]
    unexpected = sorted(selected - expected)
    if missing:
        problems.append(
            "missing expected browser test(s) (renamed, deleted or deselected):\n"
            + "\n".join(f"  - {nodeid}" for nodeid in missing)
        )
    if unexpected:
        problems.append(
            "unexpected browser test(s) not in the explicit inventory "
            "(add legitimate tests to tests/browser_test_inventory.py):\n"
            + "\n".join(f"  + {nodeid}" for nodeid in unexpected)
        )
    return problems


def format_inventory_error(problems: list[str]) -> str:
    return INVENTORY_ERROR_PREFIX + ":\n" + "\n".join(problems)
