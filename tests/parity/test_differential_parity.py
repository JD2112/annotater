"""
Differential parity (PLAN Task 3) — Bedtools vs Polars-Bio.

Layer 3 of the oracle: for representative fixtures, each engine's
canonicalized result is compared DIRECTLY (strict comparator) against
the other engine's canonicalized result. This guards against both
engines sharing a semantic bug that the explicit fixtures happen not to
pin down (belt-and-braces in addition to layers 1+2).

All differential cases are currently xfail(strict=True): the
comparison is blocked because PolarsBioEngine output is not canonical —
``canonicalize_annotation_result`` raises ``CanonicalSchemaError`` on it
(SPEC 6; engine-contract section 3). The reason points to the Task 4
result-adapter work. Until the marker is removed, a differential
failure is visible as xfail-with-reason, not as a silent skip.
"""

from __future__ import annotations

import pytest

from streamlit_app.core import BedtoolsEngine, PolarsBioEngine

from .cases import DIFFERENTIAL_CASES
from .comparator import assert_canonical_equal, run_and_canonicalize

DIFFERENTIAL_BLOCKED_REASON = (
    "Differential comparison currently blocked: PolarsBioEngine output is not "
    "canonical, so canonicalize_annotation_result rejects it (both frames "
    "coord_-prefixed, polars-bio _1/_2 suffixes retained, internal pb_row_id "
    "leaked, no annot_* columns) before Bedtools and Polars-Bio results can be "
    "compared (SPEC 6; engine-contract section 3; Task 4 result adapter). For "
    "boundary fixtures the polars-bio 1-based-closed coordinate-system default "
    "additionally breaks half-open semantics (SPEC 5)."
)


@pytest.mark.xfail(strict=True, reason=DIFFERENTIAL_BLOCKED_REASON)
@pytest.mark.parametrize("case", DIFFERENTIAL_CASES, ids=lambda c: c.name)
def test_bedtools_equals_polars_bio_canonical(case):
    bedtools_result = run_and_canonicalize(
        BedtoolsEngine, case.coord_df, case.annot_df, how=case.how
    )
    polars_result = run_and_canonicalize(
        PolarsBioEngine, case.coord_df, case.annot_df, how=case.how
    )
    # strict: columns+order, row count, row order, NA-aware values, dtypes
    assert_canonical_equal(
        polars_result,
        bedtools_result,
        label=f"differential:{case.name}",
    )