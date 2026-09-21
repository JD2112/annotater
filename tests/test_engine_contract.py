"""
Engine contract tests (PLAN Task 2.5)

Both engines — BedtoolsEngine and PolarsBioEngine — are exercised through
the *same* small coordinate and annotation tables and checked against the
contract in SPEC.md section 9 and docs/engine-contract.md:

1. ``how="inner"`` with one matching and one non-matching query row
   returns exactly the matched query/annotation pairs, all with
   ``has_overlap=True``;
2. ``how="left"`` preserves the non-matching query row exactly once with
   ``has_overlap=False``;
3. a query with no match produces zero result rows for ``how="inner"``
   (never a fake single-row placeholder) and exactly the one preserved
   query row for ``how="left"``.

Additionally, SPEC section 4 boundary semantics are locked down for both
engines: touching intervals do not overlap; one-base overlaps do.

Two groups of tests encode the *canonical result schema* contract
(``coord_*`` / ``annot_*`` column names, canonical missing values, no
backend-suffixed artifacts). As of Task 2.5 the current implementations
deviate from that schema in documented ways (see docs/implementation-notes.md,
"Current implementation limitations"):

- PolarsBioEngine emits ``coord_*``-prefixed columns for *both* frames,
  polars-bio ``_1``/``_2`` suffixes, and an internal ``pb_row_id`` column;
- BedtoolsEngine emits bedtools left-join sentinel values (``.`` / ``-1``)
  instead of canonical missing values on unmatched annotation fields;
- PolarsBioEngine never declares the 0-based coordinate system to
  polars-bio 0.35.1, whose global default is 1-based closed intervals.
  AnnotateR's canonical 0-based half-open data is therefore re-interpreted:
  touching intervals ([10,20) vs [20,25)) are wrongly reported as overlaps.
  (Setting ``pb.set_option("datafusion.bio.coordinate_system_zero_based",
  True)`` restores correct half-open behavior — the engine must do this
  explicitly, which is Task 3/4 work.)

Those assertions are marked ``xfail(strict=False)`` per engine so the
deviations are captured precisely without blocking the suite. When a
later task (Task 3/4) fixes an engine, the marker flips to XPASS and
should be removed.
"""

from __future__ import annotations

import pandas as pd
import pytest

from streamlit_app.core import BedtoolsEngine, PolarsBioEngine

#: Canonical inner/left result columns for the fixtures used in this module
#: (query metadata column: ``gene``; annotation metadata column: ``feature``).
EXPECTED_CANONICAL_COLUMNS = [
    "coord_chr",
    "coord_start",
    "coord_end",
    "coord_gene",
    "annot_chr",
    "annot_start",
    "annot_end",
    "annot_feature",
    "has_overlap",
]

ENGINES = [
    pytest.param(BedtoolsEngine, id="bedtools"),
    pytest.param(PolarsBioEngine, id="polars-bio"),
]


def make_fixture():
    """One matching pair (100-200 vs 150-250), one touching-but-matching
    pair (2000-2100 vs 2000-2050), and one non-matching query row (10-20)."""
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
    """Locate the query-start column without assuming the exact (not yet
    canonical) column names emitted by each backend."""
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
# Semantic contract (holds for both engines as of Task 2.5)
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


# ---------------------------------------------------------------------------
# SPEC section 4: half-open boundary semantics, identical for both engines
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "engine_cls",
    [
        pytest.param(BedtoolsEngine, id="bedtools"),
        pytest.param(
            PolarsBioEngine,
            id="polars-bio",
            marks=pytest.mark.xfail(
                strict=False,
                reason=(
                    "Task 2.5 audit: PolarsBioEngine does not declare the 0-based "
                    "coordinate system, so polars-bio 0.35.1's 1-based closed-interval "
                    "global default re-interprets canonical half-open data and reports "
                    "touching intervals [10,20)/[20,25) as overlapping (SPEC section 4 "
                    "requires no overlap at boundaries). Fix belongs to Task 3/4."
                ),
            ),
        ),
    ],
)
def test_touching_intervals_do_not_overlap(engine_cls):
    coord_df = pd.DataFrame({"chr": ["chrA"], "start": [10], "end": [20], "gene": ["g"]})
    annot_df = pd.DataFrame({"chr": ["chrA"], "start": [20], "end": [25], "feature": ["f"]})
    result = engine_cls().intersect(coord_df, annot_df, how="inner")
    assert len(result) == 0


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


# ---------------------------------------------------------------------------
# Canonical result schema contract (currently deviated from — see module doc)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "engine_cls",
    [
        pytest.param(BedtoolsEngine, id="bedtools"),
        pytest.param(
            PolarsBioEngine,
            id="polars-bio",
            marks=pytest.mark.xfail(
                strict=False,
                reason=(
                    "Task 2.5 audit: PolarsBioEngine emits coord_-prefixed columns for "
                    "both frames plus polars-bio _1/_2 suffixes and an internal "
                    "pb_row_id column, not the canonical coord_*/annot_* result set."
                ),
            ),
        ),
    ],
)
def test_inner_canonical_result_columns(engine_cls):
    coord_df, annot_df = make_fixture()
    result = engine_cls().intersect(coord_df, annot_df, how="inner")

    assert list(result.columns) == EXPECTED_CANONICAL_COLUMNS
    assert result["has_overlap"].dtype == bool


@pytest.mark.parametrize(
    "engine_cls",
    [
        pytest.param(
            BedtoolsEngine,
            id="bedtools",
            marks=pytest.mark.xfail(
                strict=False,
                reason=(
                    "Task 2.5 audit: bedtools left-join sentinel values ('.'/'-1') leak "
                    "into unmatched annotation fields instead of canonical missing "
                    "values (docs/engine-contract.md section 6)."
                ),
            ),
        ),
        pytest.param(
            PolarsBioEngine,
            id="polars-bio",
            marks=pytest.mark.xfail(
                strict=False,
                reason=(
                    "Task 2.5 audit: PolarsBioEngine left mode mixes clean coord_* "
                    "columns with suffixed backend columns for both frames; annotation "
                    "fields lack the annot_ provenance prefix."
                ),
            ),
        ),
    ],
)
def test_left_canonical_missing_values(engine_cls):
    coord_df, annot_df = make_fixture()
    result = engine_cls().intersect(coord_df, annot_df, how="left")

    assert list(result.columns) == EXPECTED_CANONICAL_COLUMNS
    nomatch = result[~result["has_overlap"].astype(bool)]
    assert len(nomatch) == 1
    annot_cols = [c for c in EXPECTED_CANONICAL_COLUMNS if c.startswith("annot_")]
    # Unmatched annotation fields are canonical missing values (NA), not
    # backend sentinels such as '.' or -1.
    assert bool(nomatch[annot_cols].isna().all().all())
    assert result["has_overlap"].dtype == bool


@pytest.mark.parametrize(
    "engine_cls",
    [
        pytest.param(BedtoolsEngine, id="bedtools"),
        pytest.param(
            PolarsBioEngine,
            id="polars-bio",
            marks=pytest.mark.xfail(
                strict=False,
                reason=(
                    "Task 2.5 audit: backend artifacts (polars-bio _1/_2 suffixes and "
                    "internal pb_row_id row identity) are present in emitted column "
                    "names; per SPEC section 9.2 such schemas are intermediate only."
                ),
            ),
        ),
    ],
)
def test_no_backend_artifacts_in_result_columns(engine_cls):
    coord_df, annot_df = make_fixture()
    engine = engine_cls()
    for how in ("inner", "left"):
        result = engine.intersect(coord_df, annot_df, how=how)
        offenders = [
            c
            for c in result.columns
            if ("_1" in c or "_2" in c or "pb_row_id" in c)
        ]
        assert not offenders, f"{how}: backend artifacts leaked: {offenders}"