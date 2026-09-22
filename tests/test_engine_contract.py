"""
Engine contract SMOKE tests (shrunken in PLAN Task 3).

The systematic Bedtools <-> Polars-Bio parity harness now lives in
``tests/parity/`` and owns:

- explicit per-engine expected-result fixtures (overlap, boundary,
  left-join, metadata, ordering, strand) with the strict canonical
  comparator;
- every known engine deviation as ``xfail(strict=True)`` with a precise
  root-cause reason (Task 2.5 deviations were migrated there, none lost);
- differential Bedtools-vs-Polars-Bio comparison;
- raw-layer diagnostics that attribute each deviation to its exact layer.

This module keeps only smoke-level contract assertions that hold for
BOTH engines today and deliberately operate on RAW engine output with
lenient column lookup (canonical-level behavior is the parity harness's
job). It exists so a catastrophic regression in either engine
(crash, grossly wrong row set) is visible without running the full
parity matrix.
"""

from __future__ import annotations

import pandas as pd
import pytest

from streamlit_app.core import BedtoolsEngine, PolarsBioEngine

ENGINES = [
    pytest.param(BedtoolsEngine, id="bedtools"),
    pytest.param(PolarsBioEngine, id="polars-bio"),
]


def make_fixture():
    """One matching pair (100-200 vs 150-250), one overlapping pair
    (2000-2100 vs 2000-2050), and one non-matching query row (10-20)."""
    coord_df = pd.DataFrame(
        {
            "chr": ["chrA", "chrA", "chrA"],
            "start": [100, 10, 2000],
            "end": [200, 20, 2100],
            "gene": ["g1", "g2", "g3"],
        }
    )
    annot_df = pd.DataFrame(
        {
            "chr": ["chrA", "chrA"],
            "start": [150, 2000],
            "end": [250, 2050],
            "feature": ["f1", "f2"],
        }
    )
    return coord_df, annot_df


def make_no_match_fixture():
    """Query on chrA, annotations only on chrB: zero overlaps."""
    coord_df = pd.DataFrame(
        {"chr": ["chrA"], "start": [100], "end": [200], "gene": ["g1"]}
    )
    annot_df = pd.DataFrame(
        {"chr": ["chrB"], "start": [150], "end": [250], "feature": ["f1"]}
    )
    return coord_df, annot_df


def _coord_start_column(df: pd.DataFrame) -> str:
    """Locate the query-start column without assuming the exact
    (not yet canonical for all engines) column names each backend emits."""
    for col in df.columns:
        if col.startswith("coord") and "start" in col.lower():
            return col
    raise AssertionError(f"no coord start column in {list(df.columns)}")


def _feature_column(df: pd.DataFrame) -> str:
    for col in df.columns:
        if "feature" in col.lower():
            return col
    raise AssertionError(f"no feature column in {list(df.columns)}")


# ---------------------------------------------------------------------------
# Semantic smoke contract (raw output; lenient column lookup)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_inner_returns_only_matched_pairs(engine_cls):
    coord_df, annot_df = make_fixture()
    result = engine_cls().intersect(coord_df, annot_df, how="inner")

    # Exactly the two overlapping query/annotation pairs, nothing else.
    assert len(result) == 2
    assert set(result[_coord_start_column(result)].tolist()) == {100, 2000}
    assert set(result[_feature_column(result)].tolist()) == {"f1", "f2"}
    assert bool((result["has_overlap"] == True).all())  # noqa: E712


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_left_preserves_non_matching_query_row_once(engine_cls):
    coord_df, annot_df = make_fixture()
    result = engine_cls().intersect(coord_df, annot_df, how="left")

    start = _coord_start_column(result)
    pairs = set(zip(result[start].tolist(), result["has_overlap"].astype(bool).tolist()))
    assert pairs == {(100, True), (10, False), (2000, True)}
    # The unmatched query row appears exactly once.
    assert int((result["has_overlap"].astype(bool) == False).sum()) == 1  # noqa: E712


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_no_match_inner_is_zero_rows(engine_cls):
    coord_df, annot_df = make_no_match_fixture()
    result = engine_cls().intersect(coord_df, annot_df, how="inner")

    # No match must yield zero rows — never a fake single-row placeholder.
    assert len(result) == 0


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_no_match_left_preserves_query_with_no_overlap(engine_cls):
    coord_df, annot_df = make_no_match_fixture()
    result = engine_cls().intersect(coord_df, annot_df, how="left")

    assert len(result) == 1
    start = _coord_start_column(result)
    assert result.iloc[0][start] == 100
    assert bool(result["has_overlap"].astype(bool).iloc[0]) is False


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_one_base_overlap_counts(engine_cls):
    coord_df = pd.DataFrame({"chr": ["chrA"], "start": [10], "end": [20], "gene": ["g"]})
    annot_df = pd.DataFrame({"chr": ["chrA"], "start": [19], "end": [20], "feature": ["f"]})
    result = engine_cls().intersect(coord_df, annot_df, how="inner")
    assert len(result) == 1
    assert bool((result["has_overlap"] == True).all())  # noqa: E712


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_different_chromosomes_never_overlap(engine_cls):
    coord_df = pd.DataFrame({"chr": ["chrA"], "start": [10], "end": [20], "gene": ["g"]})
    annot_df = pd.DataFrame({"chr": ["chrB"], "start": [10], "end": [20], "feature": ["f"]})
    result = engine_cls().intersect(coord_df, annot_df, how="inner")
    assert len(result) == 0


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_unknown_mode_raises_explicitly(engine_cls):
    coord_df, annot_df = make_fixture()
    engine = engine_cls(mode="bogus")
    with pytest.raises(ValueError):
        engine.intersect(coord_df, annot_df, how="inner")