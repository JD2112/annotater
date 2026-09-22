"""
Metadata provenance parity (PLAN Task 3) — SPEC 6.

Verifies that canonical output carries ``coord_*`` / ``annot_*``
provenance prefixes, preserves arbitrary / numeric / boolean / missing
metadata deterministically, keeps metadata column order, and rejects
input metadata using the reserved ``coord_``/``annot_`` prefixes
(Task 2 reserved-name policy, enforced at the normalization layer).

No backend artifact (``_1``, ``_2``, ``_right``, ``pb_row_id``, sentinel
strings) may appear in a passing canonical result: the comparator's
exact-column check and cell-wise value equality make any such leak a
test failure.
"""

from __future__ import annotations

import pytest

from streamlit_app.core.normalization import normalize_intervals
from streamlit_app.core.schema import CanonicalSchemaError

from .cases import METADATA_CASES
from .comparator import check_expected, interval_table
from .conftest import case_engine_params


@pytest.mark.parametrize("case_engine", case_engine_params(METADATA_CASES))
def test_metadata_provenance_contract(case_engine):
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
    "reserved_name", ["coord_feature", "annot_score"]
)
def test_reserved_prefixes_rejected_at_normalization(reserved_name):
    """
    Source metadata may not use the reserved canonical result prefixes
    (Task 2 policy): normalization must reject such columns explicitly
    instead of letting them collide with result provenance.
    """
    df = interval_table(["chrA"], [10], [20], **{reserved_name: ["x"]})
    with pytest.raises(CanonicalSchemaError, match="reserved"):
        normalize_intervals(df, coordinate_system="0-based")