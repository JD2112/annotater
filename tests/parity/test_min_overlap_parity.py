"""
min_overlap contract parity (PLAN Task 6A) — SPEC 8.2.

The single normative definition (fixed by Task 6A):

    a matched pair qualifies iff
        overlap_length > 0
        AND overlap_length / query_length >= min_overlap

where ``overlap_length = max(0, min(q_end, a_end) - max(q_start, a_start))``
and ``query_length = q_end - q_start`` — the fraction is relative to the
QUERY interval (never the annotation), there is no reciprocal
requirement, and coverage from multiple annotation rows is never
aggregated. The threshold comparison is inclusive (``>=``).

Each case in ``MIN_OVERLAP_CASES`` carries its expected rows derived
from that definition (never from backend output) and is checked against
BOTH engines independently through the canonical adapter. The direct
engine-vs-engine layer lives in ``test_differential_parity.py``
(min_overlap entries in ``DIFFERENTIAL_CASES``); parameter validation
lives in ``tests/test_min_overlap_validation.py``.
"""

from __future__ import annotations

import pytest

from .cases import MIN_OVERLAP_CASES
from .comparator import check_expected
from .conftest import case_engine_params


@pytest.mark.parametrize("case_engine", case_engine_params(MIN_OVERLAP_CASES))
def test_min_overlap_contract(case_engine):
    case, engine_cls = case_engine
    check_expected(
        engine_cls,
        case.coord_df,
        case.annot_df,
        case.pairs,
        how=case.how,
        label=case.name,
        **case.engine_kwargs,
    )