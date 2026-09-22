"""
Left-join parity (PLAN Task 3) — SPEC 7.2.

The canonical left contract (NOT bedtools ``-loj`` sentinel behavior, and
NOT polars-bio ``overlap_output="left"`` which returns only overlapping
left rows):

- every query row is preserved;
- a query with N matches yields N rows with ``has_overlap=True``;
- an unmatched query yields exactly one row with query metadata intact,
  ``has_overlap=False``, and canonical-missing (``pd.NA``) in every
  ``annot_*`` field;
- an empty annotation table is still a valid left input: all queries
  survive as unmatched rows.

Empty-query cases assert that a genuinely empty result (0 rows, full
canonical schema) is produced — an empty result is valid here, unlike a
swallowed backend failure (see test_error_contract.py).
"""

from __future__ import annotations

import pytest

from .cases import LEFT_CASES
from .comparator import check_expected
from .conftest import case_engine_params


@pytest.mark.parametrize("case_engine", case_engine_params(LEFT_CASES))
def test_left_contract(case_engine):
    case, engine_cls = case_engine
    check_expected(
        engine_cls,
        case.coord_df,
        case.annot_df,
        case.pairs,
        how=case.how,
        label=case.name,
    )