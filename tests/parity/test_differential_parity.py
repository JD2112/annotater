"""
Differential parity (PLAN Task 3) — Bedtools vs Polars-Bio.

Layer 3 of the oracle: for representative fixtures, each engine's
canonicalized result is compared DIRECTLY (strict comparator) against
the other engine's canonicalized result. This guards against both
engines sharing a semantic bug that the explicit fixtures happen not to
pin down (belt-and-braces in addition to layers 1+2).

Since Task 4 both engines emit canonical results on the covered
parity surface, the direct comparison runs for every differential case
(no xfails remain in this module).
"""

from __future__ import annotations

import pytest

from streamlit_app.core import BedtoolsEngine, PolarsBioEngine

from .cases import DIFFERENTIAL_CASES
from .comparator import assert_canonical_equal, run_and_canonicalize


@pytest.mark.parametrize("case", DIFFERENTIAL_CASES, ids=lambda c: c.name)
def test_bedtools_equals_polars_bio_canonical(case):
    # Closest mode (Task 6E, SPEC 8.6) carries the canonical nullable
    # integer ``distance`` extra column; declare it for the
    # canonicalization layer, mirroring ``check_expected``.
    extra_columns = (
        ("distance",) if case.engine_kwargs.get("mode") == "closest" else ()
    )
    bedtools_result = run_and_canonicalize(
        BedtoolsEngine, case.coord_df, case.annot_df,
        how=case.how, extra_columns=extra_columns, **case.engine_kwargs,
    )
    polars_result = run_and_canonicalize(
        PolarsBioEngine, case.coord_df, case.annot_df,
        how=case.how, extra_columns=extra_columns, **case.engine_kwargs,
    )
    # strict: columns+order, row count, row order, NA-aware values, dtypes
    assert_canonical_equal(
        polars_result,
        bedtools_result,
        label=f"differential:{case.name}",
    )