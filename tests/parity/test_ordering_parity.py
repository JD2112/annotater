"""
Deterministic ordering parity (PLAN Task 3) — SPEC 4.6, 6; engine-contract 7.

Canonical row order is: original query row order, then original
annotation row order within each query; unmatched query rows appear at
their own query position (left mode).

These fixtures place inputs OUT of coordinate order so that a backend
which silently sorts by coordinate (or loses duplicate identity) is
immediately visible. Duplicate-valued rows are included so ordering can
never be inferred from coordinate values alone.
"""

from __future__ import annotations

import pytest

from .cases import ORDERING_CASES
from .comparator import (
    assert_canonical_equal,
    build_expected_result,
    check_expected,
    run_and_canonicalize,
)
from .conftest import case_engine_params
from streamlit_app.core import BedtoolsEngine, PolarsBioEngine


@pytest.mark.parametrize("case_engine", case_engine_params(ORDERING_CASES))
def test_ordering_contract(case_engine):
    case, engine_cls = case_engine
    check_expected(
        engine_cls,
        case.coord_df,
        case.annot_df,
        case.pairs,
        how=case.how,
        label=case.name,
    )


@pytest.mark.parametrize(
    "engine_cls",
    [
        pytest.param(BedtoolsEngine, id="bedtools"),
        pytest.param(PolarsBioEngine, id="polars-bio"),
    ],
)
def test_identical_runs_are_deterministic(engine_cls):
    """Equivalent runs with identical inputs MUST produce equivalent
    canonical tables (SPEC invariant 4.6)."""
    case = next(
        c for c in ORDERING_CASES if c.name == "duplicate_rows_deterministic_order"
    )
    first = run_and_canonicalize(
        engine_cls, case.coord_df, case.annot_df, how=case.how
    )
    second = run_and_canonicalize(
        engine_cls, case.coord_df, case.annot_df, how=case.how
    )
    assert_canonical_equal(second, build_expected_result(case.coord_df, case.annot_df, case.pairs))
    assert_canonical_equal(second, first, label="determinism-rerun")