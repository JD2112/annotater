"""
Contains contract parity (PLAN Task 6C) — SPEC 8.4.

AnnotateR ``contains`` has one normative, backend-independent meaning:

    contains(Q, A) =
        q_start <= a_start
        AND
        q_end >= a_end

i.e. **the query interval fully contains the annotation interval**.
Directionality is fixed. Boundary equality counts (identical intervals
and shared left/right boundaries all qualify); annotation-contains-query
is the ``within`` direction and must NOT qualify; partial overlaps and
touching intervals must NOT qualify.

``contains`` is deliberately NOT ``min_overlap == 1.0``: ``min_overlap``
measures the fraction of the QUERY covered by the annotation (SPEC 8.2)
and is defined for overlap mode only, whereas containment constrains both
annotation boundaries against the query. Neither predicate implies the
other, and ``min_overlap`` is not applied in contains mode.

Strand composes with contains by logical AND (SPEC 8.3): a contained pair
still requires both rows to carry an explicit equal strand under
``use_strand=True``. In left mode a query whose overlapping annotations
all fail the containment or strand predicate is unmatched exactly once
(SPEC 7.2).

Each case in ``CONTAINS_CASES`` carries its expected rows derived from
the definition above (never from backend output) and is checked against
BOTH engines independently through the canonical adapter. The direct
engine-vs-engine layer lives in ``test_differential_parity.py``
(contains entries in ``DIFFERENTIAL_CASES``).
"""

from __future__ import annotations

import pandas as pd
import polars_bio
import pybedtools
import pytest

from streamlit_app.core import BedtoolsEngine, PolarsBioEngine
from streamlit_app.core.annotator import contains_keep_mask

from .cases import CONTAINS_CASES
from .comparator import check_expected, interval_table, run_and_canonicalize
from .conftest import case_engine_params
from .fixtures import CHR

ENGINES = [
    pytest.param(BedtoolsEngine, id="bedtools"),
    pytest.param(PolarsBioEngine, id="polars-bio"),
]


@pytest.mark.parametrize("case_engine", case_engine_params(CONTAINS_CASES))
def test_contains_contract(case_engine):
    """Per-engine contract layer: explicit expected rows, both engines."""
    case, engine_cls = case_engine
    check_expected(
        engine_cls,
        case.coord_df,
        case.annot_df,
        case.pairs,
        how=case.how,
        label=case.name,
        **case.engine_kwargs,
    )


# ---------------------------------------------------------------------------
# Shared predicate (backend-independent units)
# ---------------------------------------------------------------------------


def _pairs_frame(rows) -> pd.DataFrame:
    """Canonical-column frame for direct predicate unit tests."""
    return pd.DataFrame(
        {
            "coord_start": [r[0] for r in rows],
            "coord_end": [r[1] for r in rows],
            "annot_start": pd.array([r[2] for r in rows], dtype="Int64"),
            "annot_end": pd.array([r[3] for r in rows], dtype="Int64"),
        }
    )


def test_contains_predicate_truth_table():
    """The shared predicate itself, independent of any backend."""
    frame = _pairs_frame(
        [
            (10, 30, 15, 20),  # strict containment
            (10, 20, 10, 20),  # exact equality
            (10, 30, 10, 20),  # shared left boundary
            (5, 20, 10, 20),  # shared right boundary
            (15, 20, 10, 30),  # annotation contains query -> False
            (10, 20, 15, 25),  # partial right overlap -> False
            (10, 20, 5, 15),  # partial left overlap -> False
            (10, 20, 20, 25),  # touching right -> False
            (10, 20, 5, 10),  # touching left -> False
        ]
    )
    assert contains_keep_mask(frame).tolist() == [
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
    ]


def test_contains_predicate_missing_annotation_is_false():
    """Unmatched rows (no annotation coordinates) never satisfy containment."""
    assert contains_keep_mask(_pairs_frame([(10, 30, None, None)])).tolist() == [False]


# ---------------------------------------------------------------------------
# Focused regressions (both engines)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_contains_vs_min_overlap_1_asymmetry(engine_cls):
    """contains and overlap+min_overlap=1.0 are different predicates.

    A: Q[10,20), A[0,100). The annotation covers the whole query
       (min_overlap=1.0 matches) but the query does not contain the
       annotation (contains must not match).
    B: Q[0,100), A[10,20). The query contains the annotation (contains
       matches) but the annotation covers only 10% of the query
       (min_overlap=1.0 must not match).
    """
    # A — query smaller, annotation covering it.
    q = interval_table([CHR], [10], [20], gene=["g1"])
    a = interval_table([CHR], [0], [100], feature=["f1"])
    assert len(run_and_canonicalize(engine_cls, q, a, mode="contains")) == 0
    assert len(run_and_canonicalize(engine_cls, q, a, min_overlap=1.0)) == 1

    # B — query larger, annotation contained.
    q2 = interval_table([CHR], [0], [100], gene=["g1"])
    a2 = interval_table([CHR], [10], [20], feature=["f1"])
    assert len(run_and_canonicalize(engine_cls, q2, a2, mode="contains")) == 1
    assert len(run_and_canonicalize(engine_cls, q2, a2, min_overlap=1.0)) == 0


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_min_overlap_not_applied_in_contains_mode(engine_cls):
    """SPEC 8.2 is scoped to overlap mode: a contained pair whose query
    coverage is below the threshold must still match, inner and left."""
    q = interval_table([CHR], [0], [100], gene=["g1"])
    a = interval_table([CHR], [10], [20], feature=["f1"])
    inner = run_and_canonicalize(engine_cls, q, a, mode="contains", min_overlap=1.0)
    assert len(inner) == 1
    assert bool(inner["has_overlap"].iloc[0])
    left = run_and_canonicalize(
        engine_cls, q, a, how="left", mode="contains", min_overlap=1.0
    )
    assert len(left) == 1
    assert bool(left["has_overlap"].iloc[0])


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_contains_left_reconstruction(engine_cls):
    """A query whose only overlaps are not contained is unmatched exactly
    once; a query with a contained match emits only that match."""
    q = interval_table([CHR, CHR], [10, 200], [20, 300], gene=["q1", "q2"])
    a = interval_table([CHR, CHR], [15, 250], [25, 260], feature=["a1", "a2"])
    result = run_and_canonicalize(engine_cls, q, a, how="left", mode="contains")
    assert len(result) == 2
    assert list(result["coord_gene"]) == ["q1", "q2"]
    assert list(result["has_overlap"]) == [False, True]
    assert pd.isna(result["annot_feature"].iloc[0])


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_contains_respects_left_over_inner_row_counts(engine_cls):
    """Empty-annotation left mode preserves every query row unmatched
    (SPEC 7.2), while inner mode yields zero rows."""
    q = interval_table([CHR, CHR], [10, 100], [30, 200], gene=["q1", "q2"])
    empty = interval_table([], [], [], feature=[])
    inner = run_and_canonicalize(engine_cls, q, empty, mode="contains")
    assert len(inner) == 0
    left = run_and_canonicalize(engine_cls, q, empty, how="left", mode="contains")
    assert len(left) == 2
    assert list(left["coord_gene"]) == ["q1", "q2"]
    assert not left["has_overlap"].any()


# ---------------------------------------------------------------------------
# Candidate-generation strategy (ordinary overlap, never a fraction flag or
# a Cartesian product)
# ---------------------------------------------------------------------------


def test_bedtools_contains_uses_ordinary_overlap_candidates(monkeypatch):
    """contains must NOT be mapped to a bedtools fraction flag: candidates
    come from an ordinary (unfiltered) ``intersect`` and AnnotateR applies
    the shared predicate. ``-f``/``-F`` remain only for the non-normative
    ``within`` placeholder."""
    seen = {}
    real = pybedtools.BedTool.intersect

    def spy(self, other, **kwargs):
        seen["kwargs"] = dict(kwargs)
        return real(self, other, **kwargs)

    monkeypatch.setattr(pybedtools.BedTool, "intersect", spy)
    q = interval_table([CHR], [10], [30], gene=["g1"])
    a = interval_table([CHR], [15], [20], feature=["f1"])
    BedtoolsEngine(mode="contains").intersect(q, a, how="inner")
    assert "f" not in seen["kwargs"] and "F" not in seen["kwargs"]
    assert "r" not in seen["kwargs"] and "e" not in seen["kwargs"]


def test_polars_contains_uses_ordinary_overlap_candidates(monkeypatch):
    """Pinned polars-bio exposes no query-contains-annotation primitive, so
    contains must run ordinary ``pb.overlap`` and filter canonically —
    never pass a fraction/containment option."""
    seen = {}
    real = polars_bio.overlap

    def spy(*args, **kwargs):
        seen["kwargs"] = dict(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(polars_bio, "overlap", spy)
    q = interval_table([CHR], [10], [30], gene=["g1"])
    a = interval_table([CHR], [15], [20], feature=["f1"])
    PolarsBioEngine(mode="contains").intersect(q, a, how="inner")
    assert seen["kwargs"]["cols1"] == ["chrom", "start", "end"]
    assert seen["kwargs"]["cols2"] == ["chrom", "start", "end"]
    assert not {"f", "F", "min_overlap", "fraction", "contains"} & set(seen["kwargs"])
