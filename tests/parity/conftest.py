"""
Shared parametrization for the parity harness (PLAN Task 3).

``case_engine_params`` expands a list of :class:`ParityCase` into one
pytest parameter per (case, engine) pair. The xfail status is read from
the case itself, so each deviation is marked exactly where it lives with
its precise root-cause reason (see fixtures.py for the reason registry).

All xfails are ``strict=True``: if a marked case unexpectedly passes
(the deviation was fixed, or the marker is stale), CI fails with XPASS
until the marker is reviewed and removed.
"""

from __future__ import annotations

import pytest

from streamlit_app.core import BedtoolsEngine, PolarsBioEngine


def case_engine_params(cases: list) -> list:
    params = []
    for case in cases:
        bt_marks = (
            [pytest.mark.xfail(strict=True, reason=case.bedtools_xfail)]
            if case.bedtools_xfail
            else []
        )
        pb_marks = (
            [pytest.mark.xfail(strict=True, reason=case.polars_xfail)]
            if case.polars_xfail
            else []
        )
        params.append(
            pytest.param(
                (case, BedtoolsEngine),
                id=f"{case.name}[bedtools]",
                marks=bt_marks,
            )
        )
        params.append(
            pytest.param(
                (case, PolarsBioEngine),
                id=f"{case.name}[polars-bio]",
                marks=pb_marks,
            )
        )
    return params