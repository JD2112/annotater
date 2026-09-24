"""
Within contract parity (PLAN Task 6D) — SPEC 8.5.

AnnotateR ``within`` has one normative, backend-independent meaning:

    within(Q, A) =
        a_start <= q_start
        AND
        a_end >= q_end

i.e. **the query interval is fully contained within the annotation
interval**. Directionality is fixed. Boundary equality counts
(identical intervals and shared left/right boundaries all qualify);
query-contains-annotation is the ``contains`` direction and must NOT
qualify; partial overlaps and touching intervals must NOT qualify.

``within`` is the directional inverse of ``contains`` (SPEC 8.4) with
respect to the query/annotation roles: equal intervals satisfy BOTH
relations. ``within`` is deliberately NOT ``min_overlap`` (SPEC 8.2):
``min_overlap`` is a query-relative coverage threshold defined for
overlap mode only, whereas ``within`` constrains both interval
boundaries against the annotation — a coverage threshold can pass while
``within`` fails (``Q=[10,20)`` vs ``A=[5,15)`` at ``min_overlap=0.5``)
— and ``min_overlap`` is not applied in within mode.

Strand composes with within by logical AND (SPEC 8.3): a contained pair
still requires both rows to carry an explicit equal strand under
``use_strand=True``, and missing/unknown strand is not a wildcard. In
left mode a query whose overlapping annotations all fail the containment
or strand predicate is unmatched exactly once (SPEC 7.2).

Each case in ``WITHIN_CASES`` carries its expected rows derived from the
definition above (never from backend output) and is checked against BOTH
engines independently through the canonical adapter. The direct
engine-vs-engine layer lives in ``test_differential_parity.py`` (within
entries in ``DIFFERENTIAL_CASES``).
"""

from __future__ import annotations

import pandas as pd
import polars_bio
import pybedtools
import pytest

from streamlit_app.core import BedtoolsEngine, PolarsBioEngine
from streamlit_app.core.annotator import (
    contains_keep_mask,
    min_overlap_keep_mask,
    within_keep_mask,
)

from .cases import WITHIN_CASES
from .comparator import check_expected, interval_table, run_and_canonicalize
from .conftest import case_engine_params
from .fixtures import CHR

ENGINES = [
    pytest.param(BedtoolsEngine, id="bedtools"),
    pytest.param(PolarsBioEngine, id="polars-bio"),
]


@pytest.mark.parametrize("case_engine", case_engine_params(WITHIN_CASES))
def test_within_contract(case_engine):
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


#: (q_start, q_end, a_start, a_end) truth-table rows.
_TRUTH_TABLE = [
    (15, 20, 10, 30),  # annotation larger than query (strict within)
    (10, 20, 10, 20),  # exact equality
    (10, 20, 10, 30),  # shared left boundary
    (10, 20, 5, 20),  # shared right boundary
    (10, 30, 15, 20),  # query contains annotation -> False
    (10, 20, 15, 25),  # partial right overlap -> False
    (10, 20, 5, 15),  # partial left overlap -> False
    (10, 20, 20, 30),  # touching right -> False
    (10, 20, 0, 10),  # touching left -> False
]


def test_within_predicate_truth_table():
    """The shared predicate itself, independent of any backend."""
    assert within_keep_mask(_pairs_frame(_TRUTH_TABLE)).tolist() == [
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


def test_within_predicate_missing_annotation_is_false():
    """Unmatched rows (no annotation coordinates) never satisfy within."""
    assert within_keep_mask(_pairs_frame([(15, 20, None, None)])).tolist() == [False]


def test_within_and_contains_are_directional_inverses():
    """``within(Q, A) == contains(A, Q)`` exactly: the two relations are the
    same predicate with the query/annotation roles swapped.

    Equality satisfies BOTH (equal intervals contain each other), and the
    query-contains-annotation direction is never a within match.
    """
    frame = _pairs_frame(_TRUTH_TABLE)
    swapped = _pairs_frame([(a, b, qs, qe) for (qs, qe, a, b) in _TRUTH_TABLE])
    assert within_keep_mask(frame).tolist() == contains_keep_mask(swapped).tolist()

    contains = contains_keep_mask(frame)
    within = within_keep_mask(frame)
    for i, (qs, qe, a_start, a_end) in enumerate(_TRUTH_TABLE):
        if (qs, qe) == (a_start, a_end):
            # Equality satisfies both relations.
            assert contains[i] and within[i], (qs, qe)
        else:
            # Never both: the two predicates are the opposite directions.
            assert not (contains[i] and within[i]), (qs, qe, a_start, a_end)


def test_within_implies_full_query_coverage():
    """A within pair always covers 100% of the query (query fraction 1.0).

    This is exactly why the Task 6A ``min_overlap`` mode gate is not
    observable *within within mode*: any valid threshold is already
    satisfied. The gate is still preserved (SPEC 8.2 is scoped to the
    overlap method) and the failing direction is pinned by the
    ``within_not_min_overlap_partial`` fixtures (a fractional threshold
    that passes while ``within`` fails).
    """
    pairs = [(15, 20, 10, 30), (10, 20, 10, 20), (10, 20, 0, 100)]
    frame = _pairs_frame(pairs)
    assert within_keep_mask(frame).all()
    assert min_overlap_keep_mask(frame, 1.0).all()


# ---------------------------------------------------------------------------
# Focused regressions (both engines)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_within_vs_contains_directionality(engine_cls):
    """within and contains are directional inverses of each other.

    A: Q[10,20), A[0,100). The annotation contains the query: within
       matches, contains must not.
    B: Q[0,100), A[10,20). The query contains the annotation: contains
       matches, within must not.
    C: Q[10,20), A[10,20). Equal intervals contain each other: both match.
    """
    # A — query smaller, annotation covering it.
    q = interval_table([CHR], [10], [20], gene=["g1"])
    a = interval_table([CHR], [0], [100], feature=["f1"])
    assert len(run_and_canonicalize(engine_cls, q, a, mode="within")) == 1
    assert len(run_and_canonicalize(engine_cls, q, a, mode="contains")) == 0

    # B — query larger, annotation contained.
    q2 = interval_table([CHR], [0], [100], gene=["g1"])
    a2 = interval_table([CHR], [10], [20], feature=["f1"])
    assert len(run_and_canonicalize(engine_cls, q2, a2, mode="within")) == 0
    assert len(run_and_canonicalize(engine_cls, q2, a2, mode="contains")) == 1

    # C — equality satisfies both.
    q3 = interval_table([CHR], [10], [20], gene=["g1"])
    a3 = interval_table([CHR], [10], [20], feature=["f1"])
    assert len(run_and_canonicalize(engine_cls, q3, a3, mode="within")) == 1
    assert len(run_and_canonicalize(engine_cls, q3, a3, mode="contains")) == 1


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_within_is_not_a_coverage_threshold(engine_cls):
    """``within`` is positional containment, not a query-fraction threshold.

    Q[10,20) vs A[5,15): the query fraction covered by the annotation is
    exactly 0.5, so ``min_overlap=0.5`` qualifies in overlap mode, while
    ``within`` must not qualify at any threshold.
    """
    q = interval_table([CHR], [10], [20], gene=["g1"])
    a = interval_table([CHR], [5], [15], feature=["f1"])
    assert len(run_and_canonicalize(engine_cls, q, a, min_overlap=0.5)) == 1
    assert len(run_and_canonicalize(engine_cls, q, a, mode="within")) == 0
    assert (
        len(run_and_canonicalize(engine_cls, q, a, mode="within", min_overlap=0.5))
        == 0
    )


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_min_overlap_not_applied_in_within_mode(engine_cls):
    """SPEC 8.2 is scoped to overlap mode: in within mode the containment
    predicate alone decides. The partial candidate passes a 0.5
    query-fraction threshold but must not qualify, inner or left."""
    q = interval_table([CHR], [10], [20], gene=["g1"])
    a = interval_table([CHR, CHR], [0, 5], [100, 15], feature=["a1", "a2"])

    inner = run_and_canonicalize(engine_cls, q, a, mode="within", min_overlap=0.5)
    assert len(inner) == 1
    assert list(inner["annot_feature"]) == ["a1"]

    left = run_and_canonicalize(
        engine_cls, q, a, how="left", mode="within", min_overlap=0.5
    )
    assert len(left) == 1
    assert bool(left["has_overlap"].iloc[0])
    assert list(left["annot_feature"]) == ["a1"]


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_min_overlap_not_applied_in_within_mode_left_unmatched(engine_cls):
    """A query whose only candidate passes the threshold but is not a
    within match appears exactly once, unmatched."""
    q = interval_table([CHR], [10], [20], gene=["g1"])
    a = interval_table([CHR], [5], [15], feature=["f1"])
    result = run_and_canonicalize(
        engine_cls, q, a, how="left", mode="within", min_overlap=0.5
    )
    assert len(result) == 1
    assert not bool(result["has_overlap"].iloc[0])
    assert pd.isna(result["annot_feature"].iloc[0])


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_within_left_reconstruction(engine_cls):
    """A query whose only overlaps fail containment is unmatched exactly
    once; a query with a containing match emits only that match."""
    q = interval_table([CHR, CHR], [10, 200], [20, 300], gene=["q1", "q2"])
    a = interval_table([CHR, CHR], [0, 250], [100, 260], feature=["a1", "a2"])
    result = run_and_canonicalize(engine_cls, q, a, how="left", mode="within")
    assert len(result) == 2
    assert list(result["coord_gene"]) == ["q1", "q2"]
    assert list(result["has_overlap"]) == [True, False]
    assert pd.isna(result["annot_feature"].iloc[1])


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_within_respects_left_over_inner_row_counts(engine_cls):
    """Empty-annotation left mode preserves every query row unmatched
    (SPEC 7.2), while inner mode yields zero rows."""
    q = interval_table([CHR, CHR], [15, 100], [20, 200], gene=["q1", "q2"])
    empty = interval_table([], [], [], feature=[])
    inner = run_and_canonicalize(engine_cls, q, empty, mode="within")
    assert len(inner) == 0
    left = run_and_canonicalize(engine_cls, q, empty, how="left", mode="within")
    assert len(left) == 2
    assert list(left["coord_gene"]) == ["q1", "q2"]
    assert not left["has_overlap"].any()


# ---------------------------------------------------------------------------
# Candidate-generation strategy (ordinary overlap, never a fraction flag or
# a Cartesian product)
# ---------------------------------------------------------------------------


def test_bedtools_within_uses_ordinary_overlap_candidates(monkeypatch):
    """within must NOT be mapped to a bedtools fraction flag: candidates
    come from an ordinary (unfiltered) ``intersect`` and AnnotateR applies
    the shared predicate. In particular the old ``-F 1.0`` placeholder —
    a minimum overlap as a fraction of B (the annotation), i.e. the
    *contains* direction — is not used."""
    seen = {}
    real = pybedtools.BedTool.intersect

    def spy(self, other, **kwargs):
        seen["kwargs"] = dict(kwargs)
        return real(self, other, **kwargs)

    monkeypatch.setattr(pybedtools.BedTool, "intersect", spy)
    q = interval_table([CHR], [15], [20], gene=["g1"])
    a = interval_table([CHR], [10], [30], feature=["f1"])
    BedtoolsEngine(mode="within").intersect(q, a, how="inner")
    assert "f" not in seen["kwargs"] and "F" not in seen["kwargs"]
    assert "r" not in seen["kwargs"] and "e" not in seen["kwargs"]


def test_polars_within_uses_ordinary_overlap_candidates(monkeypatch):
    """Pinned polars-bio 0.35.1 exposes no containment primitive, so within
    must run ordinary ``pb.overlap`` and filter canonically — never pass a
    fraction/containment option."""
    seen = {}
    real = polars_bio.overlap

    def spy(*args, **kwargs):
        seen["kwargs"] = dict(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(polars_bio, "overlap", spy)
    q = interval_table([CHR], [15], [20], gene=["g1"])
    a = interval_table([CHR], [10], [30], feature=["f1"])
    PolarsBioEngine(mode="within").intersect(q, a, how="inner")
    assert seen["kwargs"]["cols1"] == ["chrom", "start", "end"]
    assert seen["kwargs"]["cols2"] == ["chrom", "start", "end"]
    assert not {"f", "F", "min_overlap", "fraction", "contains", "within"} & set(
        seen["kwargs"]
    )
