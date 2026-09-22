"""
Backend RAW-layer diagnostics (PLAN Task 3).

These tests inspect engine output BEFORE canonical result
normalization, isolating the exact layer where each known deviation
lives. They complement the canonical-level contract tests:

- a deviation flagged at the raw layer explains WHY a canonical-level
  test xfails (root-cause attribution);
- positive raw controls document which layers are already conformant,
  so Task 4/5 work can be scoped precisely.

No fix is attempted here; each deviation is captured with a precise
root-cause xfail reason (inventory in docs/implementation-notes.md).
"""

from __future__ import annotations

import pytest

from streamlit_app.core import BedtoolsEngine, PolarsBioEngine
from streamlit_app.core.schema import canonical_result_columns, canonicalize_annotation_result

from .comparator import is_missing, interval_table, run_engine

CHR = "chrA"


# ---------------------------------------------------------------------------
# Polars-Bio raw layer
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    strict=True,
    reason=(
        "PolarsBioEngine does not declare the coordinate system, so "
        "polars-bio 0.35.1's 1-based CLOSED-interval default interprets "
        "canonical 0-based half-open intervals [10,20) and [20,25) as "
        "overlapping (they only touch). The RAW overlap call already "
        "produces the wrong row set; no amount of post-processing can "
        "repair it. Fix belongs to the engine: set the coordinate-system "
        "global option or normalize inputs. SPEC 5; engine-contract "
        "section 4. Task 4."
    ),
)
def test_polars_raw_touching_intervals_do_not_overlap():
    raw = run_engine(
        PolarsBioEngine,
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [20], [25], feature=["f1"]),
        how="inner",
    )
    assert len(raw) == 0, f"touching intervals must not overlap, got {len(raw)} raw rows"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "PolarsBioEngine._post_process emits a non-canonical raw schema: "
        "both frames are coord_-prefixed, polars-bio _1/_2 column suffixes "
        "are retained, the internal pb_row_id column is leaked, and no "
        "annot_* columns exist, so canonicalize_annotation_result raises "
        "CanonicalSchemaError. SPEC 6 exact canonical column set; SPEC 9.2 "
        "(provenance must not be guessed by suffix heuristics); "
        "engine-contract section 3. Task 4."
    ),
)
def test_polars_raw_inner_output_is_canonical():
    coord_df = interval_table([CHR], [10], [20], gene=["g1"])
    annot_df = interval_table([CHR, CHR], [5, 25], [15, 35], feature=["f1", "f2"])
    raw = run_engine(PolarsBioEngine, coord_df, annot_df, how="inner")
    # the canonical adapter must accept the raw frame as-is
    canonicalize_annotation_result(raw, coord_df, annot_df)
    assert list(raw.columns) == list(canonical_result_columns(coord_df, annot_df))


def test_polars_raw_left_reconstructs_unmatched_queries():
    """
    POSITIVE CONTROL: the polars-bio left-reconstruction logic
    (row-id join back onto the query frame) DOES preserve unmatched
    query rows at the raw layer. The polars-bio left-mode deviation is
    therefore ONLY the non-canonical schema, not row loss.
    """
    raw = run_engine(
        PolarsBioEngine,
        interval_table([CHR, CHR], [10, 100], [20, 200], gene=["g1", "g2"]),
        interval_table([CHR], [15], [25], feature=["f1"]),
        how="left",
    )
    assert len(raw) == 2  # both query rows survive at the raw layer


# ---------------------------------------------------------------------------
# Bedtools raw layer
# ---------------------------------------------------------------------------

def test_bedtools_raw_inner_output_is_canonical():
    """
    POSITIVE CONTROL: for inner mode on non-empty inputs, BedtoolsEngine
    raw output already matches the canonical schema (coord_*/annot_*
    provenance, has_overlap bool); the canonical adapter passes it
    through. Bedtools deviations live elsewhere (left sentinels,
    metadata round-trip, empty-input guard — see other modules).
    """
    coord_df = interval_table([CHR], [10], [20], gene=["g1"])
    annot_df = interval_table([CHR, CHR], [5, 25], [15, 35], feature=["f1", "f2"])
    raw = run_engine(BedtoolsEngine, coord_df, annot_df, how="inner")
    canonicalize_annotation_result(raw, coord_df, annot_df)  # must not raise
    assert list(raw.columns) == list(canonical_result_columns(coord_df, annot_df))


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BedtoolsEngine raw left-mode output keeps bedtools -loj sentinel "
        "values ('.' and '-1') in unmatched annotation fields instead of "
        "canonical missing values (SPEC 6; engine-contract sections 6/8). "
        "Today the canonical adapter masks this at the public level; the "
        "engine itself must emit canonical missing directly. Task 5."
    ),
)
def test_bedtools_raw_left_unmatched_uses_canonical_missing():
    raw = run_engine(
        BedtoolsEngine,
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [100], [200], feature=["f1"]),
        how="left",
    )
    assert len(raw) == 1
    row = raw.iloc[0]
    for col in raw.columns:
        if col.startswith("annot_"):
            assert is_missing(row[col]), (
                f"unmatched annot field {col!r} must be canonical missing, "
                f"got {row[col]!r}"
            )