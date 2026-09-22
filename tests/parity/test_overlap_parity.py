"""
Inner-overlap parity (PLAN Task 3) — layer 1+2 of the oracle.

Every case compares each engine's canonicalized result strictly against
explicit expected rows derived from the half-open overlap predicate
``max(starts) < min(ends)`` (SPEC 5/7.1; engine-contract section 4).

Covers: exact/partial/full-containment overlaps, non-overlap (chromosome,
gap, touching boundaries), one-base intervals, one-to-many / many-to-many,
and duplicate input rows (multiplicity preserved).
"""

from __future__ import annotations

import pytest

from .cases import OVERLAP_CASES
from .comparator import check_expected
from .conftest import case_engine_params


@pytest.mark.parametrize("case_engine", case_engine_params(OVERLAP_CASES))
def test_overlap_contract(case_engine):
    case, engine_cls = case_engine
    check_expected(
        engine_cls,
        case.coord_df,
        case.annot_df,
        case.pairs,
        how="inner",
        label=case.name,
    )