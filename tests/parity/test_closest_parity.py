"""
Closest contract parity (PLAN Task 6E) — SPEC 8.6.

AnnotateR ``closest`` has one normative, backend-independent meaning:

    per query, over SAME-CHROMOSOME annotations only (strand
    eligibility, SPEC 8.3, applied BEFORE nearest selection when
    ``use_strand=True``)::

        distance(Q, A) = max(0, a_start - q_end, q_start - a_end)

i.e. the number of genomic bases in the gap between the two canonical
0-based half-open intervals: overlapping intervals have distance 0,
touching (bookended) intervals have distance 0, a one-base gap has
distance 1, and a larger gap is the exact number of intervening bases.

Per query EVERY annotation tied at the minimum distance is returned (no
arbitrary one-tie selection), in annotation input order; overall row
order is query input order, then that tie order — never genomic sort
order. ``min_overlap`` (SPEC 8.2) and the contains/within predicates
(SPEC 8.4/8.5) do NOT participate in closest mode.

``how="inner"``: zero rows for a query with no eligible candidate.
``how="left"``: every query survives; a query with no eligible candidate
appears exactly once with ``has_overlap=False``, canonical-missing
``annot_*`` fields and canonical-missing (``pd.NA``) distance.

The result carries the ``distance`` column as nullable integer (Int64):
matched rows carry an integer >= 0, unmatched left rows carry ``pd.NA``.
Backend-native distances (bedtools ``closest -d``, polars-bio
``nearest.distance``) are NON-NORMATIVE and never surface — both engines
delegate to the shared canonical selection in
``streamlit_app/core/annotator.py``, and no native closest/nearest call
is made at all (pinned in ``test_error_contract.py`` and
``test_bedtools_engine.py``).

Each case in ``CLOSEST_CASES`` carries its expected rows AND its
expected distances, both derived by hand from the definition above
(never from backend output), and is checked against BOTH engines
independently through the canonical adapter. The direct engine-vs-engine
layer lives in ``test_differential_parity.py`` (closest entries in
``DIFFERENTIAL_CASES``).
"""

from __future__ import annotations

import pandas as pd
import pytest

from streamlit_app.core import BedtoolsEngine, PolarsBioEngine
from streamlit_app.core.annotator import closest_matches, interval_distance

from .cases import CLOSEST_CASES
from .comparator import check_expected, interval_table, run_and_canonicalize
from .conftest import case_engine_params
from .fixtures import CHR

ENGINES = [
    pytest.param(BedtoolsEngine, id="bedtools"),
    pytest.param(PolarsBioEngine, id="polars-bio"),
]


@pytest.mark.parametrize("case_engine", case_engine_params(CLOSEST_CASES))
def test_closest_contract(case_engine):
    """Per-engine contract layer: explicit expected rows AND explicit
    expected canonical distances, both engines."""
    case, engine_cls = case_engine
    # ``distances`` is passed through as a tuple even when empty: an
    # empty tuple means "closest mode with the distance column, zero
    # rows" — so even 0-row closest results are checked for the
    # presence and Int64 type of ``distance`` (collapsing it to None
    # would drop the column from the expected frame).
    check_expected(
        engine_cls,
        case.coord_df,
        case.annot_df,
        case.pairs,
        how=case.how,
        label=case.name,
        distances=case.distances,
        **case.engine_kwargs,
    )


# ---------------------------------------------------------------------------
# Shared canonical distance helper (single definition, exact integers)
# ---------------------------------------------------------------------------


#: (q_start, q_end, a_start, a_end, expected_distance) — the SPEC 8.6
#: boundary truth table, values derived by hand from
#: ``max(0, a_start - q_end, q_start - a_end)``.
_DISTANCE_TRUTH_TABLE = [
    (10, 20, 15, 25, 0),   # overlap
    (10, 20, 10, 20, 0),   # exact equality
    (10, 30, 15, 20, 0),   # containment
    (10, 20, 20, 30, 0),   # touching right
    (10, 20, 0, 10, 0),    # touching left
    (10, 20, 21, 30, 1),   # one-base gap right
    (10, 20, 0, 9, 1),     # one-base gap left
    (10, 20, 25, 30, 5),   # larger gap right
    (10, 20, 0, 5, 5),     # larger gap left
]


@pytest.mark.parametrize(
    "q_start,q_end,a_start,a_end,expected", _DISTANCE_TRUTH_TABLE
)
def test_interval_distance_truth_table(q_start, q_end, a_start, a_end, expected):
    """The shared helper implements exactly the normative half-open gap
    formula for the full boundary table (scalar inputs)."""
    result = interval_distance(q_start, q_end, a_start, a_end)
    # Exact integer result (never a float; Python int or numpy integer).
    import numpy as np

    assert isinstance(result, (int, np.integer))
    assert not isinstance(result, float)
    assert int(result) == expected


def test_interval_distance_matches_compact_definition_on_arrays():
    """Elementwise vectorized evaluation equals the compact definition
    ``max(0, a_start - q_end, q_start - a_end)`` on arrays."""
    import numpy as np

    q_start = np.array([10, 100, 2**40, 0, 10], dtype="int64")
    q_end = np.array([20, 200, 2**40 + 10, 5, 20], dtype="int64")
    a_start = np.array([15, 15, 0, 5, 0], dtype="int64")
    a_end = np.array([25, 25, 5, 20, 9], dtype="int64")
    result = interval_distance(q_start, q_end, a_start, a_end)
    expected = np.maximum(
        0, np.maximum(a_start - q_end, q_start - a_end)
    )
    assert (result == expected).all()
    # overlap / gap 75 / huge exact gap / touching right / one-base gap left
    assert [int(v) for v in result] == [0, 75, 2**40 - 5, 0, 1]


def test_interval_distance_exact_for_large_coordinates():
    """Distance is exact integer arithmetic: large genomic coordinates
    must not be routed through floating point (a float would silently
    corrupt values beyond 2**53)."""
    large = 2**60
    # Q = [large, large+1), A = [large - 1, large) -> touching left -> 0
    assert interval_distance(large, large + 1, large - 1, large) == 0
    # A = [large + 3, large + 4) -> one-base... three-base gap: 2
    assert interval_distance(large, large + 1, large + 3, large + 4) == 2
    # A = [0, 5) -> gap = large - 5, exactly (2**60 - 5)
    assert interval_distance(large, large + 1, 0, 5) == 2**60 - 5


# ---------------------------------------------------------------------------
# Shared nearest selection (closest_matches)
# ---------------------------------------------------------------------------


def test_closest_matches_same_chromosome_only():
    """Distance is never defined across chromosomes: the chrB annotation
    (distance 0 numerically) is not a candidate for the chrA query."""
    q = interval_table([CHR], [10], [20], gene=["g1"])
    a = interval_table(["chrB", CHR], [11, 40], [15, 50], feature=["f1", "f2"])
    q_pos, a_pos = closest_matches(q, a, use_strand=False)
    assert list(q_pos) == [0]
    assert list(a_pos) == [1]


def test_closest_matches_all_ties_in_annotation_input_order():
    """A three-way tie at the same positive distance returns ALL three,
    in annotation input order (not coordinate order)."""
    q = interval_table([CHR], [10], [20], gene=["g1"])
    a = interval_table(
        [CHR, CHR, CHR], [25, 0, 25], [30, 5, 35],
        feature=["f1", "f2", "f3"],
    )
    q_pos, a_pos = closest_matches(q, a, use_strand=False)
    assert list(q_pos) == [0, 0, 0]
    assert list(a_pos) == [0, 1, 2]


def test_closest_matches_strand_filtering_before_nearest():
    """The mandatory stranded fixture: the nearer opposite-strand
    annotation (distance 1) must NOT suppress the farther same-strand
    annotation (distance 10) — strand eligibility is applied BEFORE
    nearest selection, not as a post-filter on the winner."""
    q = interval_table([CHR], [10], [20], gene=["g1"], strand=["+"])
    a = interval_table(
        [CHR, CHR], [21, 30], [30, 40],
        feature=["f1", "f2"], strand=["-", "+"],
    )
    q_pos, a_pos = closest_matches(q, a, use_strand=True)
    assert list(q_pos) == [0]
    assert list(a_pos) == [1]


def test_closest_matches_missing_strand_not_wildcard():
    """Missing/unknown strand never qualifies in stranded mode: neither
    a missing query strand nor a missing annotation strand, and
    unknown-vs-unknown is not a candidate either."""
    a = interval_table([CHR], [15], [25], feature=["f1"], strand=["+"])
    q_missing = interval_table([CHR], [10], [20], gene=["g1"], strand=[None])
    q_pos, a_pos = closest_matches(q_missing, a, use_strand=True)
    assert len(q_pos) == 0 and len(a_pos) == 0

    a_missing = interval_table([CHR], [15], [25], feature=["f1"], strand=[None])
    q_plus = interval_table([CHR], [10], [20], gene=["g1"], strand=["+"])
    q_pos, a_pos = closest_matches(q_plus, a_missing, use_strand=True)
    assert len(q_pos) == 0 and len(a_pos) == 0

    q_none = interval_table([CHR], [10], [20], gene=["g1"], strand=[None])
    a_none = interval_table([CHR], [15], [25], feature=["f1"], strand=[None])
    q_pos, a_pos = closest_matches(q_none, a_none, use_strand=True)
    assert len(q_pos) == 0 and len(a_pos) == 0


def test_pdna_strand_ineligible_not_crash_both_engines():
    """Independent spec-review regression: the normalization layer maps
    EVERY missing/unknown strand representation to exactly ``pd.NA``, and
    a plain tuple membership test on ``pd.NA`` raises ``TypeError: boolean
    value of NA is ambiguous``. A canonical missing annotation strand must
    simply be ineligible under ``use_strand=True`` (SPEC 8.6) — never a
    wildcard, never a crash — on BOTH engines."""
    for engine_cls in (BedtoolsEngine, PolarsBioEngine):
        query = pd.DataFrame({"chr": ["1"], "start": [0], "end": [10],
                              "strand": ["+"]})
        annot = pd.DataFrame({"chr": ["1"], "start": [100], "end": [200],
                              "strand": [pd.NA]})
        result = engine_cls(use_strand=True, mode="closest").intersect(
            query, annot, how="left")
        assert len(result) == 1
        assert not result.iloc[0]["has_overlap"]
        assert pd.isna(result.iloc[0]["distance"])
        assert pd.isna(result.iloc[0]["annot_start"])
        inner = engine_cls(use_strand=True, mode="closest").intersect(
            query, annot, how="inner")
        assert len(inner) == 0
        # The same pd.NA strand must also never suppress a farther eligible
        # annotation (strand-before-nearest with canonical missingness).
        annot2 = pd.DataFrame({"chr": ["1", "1"], "start": [100, 200],
                               "end": [200, 300],
                               "strand": [pd.NA, "+"]})
        result2 = engine_cls(use_strand=True, mode="closest").intersect(
            query, annot2, how="inner")
        assert len(result2) == 1
        assert result2.iloc[0]["annot_start"] == 200
        assert result2.iloc[0]["distance"] == 200 - 10


def test_closest_matches_unstranded_ignores_strand():
    """use_strand=False: strand metadata is irrelevant; the opposite-
    strand nearer annotation wins."""
    q = interval_table([CHR], [10], [20], gene=["g1"], strand=["+"])
    a = interval_table(
        [CHR, CHR], [21, 30], [30, 40],
        feature=["f1", "f2"], strand=["-", "+"],
    )
    q_pos, a_pos = closest_matches(q, a, use_strand=False)
    assert list(q_pos) == [0]
    assert list(a_pos) == [0]


def test_closest_matches_duplicate_queries_resolved_independently():
    """Two duplicate-valued queries are resolved by identity, each
    producing its own rows."""
    q = interval_table([CHR, CHR], [10, 10], [20, 20], gene=["g1", "g2"])
    a = interval_table([CHR], [25], [30], feature=["f1"])
    q_pos, a_pos = closest_matches(q, a, use_strand=False)
    assert list(q_pos) == [0, 1]
    assert list(a_pos) == [0, 0]


# ---------------------------------------------------------------------------
# Focused regressions (both engines)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_closest_off_by_one_regression_canonical_75(engine_cls):
    """The Task 5 documented Bedtools-vs-Polars-Bio discrepancy (Bedtools
    76 / Polars-Bio 75) is resolved canonically: the half-open gap
    between Q[100,200) and A[15,25) is exactly 100 - 25 = 75 for BOTH
    engines, as a nullable integer."""
    q = interval_table([CHR], [100], [200], gene=["g1"])
    a = interval_table([CHR], [15], [25], feature=["f1"])
    result = run_and_canonicalize(
        engine_cls, q, a, mode="closest", extra_columns=("distance",)
    )
    assert len(result) == 1
    assert result["distance"].iloc[0] == 75
    assert str(result["distance"].dtype) == "Int64"


def test_closest_regression_proves_native_bedtools_distance_never_leaks():
    """The canonical result (75) is NOT bedtools' native ``closest -d``
    value (76, gap + 1 for separated pairs): pin the native value
    directly so any future regression toward native distance arithmetic
    fails loudly instead of silently matching a backend."""
    import pybedtools

    q_bed = pybedtools.BedTool.from_dataframe(
        pd.DataFrame({"chrom": [CHR], "start": [100], "end": [200]})
    )
    a_bed = pybedtools.BedTool.from_dataframe(
        pd.DataFrame({"chrom": [CHR], "start": [15], "end": [25]})
    )
    raw = q_bed.closest(a_bed, d=True, t="first").to_dataframe(
        header=None, dtype=str
    )
    native_distance = int(raw.iloc[0, -1])
    # Observed native convention on the pinned bedtools: gap + 1 (76).
    assert native_distance == 76

    result = run_and_canonicalize(
        BedtoolsEngine,
        interval_table([CHR], [100], [200], gene=["g1"]),
        interval_table([CHR], [15], [25], feature=["f1"]),
        mode="closest",
        extra_columns=("distance",),
    )
    assert result["distance"].iloc[0] == 75  # canonical, not native


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_closest_left_unmatched_distance_is_canonical_missing(engine_cls):
    """Left mode: an unmatched query row carries canonical-missing
    (pd.NA) distance, has_overlap=False and canonical-missing annotation
    fields — exactly once, at its own query position."""
    q = interval_table([CHR, "chrC"], [10, 10], [20, 20], gene=["g1", "g2"])
    a = interval_table([CHR], [25], [30], feature=["f1"])
    result = run_and_canonicalize(
        engine_cls, q, a, how="left", mode="closest",
        extra_columns=("distance",),
    )
    assert list(result["coord_gene"]) == ["g1", "g2"]
    assert list(result["has_overlap"]) == [True, False]
    assert list(result["distance"]) == [5, pd.NA]
    assert pd.isna(result["annot_feature"].iloc[1])


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_closest_distance_dtype_is_nullable_integer(engine_cls):
    """Matched rows carry a non-negative integer distance; the column is
    Int64 (never a backend-native float)."""
    q = interval_table([CHR], [10], [20], gene=["g1"])
    a = interval_table([CHR, CHR], [0, 25], [5, 30], feature=["f1", "f2"])
    result = run_and_canonicalize(
        engine_cls, q, a, mode="closest", extra_columns=("distance",)
    )
    assert str(result["distance"].dtype) == "Int64"
    assert (result["distance"] >= 0).all()
    assert set(result["distance"]) == {5}