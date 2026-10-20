#!/usr/bin/env python3
"""Fail the CI aggregator unless every required validation job succeeded.

GitHub Actions exposes the outcomes of a job's dependencies through the
``needs`` context.  A job with ``if: always()`` still runs when a dependency
fails, is cancelled or is skipped, but it does not fail by itself; this script
turns those outcomes into an explicit pass/fail decision for the stable
``ci-gate`` status check.

The payload is ``toJSON(needs)`` from the workflow, for example::

    {"tests": {"result": "success", "outputs": {}}, ...}

Only the required jobs below are considered.  Extras are ignored so that the
gate never accidentally depends on deployment or publication jobs.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

REQUIRED_JOBS = (
    "lock-consistency",
    "tests",
    "frontend-tests",
    "browser-regression",
    "docker-smoke",
)


def evaluate(needs: Any) -> list[str]:
    """Return one problem string per required job that did not succeed."""

    if not isinstance(needs, dict):
        return ["needs payload is not a JSON object"]

    problems: list[str] = []
    for job in REQUIRED_JOBS:
        entry = needs.get(job)
        if not isinstance(entry, dict):
            problems.append(f"{job}: missing from needs")
            continue
        result = entry.get("result")
        if result != "success":
            problems.append(
                f"{job}: {result if result is not None else 'missing result'}"
            )
    return problems


def main(argv: list[str]) -> int:
    raw = argv[1] if len(argv) > 1 else os.environ.get("NEEDS_JSON", "")
    try:
        needs = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        print(f"ci-gate: FAILED: cannot parse needs payload: {exc}")
        return 1

    problems = evaluate(needs)
    if problems:
        print("ci-gate: FAILED: required jobs did not succeed:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("ci-gate: all required jobs succeeded")
    for job in REQUIRED_JOBS:
        print(f"  - {job}: success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
