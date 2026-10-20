"""Regression checks for the required real-browser CI gate.

The browser suite is opt-in locally, so the job can only be trustworthy if a
``REQUIRED`` run cannot go green while the suite is disabled. These checks run
without Playwright: the opt-in guard fires before any browser or build setup.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "python-tests.yml"
BROWSER_TEST = "tests/test_browser_multi_tab.py"
GUARD_MESSAGE = "ANNOTATER_BROWSER_REQUIRED=1 requires ANNOTATER_BROWSER_TESTS=1"


def test_workflow_enables_the_required_browser_suite():
    workflow = WORKFLOW.read_text()
    assert 'ANNOTATER_BROWSER_TESTS: "1"' in workflow
    assert 'ANNOTATER_BROWSER_REQUIRED: "1"' in workflow
    assert BROWSER_TEST in workflow


def test_required_mode_fails_when_the_opt_in_flag_is_missing():
    env = os.environ.copy()
    env["ANNOTATER_BROWSER_REQUIRED"] = "1"
    env.pop("ANNOTATER_BROWSER_TESTS", None)
    env.pop("PYTEST_ADDOPTS", None)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            f"{BROWSER_TEST}::test_upload_409_conflict_drops_the_stale_side_and_disables_run",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert GUARD_MESSAGE in output, output
