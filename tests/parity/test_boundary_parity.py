"""
Boundary / off-by-one parity (PLAN Task 3).

Compact exhaustive matrix for the half-open boundary semantics,
including zero-based coordinates. These fixtures make an accidental
conversion to 1-based closed semantics immediately visible: in closed
1-based interpretation every "touching" case below would (wrongly)
overlap.
"""

from __future__ import annotations

import pytest

from .cases import BOUNDARY_CASES
from .comparator import check_expected
from .conftest import case_engine_params


@pytest.mark.parametrize("case_engine", case_engine_params(BOUNDARY_CASES))
def test_boundary_contract(case_engine):
    case, engine_cls = case_engine
    check_expected(
        engine_cls,
        case.coord_df,
        case.annot_df,
        case.pairs,
        how="inner",
        label=case.name,
    )