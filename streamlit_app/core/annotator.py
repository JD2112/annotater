"""
Annotation engine for coordinate intersection

Uses pybedtools for fast, memory-efficient genomic coordinate operations
"""

import logging
import math
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Literal, Optional, Union
import tempfile

import numpy as np
import pandas as pd
import polars as pl
import polars_bio as pb
import pybedtools
from .schema import (
    CANONICAL_MISSING,
    HAS_OVERLAP_COLUMN,
    STRAND_VALUES,
    CanonicalSchemaError,
    canonical_result_columns,
    interval_metadata_columns,
    validate_canonical_interval_table,
)

logger = logging.getLogger(__name__)


def validate_min_overlap(min_overlap) -> Optional[float]:
    """
    Validate AnnotateR's ``min_overlap`` threshold (SPEC 8.2, Task 6A).

    Accepts ``None`` (no fractional threshold; ordinary positive
    overlap) or a numeric value in ``[0, 1]`` — int or float, so the
    integers ``0``/``1`` are valid numeric equivalents (normalized to
    ``float``). Raises ``ValueError`` for out-of-range values, NaN,
    infinities, booleans, and non-numeric types; invalid values are
    rejected, never clamped.

    Shared by every engine (via ``AnnotationEngine.__init__``) so all
    backends validate identically, BEFORE any backend execution.
    """
    if min_overlap is None:
        return None
    if isinstance(min_overlap, bool) or not isinstance(min_overlap, (int, float)):
        raise ValueError(
            f"min_overlap must be None or a number in [0, 1]; "
            f"got {min_overlap!r}"
        )
    if math.isnan(min_overlap) or not (0.0 <= min_overlap <= 1.0):
        raise ValueError(
            f"min_overlap must be in [0, 1]; got {min_overlap!r}"
        )
    return float(min_overlap)


def min_overlap_keep_mask(df: pd.DataFrame, min_overlap: float) -> np.ndarray:
    """
    Shared canonical ``min_overlap`` predicate (SPEC 8.2, Task 6A).

    A matched pair qualifies iff::

        overlap_length > 0
        AND overlap_length / query_length >= min_overlap

    where ``overlap_length = max(0, min(coord_end, annot_end) -
    max(coord_start, annot_start))`` and ``query_length =
    coord_end - coord_start``: the fraction is relative to the QUERY
    interval (never the annotation), there is no reciprocal
    requirement, and each row (query/annotation pair) is evaluated
    independently — coverage from multiple annotation rows is never
    summed. The threshold comparison is inclusive (``>=``).

    This is the single contract-level definition of ``min_overlap``;
    both engines apply exactly this predicate so the meaning is
    backend-independent. Rows with missing annotation coordinates
    (unmatched rows) evaluate to False; left-mode reconstruction
    decides their fate.
    """
    q_start = df["coord_start"].to_numpy(dtype="float64")
    q_end = df["coord_end"].to_numpy(dtype="float64")
    a_start = df["annot_start"].to_numpy(dtype="float64", na_value=np.nan)
    a_end = df["annot_end"].to_numpy(dtype="float64", na_value=np.nan)
    overlap = np.maximum(
        0.0, np.minimum(q_end, a_end) - np.maximum(q_start, a_start)
    )
    query_length = q_end - q_start
    with np.errstate(invalid="ignore", divide="ignore"):
        fraction = overlap / query_length
    return (overlap > 0) & (fraction >= min_overlap)


def strand_keep_mask(
    df: pd.DataFrame, q_meta: List[str], a_meta: List[str]
) -> np.ndarray:
    """
    Shared canonical ``use_strand=True`` predicate (SPEC 8.3, Task 6B).

    A matched pair qualifies as stranded iff::

        Q.strand in {"+", "-"}
        AND A.strand in {"+", "-"}
        AND Q.strand == A.strand

    Missing/unknown strand is NOT a wildcard and NOT a strand: a row
    whose strand is canonical missing — or an input that has no strand
    column at all — can never form a stranded match, including
    unknown-vs-unknown. Canonical validation guarantees the only
    explicit states are ``"+"``/``"-"``, so equality of two present
    values is the entire predicate.

    This is the single contract-level definition of ``use_strand=True``;
    both engines apply exactly this predicate over the ordinary backend
    overlap pairs (after backend matching, before left reconstruction),
    so the meaning is identical by construction. Strand composes with
    ``min_overlap`` by logical AND — the predicates are independent and
    neither bypasses the other.
    """
    if "strand" not in q_meta or "strand" not in a_meta:
        # No explicit strand on one side: no stranded match is possible
        # (this is NOT a fall-back to unstranded mode).
        return np.zeros(len(df), dtype=bool)
    q = df["coord_strand"]
    a = df["annot_strand"]
    # pandas Series comparison maps canonical missing (pd.NA/NaN) to
    # False element-wise — exactly the "missing is not a strand" rule.
    keep = np.zeros(len(df), dtype=bool)
    for value in STRAND_VALUES:
        keep |= ((q == value) & (a == value)).to_numpy()
    return keep


def contains_keep_mask(df: pd.DataFrame) -> np.ndarray:
    """
    Shared canonical ``mode="contains"`` predicate (SPEC 8.4, Task 6C).

    AnnotateR ``contains`` means **the query interval fully contains the
    annotation interval**::

        contains(Q, A) =
            q_start <= a_start
            AND
            q_end >= a_end

    Directionality is fixed: the query is the containing interval and the
    annotation is the contained interval. Boundary equality counts, so
    identical intervals and shared left/right boundaries all qualify.
    Annotation-contains-query is the ``within`` direction and does NOT
    qualify; partial overlaps and touching intervals do not qualify
    either (a true containment pair necessarily overlaps, but overlap
    alone is not containment).

    ``contains`` is explicitly NOT ``min_overlap == 1.0`` (SPEC 8.2):
    ``min_overlap`` measures the fraction of the QUERY interval covered by
    the annotation (overlap mode only), whereas containment constrains
    both annotation boundaries against the query. Neither implication
    holds in either direction, and ``min_overlap`` is deliberately not
    applied in contains mode.

    This is the single contract-level definition of ``contains``; both
    engines apply exactly this predicate over ordinary backend overlap
    candidate pairs, so the meaning is backend-independent by
    construction. Unmatched rows (missing annotation coordinates)
    evaluate to False; left-mode reconstruction decides their fate.
    """
    q_start = df["coord_start"].to_numpy(dtype="float64")
    q_end = df["coord_end"].to_numpy(dtype="float64")
    a_start = df["annot_start"].to_numpy(dtype="float64", na_value=np.nan)
    a_end = df["annot_end"].to_numpy(dtype="float64", na_value=np.nan)
    return (q_start <= a_start) & (q_end >= a_end)


def within_keep_mask(df: pd.DataFrame) -> np.ndarray:
    """
    Shared canonical ``mode="within"`` predicate (SPEC 8.5, Task 6D).

    AnnotateR ``within`` means **the query interval is fully contained
    within the annotation interval**::

        within(Q, A) =
            a_start <= q_start
            AND
            a_end >= q_end

    Directionality is fixed: the annotation is the containing interval and
    the query is the contained interval. Boundary equality counts, so
    identical intervals and shared left/right boundaries all qualify.
    Query-contains-annotation is the ``contains`` direction (SPEC 8.4) and
    does NOT qualify; partial overlaps and touching intervals do not
    qualify either (a true containment pair necessarily overlaps, but
    overlap alone is not containment).

    ``within`` is the directional inverse of ``contains`` with respect to
    the query/annotation roles: ``contains(Q, A)`` constrains
    ``q_start <= a_start AND q_end >= a_end`` (query contains annotation),
    while ``within(Q, A)`` constrains the opposite way (annotation contains
    query). Equality satisfies BOTH relations, since equal intervals
    contain each other.

    ``within`` is explicitly NOT ``min_overlap`` (SPEC 8.2). ``min_overlap``
    is a query-relative coverage threshold defined for overlap mode only;
    ``within`` is a positional containment predicate over both interval
    boundaries. ``min_overlap`` is deliberately not applied in within mode
    (the Task 6A mode gate is preserved), and ``within`` is never inferred
    from an overlap percentage (a query-fraction threshold can pass while
    ``within`` fails, e.g. ``Q=[10,20)`` vs ``A=[5,15)`` at
    ``min_overlap=0.5``).

    This is the single contract-level definition of ``within``; both
    engines apply exactly this predicate over ordinary backend overlap
    candidate pairs, so the meaning is backend-independent by
    construction. Unmatched rows (missing annotation coordinates)
    evaluate to False; left-mode reconstruction decides their fate.
    """
    q_start = df["coord_start"].to_numpy(dtype="float64")
    q_end = df["coord_end"].to_numpy(dtype="float64")
    a_start = df["annot_start"].to_numpy(dtype="float64", na_value=np.nan)
    a_end = df["annot_end"].to_numpy(dtype="float64", na_value=np.nan)
    return (a_start <= q_start) & (a_end >= q_end)


def interval_distance(q_start, q_end, a_start, a_end):
    """
    Shared canonical ``mode="closest"`` distance (SPEC 8.6, Task 6E).

    For canonical 0-based half-open intervals ``Q=[q_start, q_end)`` and
    ``A=[a_start, a_end)``::

        distance(Q, A) = max(0, a_start - q_end, q_start - a_end)

    i.e. the number of genomic bases in the gap between the two
    half-open intervals: overlapping intervals have distance 0,
    bookended (touching) intervals have distance 0, a one-base gap has
    distance 1, and a larger gap is the exact number of intervening
    bases. Accepts scalars or numpy arrays (evaluated elementwise) and
    uses exact integer arithmetic only — never floating point.

    This is the SINGLE contract-level definition of closest distance.
    Both engines emit exactly this value, recomputed from canonical
    coordinates for every emitted row; backend-native distances are
    non-normative and never surface (observed on bedtools 2.31.1:
    ``closest -d`` reports gap + 1 for separated pairs — 76 where the
    canonical gap is 75 — and 1 for bookended pairs; polars-bio 0.35.1
    ``nearest`` reports the half-open gap itself, 75 / 0. Neither value
    defines the AnnotateR contract; see docs/references.md).
    """
    return np.maximum(0, np.maximum(a_start - q_end, q_start - a_end))


def _python_scalar(value):
    """Reduce numpy scalar types to their Python equivalents.

    The canonicalizer publishes object-dtype metadata columns built via
    ``astype(object)`` (Python ``int``/``float``/``bool``), so result
    adapters must emit the same scalar types for identical input values.
    """
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def _values_at(df: pd.DataFrame, column: str, row_ids: np.ndarray) -> np.ndarray:
    """
    Original values of ``df[column]`` at positional ``row_ids``.

    Missing input values become canonical missing (``pd.NA``); a row id
    of -1 (unmatched row) is always canonical missing. Values keep their
    original semantic type (numpy scalars are reduced to the equivalent
    Python scalars, mirroring the canonicalizer's object-dtype
    publication) — no value or dtype re-inference. Shared by the
    BedtoolsEngine adapter and the shared closest builder.
    """
    series = df[column]
    values = series.to_numpy()
    missing = series.isna().to_numpy()
    out = np.full(len(row_ids), pd.NA, dtype=object)
    valid = row_ids >= 0
    rv = row_ids[valid]
    out[valid] = [
        pd.NA if m else _python_scalar(v)
        for m, v in zip(missing[rv], values[rv])
    ]
    return out


def _ints_at(df: pd.DataFrame, column: str, row_ids: np.ndarray):
    """Integer coordinate values at ``row_ids``; -1 (unmatched) -> pd.NA."""
    values = df[column].to_numpy()
    out = pd.array([pd.NA] * len(row_ids), dtype="Int64")
    for i, rid in enumerate(row_ids):
        if rid >= 0:
            out[i] = int(values[rid])
    return out


class _ClosestAnnotations:
    """
    One chromosome's (optionally one strand's) annotation rows,
    precomputed for canonical nearest selection (SPEC 8.6, Task 6E).

    Built once per group: a start-sorted view with the prefix maximum of
    ends (strict-overlap detection), an end-sorted view (left-gap
    predecessor lookup), and exact-position hash indexes (recovery of
    every positive-distance tie without scanning). ``pos`` always holds
    annotation INPUT row positions, ascending.
    """

    __slots__ = ("pos", "starts", "ends", "_s_starts", "_pre_max_end",
                 "_e_ends", "_by_start", "_by_end")

    def __init__(self, pos: np.ndarray, starts: np.ndarray, ends: np.ndarray):
        self.pos = pos
        self.starts = starts[pos]
        self.ends = ends[pos]
        start_order = np.argsort(self.starts, kind="stable")
        self._s_starts = self.starts[start_order]
        self._pre_max_end = np.maximum.accumulate(self.ends[start_order])
        self._e_ends = np.sort(self.ends, kind="stable")
        self._by_start = {}
        self._by_end = {}
        for p, s, e in zip(pos.tolist(), self.starts.tolist(), self.ends.tolist()):
            self._by_start.setdefault(s, []).append(p)
            self._by_end.setdefault(e, []).append(p)

    def minimum_distance(self, q_start: int, q_end: int) -> int:
        """
        Minimum canonical ``interval_distance`` from ``[q_start, q_end)``
        to any group member, computed over the sorted interval arrays via
        binary search — never by materializing every query x annotation
        distance:

        - a strict overlap (``start < q_end`` and ``end > q_start``)
          means 0; the annotations starting below ``q_end`` are exactly
          the start-sorted prefix ``[0, j)``, so their prefix-maximum end
          decides whether any of them reaches past ``q_start``;
        - otherwise the nearest candidate is either the first annotation
          starting at/after ``q_end`` (right gap) or the last annotation
          ending at/before ``q_start`` (left gap): any non-overlapping
          interval satisfies ``start >= q_end`` OR ``end <= q_start``,
          and ``interval_distance`` is exactly those two gaps.

        Touching intervals fall out as distance 0 from either gap side.
        """
        j = int(np.searchsorted(self._s_starts, q_end, side="left"))
        if j > 0 and int(self._pre_max_end[j - 1]) > q_start:
            return 0
        best = None
        if j < self._s_starts.shape[0]:
            best = int(self._s_starts[j]) - q_end          # 0 when touching right
        k = int(np.searchsorted(self._e_ends, q_start, side="right")) - 1
        if k >= 0:
            gap = q_start - int(self._e_ends[k])           # 0 when touching left
            best = gap if best is None else min(best, gap)
        if best is None:
            # Defensive fallback (a non-empty group always yields a
            # candidate above): apply the shared definition directly.
            best = int(interval_distance(q_start, q_end, self.starts, self.ends).min())
        return best

    def ties(self, q_start: int, q_end: int, d_min: int) -> np.ndarray:
        """
        Every group member at canonical distance ``d_min``, in annotation
        input order (SPEC 8.6: ALL ties are returned — no arbitrary
        tie-break, no sorting by coordinate/strand/length/backend order).
        """
        if d_min == 0:
            # distance == 0  <=>  start <= q_end AND end >= q_start
            # (overlap OR bookended), evaluated with the shared helper.
            mask = interval_distance(q_start, q_end, self.starts, self.ends) == 0
            return self.pos[mask]
        # d > 0: distance == max(0, start - q_end, q_start - end) equals d
        # iff start == q_end + d (then end > start > q_end > q_start, so
        # the left gap is negative) OR end == q_start - d (then the right
        # gap is negative). Both at once would force
        # end = q_start - d < q_end + d = start, contradicting end >
        # start — so two exact-position lookups cover every tie, without
        # scanning the group.
        positions = list(self._by_start.get(q_end + d_min, ()))
        positions.extend(self._by_end.get(q_start - d_min, ()))
        positions.sort()
        return np.asarray(positions, dtype="int64")


def _closest_annotations(
    annot_df: pd.DataFrame, use_strand: bool
) -> Dict[object, _ClosestAnnotations]:
    """
    Group annotation rows for canonical nearest selection (SPEC 8.6).

    Keyed by chromosome when ``use_strand`` is False; keyed by
    ``(chromosome, strand)`` when True — so strand eligibility (SPEC
    8.3) is applied BEFORE nearest selection: only annotations carrying
    an explicit ``+``/``-`` strand enter a stranded group, and a query
    only consults the group matching its own explicit strand.
    Missing/unknown strand never joins a stranded group (not a
    wildcard), and an input without a strand column yields no groups at
    all (=> no stranded candidate), identically for both engines.
    """
    if len(annot_df) == 0:
        return {}
    chr_values = annot_df["chr"].to_numpy(dtype=object)
    starts = annot_df["start"].to_numpy(dtype="int64")
    ends = annot_df["end"].to_numpy(dtype="int64")
    strands = None
    if use_strand:
        if "strand" not in annot_df.columns:
            return {}
        strands = annot_df["strand"].to_numpy(dtype=object)
    buckets: Dict[object, list] = {}
    for idx in range(len(annot_df)):
        if use_strand:
            strand = strands[idx]
            # ``pd.isna`` first: a canonical missing value (``pd.NA``) in
            # the tuple membership test would raise ``TypeError: boolean
            # value of NA is ambiguous`` instead of simply being ineligible.
            if pd.isna(strand) or strand not in STRAND_VALUES:
                continue  # missing/unknown strand is never eligible
            key = (chr_values[idx], strand)
        else:
            key = chr_values[idx]
        buckets.setdefault(key, []).append(idx)
    return {
        key: _ClosestAnnotations(
            np.asarray(positions, dtype="int64"), starts, ends
        )
        for key, positions in buckets.items()
    }


def closest_matches(
    coord_df: pd.DataFrame, annot_df: pd.DataFrame, *, use_strand: bool = False
):
    """
    Shared canonical nearest selection (SPEC 8.6, Task 6E).

    Returns ``(query_positions, annot_positions)``: int64 arrays in the
    canonical row order — query input order, then annotation input order
    among the tied nearest rows of each query. Queries with no eligible
    candidate are absent (left-mode reconstruction is the caller's job).

    Per-query pipeline, in this strict order:

    1. same-chromosome candidates only (annotation groups are keyed by
       chromosome; distance is never defined across chromosomes);
    2. strand eligibility BEFORE nearest selection when ``use_strand``
       (SPEC 8.3): both rows must carry an explicit ``+``/``-`` strand
       and be equal — missing/unknown strand is not a wildcard, so a
       wrong-strand nearer candidate can never suppress a farther
       same-strand candidate;
    3. canonical ``interval_distance`` for every remaining candidate,
       with the minimum computed over sorted interval arrays;
    4. ALL candidates at the per-query minimum distance are returned
       (all ties), keeping annotation input order.

    ``min_overlap`` (SPEC 8.2) and the contains/within predicates (SPEC
    8.4/8.5) deliberately play no part here: they belong to their own
    modes.

    Candidate search is constrained, never a genome-wide Cartesian
    product: annotations are grouped by chromosome (and strand when
    stranded), minima come from binary searches over sorted arrays, and
    positive-distance ties are recovered by exact-position hash
    lookups; only distance-0 ties (all of which are emitted anyway) need
    a vectorized scan of the query's own group.
    """
    empty = (np.empty(0, dtype="int64"), np.empty(0, dtype="int64"))
    if len(coord_df) == 0 or len(annot_df) == 0:
        return empty
    groups = _closest_annotations(annot_df, use_strand)
    if not groups:
        return empty

    q_chr = coord_df["chr"].to_numpy(dtype=object)
    q_starts = coord_df["start"].to_numpy(dtype="int64")
    q_ends = coord_df["end"].to_numpy(dtype="int64")
    if use_strand:
        if "strand" not in coord_df.columns:
            return empty
        q_strands = coord_df["strand"].to_numpy(dtype=object)
        q_stranded_ok = coord_df["strand"].isin(list(STRAND_VALUES)).to_numpy()

    q_parts: list = []
    a_parts: list = []
    for i in range(len(coord_df)):
        if use_strand:
            if not q_stranded_ok[i]:
                continue  # a query without an explicit strand never qualifies
            key = (q_chr[i], q_strands[i])
        else:
            key = q_chr[i]
        group = groups.get(key)
        if group is None:
            continue  # no eligible annotation on this chromosome
        q_start = int(q_starts[i])
        q_end = int(q_ends[i])
        d_min = group.minimum_distance(q_start, q_end)
        ties = group.ties(q_start, q_end, d_min)
        if len(ties):
            q_parts.append(np.full(len(ties), i, dtype="int64"))
            a_parts.append(ties)
    if not q_parts:
        return empty
    return np.concatenate(q_parts), np.concatenate(a_parts)


def canonical_closest(
    coord_df: pd.DataFrame,
    annot_df: pd.DataFrame,
    how: str = "inner",
    *,
    use_strand: bool = False,
) -> pd.DataFrame:
    """
    Shared canonical ``mode="closest"`` implementation (SPEC 8.6,
    Task 6E) — used by BOTH engines, so rows, distance, tie behavior and
    ordering are backend-independent by construction.

    Contract:

    - same-chromosome candidates only (via ``closest_matches``);
    - strand eligibility before nearest selection when ``use_strand``
      (SPEC 8.3: explicit equal ``+``/``-``; missing is not a wildcard);
    - canonical ``interval_distance`` recomputed from canonical
      coordinates for every emitted row — backend-native distances
      (bedtools ``-d``, polars-bio ``nearest.distance``) never surface;
    - ALL annotations tied at the minimum distance are returned, in
      annotation input order; overall order is query input order then
      that tie order (genomic input order is never required and never
      imposed);
    - ``min_overlap`` (SPEC 8.2) and the contains/within predicates
      (SPEC 8.4/8.5) do NOT participate in closest mode;
    - ``how="inner"``: only queries with at least one eligible
      candidate (zero rows when none). ``how="left"``: every query row
      survives; a query with no candidate appears exactly once with
      canonical-missing ``annot_*``, ``has_overlap=False`` and missing
      ``distance``.

    Returns the raw canonical frame (canonical columns + ``distance``)
    with ``distance`` as nullable integer (``Int64``, ``pd.NA`` on
    unmatched rows); an empty result is an empty frame. No backend call
    is made, so there is no native failure mode to swallow — malformed
    input remains the engines' explicit pre-dispatch validation (SPEC
    9.2).
    """
    q_meta = interval_metadata_columns(coord_df)
    a_meta = interval_metadata_columns(annot_df)

    q_pos, a_pos = closest_matches(coord_df, annot_df, use_strand=use_strand)

    if how == "left" and len(coord_df):
        matched_queries = np.unique(q_pos)
        unmatched_queries = np.setdiff1d(
            np.arange(len(coord_df), dtype="int64"), matched_queries
        )
        if len(unmatched_queries):
            q_pos = np.concatenate([q_pos, unmatched_queries])
            a_pos = np.concatenate(
                [a_pos, np.full(len(unmatched_queries), -1, dtype="int64")]
            )

    if len(q_pos) == 0:
        return pd.DataFrame()

    # Canonical order: query input order, then annotation input order
    # among that query's ties. The stable sort preserves emission order
    # within a query, and a query is either fully matched or unmatched
    # (never both), so unmatched rows land exactly at their own query
    # position. Backend-internal ordering is irrelevant: no backend runs.
    order = np.argsort(q_pos, kind="stable")
    q_pos = q_pos[order]
    a_pos = a_pos[order]
    matched = a_pos >= 0

    out = pd.DataFrame(index=pd.RangeIndex(len(q_pos)))
    out["coord_chr"] = _values_at(coord_df, "chr", q_pos)
    out["coord_start"] = coord_df["start"].to_numpy(dtype="int64")[q_pos]
    out["coord_end"] = coord_df["end"].to_numpy(dtype="int64")[q_pos]
    for name in q_meta:
        out[f"coord_{name}"] = _values_at(coord_df, name, q_pos)
    out["annot_chr"] = _values_at(annot_df, "chr", a_pos)
    out["annot_start"] = _ints_at(annot_df, "start", a_pos)
    out["annot_end"] = _ints_at(annot_df, "end", a_pos)
    for name in a_meta:
        out[f"annot_{name}"] = _values_at(annot_df, name, a_pos)
    out[HAS_OVERLAP_COLUMN] = matched

    # Canonical distance (nullable integer): recomputed from canonical
    # coordinates with the single shared helper. The -1 sentinel only
    # marks unmatched rows inside this builder and is replaced below —
    # a canonical distance is always >= 0, so -1 can never be emitted.
    distance_values = np.full(len(a_pos), -1, dtype="int64")
    safe_a = a_pos[matched]
    distance_values[matched] = interval_distance(
        out["coord_start"].to_numpy()[matched],
        out["coord_end"].to_numpy()[matched],
        annot_df["start"].to_numpy(dtype="int64")[safe_a],
        annot_df["end"].to_numpy(dtype="int64")[safe_a],
    )
    distance = pd.array(distance_values, dtype="Int64")
    distance[~matched] = pd.NA
    out["distance"] = distance

    return out[list(canonical_result_columns(coord_df, annot_df)) + ["distance"]]


class AnnotationEngine(ABC):
    """
    Abstract base class for annotation engines
    """
    
    def __init__(
        self,
        use_strand: bool = False,
        min_overlap: Optional[float] = None,
        mode: Literal["overlap", "contains", "within", "closest"] = "overlap"
    ):
        self.use_strand = use_strand
        # Shared parameter validation (SPEC 8.2, Task 6A): identical for
        # every backend, and performed before any backend execution.
        self.min_overlap = validate_min_overlap(min_overlap)
        self.mode = mode
    
    @abstractmethod
    def intersect(
        self,
        coord_df: pd.DataFrame,
        annot_df: pd.DataFrame,
        how: Literal["inner", "left"] = "inner"
    ) -> pd.DataFrame:
        pass


_BT_QUERY_ROW_ID = "_bt_query_row_id"
_BT_ANNOT_ROW_ID = "_bt_annot_row_id"

#: Columns per side in the identity-only serialization: chr, start, end,
#: <row id>. There is deliberately NO stranded serialization anymore:
#: strand qualification is the shared canonical predicate (SPEC 8.3,
#: Task 6B), and closest (SPEC 8.6, Task 6E) never invokes bedtools at
#: all, so no ``-s``/column-6 layout exists anywhere.
_BT_COLUMNS_PER_SIDE = 4


class BedtoolsEngine(AnnotationEngine):
    """
    Coordinate intersection using pybedtools (external bedtools binary).

    Canonical result contract (SPEC 4.2; docs/engine-contract.md 4-8):

    - Canonical inputs (0-based half-open ``chr``/``start``/``end`` plus
      metadata) are validated before the backend call; malformed input
      raises explicitly instead of returning a silent empty result.
    - The bedtools text file is an interop boundary that carries ONLY
      coordinates plus a collision-safe internal row-identity column per
      side. User metadata never crosses the text boundary: after matching,
      every published coord/annotation/metadata value is re-attached from
      the original input frames by row identity. Lossy round-tripping
      (missing values becoming '.', numeric-looking strings re-typed as
      floats) is therefore structurally impossible.
    - Match determination is structural, not value-based: bedtools ``-loj``
      fills unmatched annotation fields with sentinels ('.', -1); the
      adapter reads the INTERNAL annotation row-identity column, where '.'
      can only be a bedtools-generated sentinel. Real user metadata values
      such as '.' or '-1' can never be mistaken for missing values.
    - Left mode preserves every query row: an empty annotation table is
      handled deterministically BEFORE the external call (no bedtools
      invocation); otherwise ``-loj`` output is adapted and any query row
      still missing from the raw output is reconstructed by set difference
      on query row IDs. Unmatched rows carry canonical missing (``pd.NA``)
      in every ``annot_*`` field and ``has_overlap=False``.
    - Rows are sorted by (query row id, annotation row id) — input row
      identity, never genomic coordinate — giving the canonical order
      (query input order, then annotation input order) including for
      duplicate-valued rows.
    - ``use_strand=True`` (Task 6B, SPEC 8.3) is NOT delegated to
      bedtools ``-s``: the overlap path runs an ordinary unstranded
      ``intersect`` and applies the shared canonical strand predicate
      ``strand_keep_mask`` as a post-filter after matching and before
      left reconstruction. A pair qualifies only if both rows carry an
      explicit canonical strand (``+``/``-``) and the strands are equal;
      missing/unknown strand is not a wildcard. (Task 6E removed the
      closest placeholder entirely: closest no longer invokes bedtools
      at all, so no native ``-s`` serialization or flag exists anywhere.)
    - ``min_overlap`` (Task 6A) is NOT forwarded to bedtools ``-f``:
      the canonical query-fraction contract (SPEC 8.2) is applied as
      the shared post-filter ``min_overlap_keep_mask`` over ordinary
      overlap pairs, after matching and before left reconstruction.
      No bedtools fraction flag is used anywhere on the overlap path:
      bedtools itself rejects ``-f 0.0`` (its range is ``(0.0, 1.0]``),
      so a native mapping could not even express the valid no-op
      threshold ``0``.
    - ``mode="contains"`` (Task 6C, SPEC 8.4) means the QUERY interval
      fully contains the ANNOTATION interval
      (``q_start <= a_start AND q_end >= a_end``). It is NOT delegated
      to a bedtools fraction flag: candidates come from an ordinary
      (unfiltered) ``intersect`` — containment implies overlap, so this
      is lossless and avoids a Cartesian product — and the shared
      canonical predicate ``contains_keep_mask`` is applied as a
      post-filter after matching and before left reconstruction, so
      both engines enforce the identical meaning. Bedtools'
      ``-f 1.0`` (a fraction of A) was the old placeholder mapping and
      is a different, backend-defined predicate; it is no longer used
      for ``contains``. ``min_overlap`` is NOT applied in contains mode
      (SPEC 8.2 is defined for the overlap method only).
    - ``mode="within"`` (Task 6D, SPEC 8.5) is the directional inverse
      of ``contains``: the ANNOTATION interval fully contains the QUERY
      interval (``a_start <= q_start AND a_end >= q_end``). It uses the
      same architecture — ordinary overlap candidates plus the shared
      canonical predicate ``within_keep_mask`` after matching and
      before left reconstruction — so both engines enforce the
      identical meaning. Bedtools ``-F 1.0`` (a minimum overlap as a
      fraction of B, i.e. the annotation) was the old within
      placeholder mapping and actually computed the *contains*
      direction with an inner-only join; it was removed, not preserved
      (a backend fraction flag must not define an AnnotateR relation).
      ``min_overlap`` is NOT applied in within mode (SPEC 8.2 is
      defined for the overlap method only).
    - ``mode="closest"`` (Task 6E, SPEC 8.6) is ONE backend-independent
      operation: the engine delegates to the shared canonical
      ``canonical_closest`` selection — same-chromosome candidates,
      strand eligibility BEFORE nearest selection, canonical
      ``interval_distance``, ALL minimum-distance ties in annotation
      input order, left reconstruction. The bedtools ``closest`` binary
      is NOT used at all, so none of its behaviors can define a public
      result: not the genomically-sorted-input requirement (AnnotateR
      input order is preserved as-is), not the ``-d`` distance
      convention (gap + 1 for separated pairs, 1 for bookended pairs),
      not ``-t first`` tie dropping, and not ``-s`` strand filtering.
      ``min_overlap`` and the contains/within predicates do not
      participate in closest mode.
    - Backend and conversion exceptions propagate to the caller. A 0-row
      result with no exception is a genuine no-match (a valid empty
      result), never a swallowed failure (SPEC 9.2). (Closest makes no
      backend call; its only failure mode is explicit input
      validation.)
    """

    def intersect(
        self,
        coord_df: pd.DataFrame,
        annot_df: pd.DataFrame,
        how: Literal["inner", "left"] = "inner"
    ) -> pd.DataFrame:
        """Intersect canonical interval tables and return canonical results."""
        # Engine inputs MUST be canonical (SPEC 4.2): fail explicitly on
        # malformed input instead of returning a silent empty result.
        validate_canonical_interval_table(coord_df)
        validate_canonical_interval_table(annot_df)

        if self.mode in ("overlap", "contains", "within"):
            # ``contains`` (SPEC 8.4, Task 6C) and ``within`` (SPEC 8.5,
            # Task 6D) share the ordinary overlap candidate generation: a
            # true containment pair (in either direction) necessarily
            # overlaps, so backend overlap is a lossless candidate filter
            # (never a Cartesian query x annotation product). The shared
            # canonical interval-relation predicate selected by ``mode``
            # is applied inside ``_overlap`` after matching and before
            # left reconstruction; ``how`` is respected so left mode
            # preserves every query row.
            return self._overlap(coord_df, annot_df, how)
        if self.mode == "closest":
            # ``closest`` (SPEC 8.6, Task 6E) is ONE backend-independent
            # operation: both engines delegate to the shared canonical
            # selection ``canonical_closest`` (same-chromosome,
            # strand-before-nearest, canonical ``interval_distance``,
            # all ties, left reconstruction). Nothing about bedtools
            # ``closest`` — sorted input, ``-d``, ``-t``, ``-s`` — can
            # influence a public result.
            return canonical_closest(
                coord_df, annot_df, how=how, use_strand=self.use_strand
            )
        raise ValueError(f"Unknown mode: {self.mode}")

    # ------------------------------------------------------------------
    # Overlap / contains / within (inner + left)
    # ------------------------------------------------------------------

    def _overlap(
        self,
        coord_df: pd.DataFrame,
        annot_df: pd.DataFrame,
        how: str,
    ) -> pd.DataFrame:
        q_meta = self._metadata_columns(coord_df)
        a_meta = self._metadata_columns(annot_df)
        q_id = self._row_id_column(coord_df.columns, _BT_QUERY_ROW_ID)
        a_id = self._row_id_column(annot_df.columns, _BT_ANNOT_ROW_ID)

        # Deterministic empty-input handling BEFORE the external call: the
        # canonical result is already known, so bedtools is not invoked.
        # left mode must preserve every query row even when the annotation
        # table is empty (SPEC 7.2).
        if len(coord_df) == 0:
            return pd.DataFrame()
        if len(annot_df) == 0:
            if how == "left":
                return self._finalize(
                    self._unmatched_query_rows(
                        coord_df, annot_df, q_meta, a_meta,
                        list(range(len(coord_df))), q_id, a_id,
                    ),
                    coord_df, annot_df, q_id, a_id,
                )
            return pd.DataFrame()

        per_side = _BT_COLUMNS_PER_SIDE
        logger.debug(
            "Running bedtools intersect on %d x %d rows",
            len(coord_df), len(annot_df),
        )
        # min_overlap is deliberately NOT forwarded to bedtools -f,
        # use_strand is deliberately NOT forwarded to bedtools -s, and no
        # fraction flag is used for contains/within: the canonical
        # query-fraction contract (SPEC 8.2, Task 6A), the same-strand
        # contract (SPEC 8.3, Task 6B) and the interval-relation
        # predicates contains/within (SPEC 8.4/8.5, Tasks 6C/6D) are all
        # applied by the shared post-filters below so both backends
        # enforce identical predicates. Candidate generation is always an
        # ordinary, unfiltered overlap ``intersect``.
        kwargs = {"wa": True, "wb": True}
        if how == "left":
            kwargs["loj"] = True

        # Backend failures MUST propagate (SPEC 9.2): a valid no-match is
        # not an exception and remains a valid empty result, but a backend
        # or conversion error must never be reported as "no matches".
        try:
            result = self._to_bed(coord_df, q_id).intersect(
                self._to_bed(annot_df, a_id), **kwargs
            )
            raw = result.to_dataframe(header=None, dtype=str)
        finally:
            pybedtools.cleanup()

        if raw.empty:
            # No exception was raised, so a 0-row raw result is a genuine
            # no-match (valid empty), not a swallowed backend error.
            if how == "left":
                return self._finalize(
                    self._unmatched_query_rows(
                        coord_df, annot_df, q_meta, a_meta,
                        list(range(len(coord_df))), q_id, a_id,
                    ),
                    coord_df, annot_df, q_id, a_id,
                )
            return pd.DataFrame()

        out = self._adapt_raw_rows(
            raw, coord_df, annot_df, q_meta, a_meta, q_id, a_id,
            expected_columns=2 * per_side,
        )

        # Canonical strand post-filter (SPEC 8.3, Task 6B): the shared
        # same-strand predicate, applied AFTER the backend match and
        # BEFORE left reconstruction, so a query whose matches all fail
        # the strand predicate is emitted exactly once as unmatched
        # (left mode) or omitted (inner mode). Unmatched (-loj sentinel)
        # rows pass through untouched. The predicate is identical for
        # both engines; it composes with min_overlap by logical AND.
        # Deliberately NOT mode-gated (unlike min_overlap, which SPEC
        # 8.2 defines for the overlap method only): SPEC 8.3 defines
        # strand relative to the *selected* interval predicate, so it
        # also applies to the contains mode (SPEC 8.4) and the within
        # mode (SPEC 8.5) (engine-contract section 10;
        # implementation-notes Task 6B "No mode gating").
        if self.use_strand:
            mask = strand_keep_mask(out, q_meta, a_meta)
            mask = mask | (out[a_id].to_numpy() < 0)
            out = out[mask].reset_index(drop=True)

        # Canonical interval-relation post-filter (SPEC 8.4 contains,
        # Task 6C; SPEC 8.5 within, Task 6D): the shared predicate
        # selected by ``mode``, applied AFTER the ordinary backend
        # overlap candidate generation and BEFORE left reconstruction.
        # Candidate generation is lossless because a containment pair in
        # either direction necessarily overlaps; the filter only removes
        # non-qualifying candidate rows. Both predicates are plain
        # boundary comparisons on canonical coordinates — never inferred
        # from an overlap fraction — and their conjunction with the
        # orthogonal strand predicate is a logical AND (the filter order
        # is therefore not observable). Unmatched (-loj sentinel) rows
        # pass through untouched, and a query losing every candidate is
        # emitted exactly once as unmatched by the left logic below.
        relation_mask = None
        if self.mode == "contains":
            relation_mask = contains_keep_mask(out)
        elif self.mode == "within":
            relation_mask = within_keep_mask(out)
        if relation_mask is not None:
            relation_mask = relation_mask | (out[a_id].to_numpy() < 0)
            out = out[relation_mask].reset_index(drop=True)

        # Canonical min_overlap post-filter (SPEC 8.2, Task 6A): the
        # shared query-fraction predicate, applied AFTER the backend
        # match and BEFORE left reconstruction, so a query whose matches
        # all fail the threshold is emitted exactly once as unmatched
        # (left mode) or omitted (inner mode). Unmatched (-loj sentinel)
        # rows pass through untouched. SPEC 8.2 is defined for the
        # overlap method, so the filter applies to overlap mode only;
        # the contains mode (SPEC 8.4) and the within mode (SPEC 8.5)
        # keep their own interval-relation predicates and are
        # deliberately exempt (Task 6A review finding; the contains
        # exemption is pinned by a Task 6C regression test and the within
        # exemption by a Task 6D regression test).
        if self.min_overlap is not None and self.mode == "overlap":
            mask = min_overlap_keep_mask(out, self.min_overlap)
            mask = mask | (out[a_id].to_numpy() < 0)
            out = out[mask].reset_index(drop=True)

        if how == "left":
            matched_ids = set(out[q_id].tolist())
            unmatched_positions = [
                i for i in range(len(coord_df)) if i not in matched_ids
            ]
            if unmatched_positions:
                out = pd.concat(
                    [
                        out,
                        self._unmatched_query_rows(
                            coord_df, annot_df, q_meta, a_meta,
                            unmatched_positions, q_id, a_id,
                        ),
                    ],
                    ignore_index=True,
                )

        return self._finalize(out, coord_df, annot_df, q_id, a_id)

    # ------------------------------------------------------------------
    # Raw-output adaptation (single explicit mapping path)
    # ------------------------------------------------------------------

    def _adapt_raw_rows(
        self,
        raw: pd.DataFrame,
        coord_df: pd.DataFrame,
        annot_df: pd.DataFrame,
        q_meta: List[str],
        a_meta: List[str],
        q_id: str,
        a_id: str,
        *,
        expected_columns: int,
    ) -> pd.DataFrame:
        """
        Map raw bedtools text output to canonical columns + row ids.

        The raw frame is the identity-only serialization (coordinates +
        internal row ids), always 4 columns per side — the sole layout
        in use (closest never serializes anything to bedtools; SPEC 8.6,
        Task 6E). Every published value is re-attached from the ORIGINAL
        input frames by row identity, so no user data is re-inferred
        from text and no backend sentinel can reach the output.
        """
        if raw.shape[1] != expected_columns:
            raise CanonicalSchemaError(
                "bedtools raw output has an unexpected column layout; "
                f"expected {expected_columns} columns (identity-only "
                "serialization: A chr/start/end/query row id, B "
                f"chr/start/end/annotation row id), got {raw.shape[1]}."
            )

        qid = self._parse_row_ids(raw.iloc[:, 3].to_numpy(), "query")
        aid_raw = raw.iloc[:, expected_columns - 1].to_numpy()
        # Structural match determination: the annotation row id is generated
        # by this engine, so '.' in this column can ONLY be a bedtools -loj
        # sentinel (unmatched); an integer means the matched annotation row.
        unmatched = aid_raw == "."
        aid = np.full(len(aid_raw), -1, dtype="int64")
        aid[~unmatched] = self._parse_row_ids(aid_raw[~unmatched], "annotation")

        # Deterministic canonical ordering by input row identity (never by
        # genomic coordinate): query input order, then annotation input
        # order; unmatched rows (a_id = -1) sit after their query's matches.
        order = np.lexsort((aid, qid))
        return self._build_result(
            coord_df, annot_df, q_meta, a_meta, qid[order], aid[order], q_id, a_id
        )

    def _build_result(
        self,
        coord_df: pd.DataFrame,
        annot_df: pd.DataFrame,
        q_meta: List[str],
        a_meta: List[str],
        qid: np.ndarray,
        aid: np.ndarray,
        q_id: str,
        a_id: str,
    ) -> pd.DataFrame:
        """
        Assemble canonical columns for the given (already ordered) rows.

        ``aid`` < 0 marks an unmatched row: every ``annot_*`` field is
        canonical missing and ``has_overlap`` is False. Values keep their
        original Python/numpy types (no re-inference of any kind).
        """
        out = pd.DataFrame(index=pd.RangeIndex(len(qid)))
        out["coord_chr"] = _values_at(coord_df, "chr", qid)
        out["coord_start"] = _values_at(coord_df, "start", qid).astype("int64")
        out["coord_end"] = _values_at(coord_df, "end", qid).astype("int64")
        for name in q_meta:
            out[f"coord_{name}"] = _values_at(coord_df, name, qid)
        out["annot_chr"] = _values_at(annot_df, "chr", aid)
        out["annot_start"] = _ints_at(annot_df, "start", aid)
        out["annot_end"] = _ints_at(annot_df, "end", aid)
        for name in a_meta:
            out[f"annot_{name}"] = _values_at(annot_df, name, aid)
        out[HAS_OVERLAP_COLUMN] = aid >= 0
        out[q_id] = qid
        out[a_id] = aid
        return out

    def _unmatched_query_rows(
        self,
        coord_df: pd.DataFrame,
        annot_df: pd.DataFrame,
        q_meta: List[str],
        a_meta: List[str],
        positions: List[int],
        q_id: str,
        a_id: str,
    ) -> pd.DataFrame:
        """
        One canonical unmatched row per query position (left mode).

        Annot fields are canonical missing; the row-identity columns carry
        the query position and a sentinel -1 annotation position.
        """
        qid = np.asarray(list(positions), dtype="int64")
        aid = np.full(len(qid), -1, dtype="int64")
        return self._build_result(
            coord_df, annot_df, q_meta, a_meta, qid, aid, q_id, a_id
        )

    def _finalize(
        self,
        out: pd.DataFrame,
        coord_df: pd.DataFrame,
        annot_df: pd.DataFrame,
        q_id: str,
        a_id: str,
    ) -> pd.DataFrame:
        """Deterministic canonical ordering + internal-column cleanup."""
        out = out.sort_values([q_id, a_id], kind="stable").reset_index(drop=True)
        out = out.drop(columns=[q_id, a_id])
        return out[list(canonical_result_columns(coord_df, annot_df))]

    # ------------------------------------------------------------------
    # Serialization / deserialization helpers (identity-only boundary)
    # ------------------------------------------------------------------

    def _to_bed(
        self, df: pd.DataFrame, row_id: str
    ) -> pybedtools.BedTool:
        """
        Identity-only serialization of a canonical interval table.

        Only coordinates and the internal row-identity column cross the
        bedtools text boundary; user metadata is re-attached from the
        original frame after matching (see ``_build_result``). There is
        deliberately no stranded variant: strand qualification is the
        shared canonical predicate (SPEC 8.3), and closest (SPEC 8.6)
        never serializes anything to bedtools.
        """
        bed_df = pd.DataFrame(
            {
                "chr": df["chr"].astype(str),
                "start": df["start"].astype("int64"),
                "end": df["end"].astype("int64"),
                row_id: np.arange(len(df), dtype="int64"),
            }
        )
        return pybedtools.BedTool.from_dataframe(bed_df)

    @staticmethod
    def _parse_row_ids(values: np.ndarray, side: str) -> np.ndarray:
        """Parse an internal row-id column; a broken round-trip is a schema error."""
        try:
            return np.asarray(values, dtype="int64")
        except (TypeError, ValueError) as exc:
            raise CanonicalSchemaError(
                f"bedtools raw output has a non-integer {side} row-id column; "
                "the identity-only serialization round-trip is broken"
            ) from exc

    @staticmethod
    def _metadata_columns(df: pd.DataFrame) -> List[str]:
        """Metadata columns: every column except the canonical core."""
        return [c for c in df.columns if c not in ("chr", "start", "end")]

    @staticmethod
    def _row_id_column(columns, preferred: str) -> str:
        """Collision-safe internal row-identity column name."""
        name = preferred
        suffix = 2
        while name in columns:
            name = f"{preferred}_{suffix}"
            suffix += 1
        return name


_PB_INTERVAL_COLUMNS = ("chrom", "start", "end")
_PB_SUFFIXES = ("_1", "_2")
_PB_QUERY_ROW_ID = "_pb_query_row_id"
_PB_ANNOT_ROW_ID = "_pb_annot_row_id"
_PB_Q_ID_COLUMN = "_pb_q_id"
_PB_A_ID_COLUMN = "_pb_a_id"


class PolarsBioEngine(AnnotationEngine):
    """
    High-performance engine using Polars and Polars-Bio (Rust backend)

    Canonical result contract (SPEC 4.2; docs/engine-contract.md 4-8):

    - Canonical inputs (0-based half-open ``chr``/``start``/``end`` plus
      metadata) are validated, converted to polars frames, and stamped
      with the per-frame coordinate-system metadata
      ``coordinate_system_zero_based=True`` so interval operations
      interpret the data as 0-based half-open. No process-global
      polars-bio option is read or mutated.
    - Stable per-row identity columns (collision-safe names, Int64) are
      added to both inputs before the backend call. They drive the
      deterministic canonical ordering (query input order, then
      annotation input order) and the left-mode reconstruction of
      unmatched queries, and they are removed before public output.
    - ``pb.overlap`` is invoked with explicit
      ``cols1``/``cols2`` and explicit suffixes. The raw backend output
      is mapped to the canonical ``coord_*``/``annot_*`` schema using
      the exact input schemas: provenance comes from input position,
      never from output suffix heuristics. A raw output whose columns do
      not match the expected mapping raises ``CanonicalSchemaError``
      instead of guessing.
    - ``min_overlap`` (Task 6A) is enforced with the SAME shared
      query-fraction predicate as BedtoolsEngine
      (``min_overlap_keep_mask``): pinned polars-bio 0.35.1 ``overlap``
      exposes no fraction mechanism, so the AnnotateR contract (SPEC
      8.2) is applied as a post-filter over the ordinary overlap pairs,
      before left reconstruction.
    - ``use_strand=True`` (Task 6B) is enforced with the SAME shared
      same-strand predicate as BedtoolsEngine (``strand_keep_mask``):
      pinned polars-bio 0.35.1 ``overlap`` exposes no strand option, so
      the AnnotateR contract (SPEC 8.3) is applied as a post-filter over
      the ordinary overlap pairs, after matching and before left
      reconstruction.
    - ``mode="contains"`` (Task 6C, SPEC 8.4) means the QUERY interval
      fully contains the ANNOTATION interval. Pinned polars-bio 0.35.1
      exposes no query-contains-annotation primitive, so the same
      architecture is used as for ``min_overlap``/``use_strand``:
      ordinary ``pb.overlap`` candidate pairs (containment implies
      overlap) plus the shared canonical predicate
      ``contains_keep_mask``, applied after matching and before left
      reconstruction. ``min_overlap`` is NOT applied in contains mode.
    - ``mode="within"`` (Task 6D, SPEC 8.5) is the directional inverse
      of ``contains``: the ANNOTATION interval fully contains the QUERY
      interval. Pinned polars-bio 0.35.1 exposes no containment primitive
      at all (only ``overlap``/``nearest``/coverage/count operations),
      so ordinary ``pb.overlap`` candidates plus the shared canonical
      predicate ``within_keep_mask`` are used, after matching and before
      left reconstruction. ``min_overlap`` is NOT applied in within mode.
    - ``mode="closest"`` (Task 6E, SPEC 8.6) is ONE backend-independent
      operation: the engine delegates to the SAME shared canonical
      ``canonical_closest`` selection as BedtoolsEngine — same rows,
      same canonical distance, same ties, same ordering BY
      CONSTRUCTION. Pinned polars-bio 0.35.1 ``nearest`` is
      deliberately NOT used: its ``k=1`` default drops tied nearest
      rows (verified: a symmetric distance-5 tie returns 1 of 2 rows),
      it exposes no strand option at all, and its native ``distance``
      column is non-normative for the contract — canonical distance is
      recomputed by the shared ``interval_distance`` instead. (Its
      observed native gap convention happens to match the canonical
      formula; bedtools ``-d`` does not — neither defines the contract.)
    - Backend exceptions propagate to the caller. A valid no-match is
      not an exception: it remains a valid empty (0-row) result. (Closest
      makes no backend call; its only failure mode is explicit input
      validation.)
    """

    def intersect(
        self,
        coord_df: pd.DataFrame,
        annot_df: pd.DataFrame,
        how: Literal["inner", "left"] = "inner"
    ) -> pd.DataFrame:
        """Intersect canonical interval tables and return canonical results."""
        # Engine inputs MUST be canonical (SPEC 4.2): fail explicitly on
        # malformed input instead of returning a silent empty result.
        validate_canonical_interval_table(coord_df)
        validate_canonical_interval_table(annot_df)

        if self.mode in ("overlap", "contains", "within"):
            # ``contains`` (SPEC 8.4, Task 6C) and ``within`` (SPEC 8.5,
            # Task 6D) share the ordinary overlap candidate generation (a
            # containment pair in either direction implies overlap, so
            # this is lossless and never a Cartesian product); the shared
            # canonical interval-relation predicate selected by ``mode``
            # is applied inside ``_adapt_overlap_result``. how is
            # respected for left mode.
            return self._overlap(coord_df, annot_df, how)
        if self.mode == "closest":
            # ``closest`` (SPEC 8.6, Task 6E) is ONE backend-independent
            # operation: both engines delegate to the shared canonical
            # selection ``canonical_closest`` (same-chromosome,
            # strand-before-nearest, canonical ``interval_distance``,
            # all ties, left reconstruction). pb.nearest — including its
            # ``k=1`` tie loss and native ``distance`` column — is never
            # invoked.
            return canonical_closest(
                coord_df, annot_df, how=how, use_strand=self.use_strand
            )
        raise ValueError(f"Unknown mode: {self.mode}")

    # ------------------------------------------------------------------
    # Overlap (inner + left)
    # ------------------------------------------------------------------

    def _overlap(self, coord_df: pd.DataFrame, annot_df: pd.DataFrame, how: str) -> pd.DataFrame:
        q_meta = self._metadata_columns(coord_df)
        a_meta = self._metadata_columns(annot_df)
        q_id = self._row_id_column(coord_df.columns, _PB_QUERY_ROW_ID)
        a_id = self._row_id_column(annot_df.columns, _PB_ANNOT_ROW_ID)
        q_frame = self._prepare_backend_frame(coord_df, q_id)
        a_frame = self._prepare_backend_frame(annot_df, a_id)

        logger.debug("Running pb.overlap on %d x %d rows", len(coord_df), len(annot_df))
        # Backend failures MUST propagate (SPEC 9.2): a valid no-match is
        # not an exception and remains a valid empty (0-row) result, but a
        # backend error must never be reported as "no matches".
        raw = pb.overlap(
            q_frame,
            a_frame,
            suffixes=_PB_SUFFIXES,
            cols1=list(_PB_INTERVAL_COLUMNS),
            cols2=list(_PB_INTERVAL_COLUMNS),
            output_type="polars.DataFrame",
        )

        return self._adapt_overlap_result(raw, coord_df, annot_df, how)

    def _adapt_overlap_result(
        self,
        raw: pl.DataFrame,
        coord_df: pd.DataFrame,
        annot_df: pd.DataFrame,
        how: str,
    ) -> pd.DataFrame:
        """Map raw pb.overlap output to the canonical result schema."""
        q_meta = self._metadata_columns(coord_df)
        a_meta = self._metadata_columns(annot_df)
        q_id = self._row_id_column(coord_df.columns, _PB_QUERY_ROW_ID)
        a_id = self._row_id_column(annot_df.columns, _PB_ANNOT_ROW_ID)
        rename, expected = self._canonical_rename_map(q_meta, a_meta, q_id, a_id)

        # Empty raw result: no exception was raised, so this is a genuine
        # no-match (a valid empty result), not a swallowed backend error.
        if raw.is_empty():
            if how == "left" and len(coord_df) > 0:
                unmatched = self._unmatched_query_rows(
                    coord_df, q_meta, a_meta, list(range(len(coord_df)))
                )
                return unmatched[list(canonical_result_columns(coord_df, annot_df))]
            return pd.DataFrame()

        df = raw.to_pandas()
        missing = [c for c in expected if c not in df.columns]
        unexpected = [c for c in df.columns if c not in expected]
        if missing or unexpected:
            raise CanonicalSchemaError(
                "polars-bio raw output columns do not match the expected "
                "suffixed mapping; column provenance cannot be determined "
                f"explicitly. missing={missing}, unexpected={unexpected}"
            )
        df = df.rename(columns=rename)

        # Canonical strand post-filter (SPEC 8.3, Task 6B) — the same
        # shared predicate as BedtoolsEngine: pinned polars-bio 0.35.1
        # ``overlap`` has no strand option, so the same-strand contract
        # is applied post-hoc. Every raw pb.overlap row is a matched
        # pair, so the mask applies to all rows; queries losing every
        # match are reconstructed as unmatched below (left mode). It
        # composes with min_overlap by logical AND. Deliberately NOT
        # mode-gated (unlike min_overlap below): SPEC 8.3 defines
        # strand relative to the *selected* interval predicate, so it
        # also applies to the contains mode (SPEC 8.4) and the within
        # mode (SPEC 8.5) (engine-contract section 10;
        # implementation-notes Task 6B "No mode gating").
        if self.use_strand:
            df = df[strand_keep_mask(df, q_meta, a_meta)].reset_index(drop=True)

        # Canonical interval-relation post-filter (SPEC 8.4 contains,
        # Task 6C; SPEC 8.5 within, Task 6D) — the same shared predicate
        # as BedtoolsEngine, applied over the ordinary pb.overlap
        # candidate pairs. Both predicates are plain boundary comparisons
        # on canonical coordinates, never inferred from an overlap
        # fraction, and their conjunction with the orthogonal strand
        # predicate is a logical AND (the filter order is therefore not
        # observable). Every raw row is a matched pair, so the mask
        # applies to all rows; queries losing every candidate are
        # reconstructed as unmatched below (left mode).
        if self.mode == "contains":
            df = df[contains_keep_mask(df)].reset_index(drop=True)
        elif self.mode == "within":
            df = df[within_keep_mask(df)].reset_index(drop=True)

        # Canonical min_overlap post-filter (SPEC 8.2, Task 6A) — the
        # same shared predicate as BedtoolsEngine. Every raw pb.overlap
        # row is a matched pair, so the mask applies to all rows;
        # queries losing every match are reconstructed as unmatched
        # below (left mode). SPEC 8.2 is defined for the overlap method,
        # so the filter applies to overlap mode only; the contains mode
        # (SPEC 8.4) and the within mode (SPEC 8.5) keep their own
        # interval-relation predicates and are deliberately exempt (Task
        # 6A review finding; the contains exemption is pinned by a Task
        # 6C test and the within exemption by a Task 6D test).
        if self.min_overlap is not None and self.mode == "overlap":
            df = df[min_overlap_keep_mask(df, self.min_overlap)].reset_index(drop=True)

        # Deterministic canonical ordering by input row identity (never by
        # genomic coordinate): query input order, then annotation input order.
        df = df.sort_values([_PB_Q_ID_COLUMN, _PB_A_ID_COLUMN], kind="stable")
        df[HAS_OVERLAP_COLUMN] = True

        if how == "left":
            matched_ids = set(df[_PB_Q_ID_COLUMN].tolist())
            unmatched_positions = [
                i for i in range(len(coord_df)) if i not in matched_ids
            ]
            if unmatched_positions:
                unmatched = self._unmatched_query_rows(
                    coord_df, q_meta, a_meta, unmatched_positions
                )
                df = pd.concat([df, unmatched], ignore_index=True)
                df = df.sort_values([_PB_Q_ID_COLUMN, _PB_A_ID_COLUMN], kind="stable")

        df = df.drop(columns=[_PB_Q_ID_COLUMN, _PB_A_ID_COLUMN])
        return df[list(canonical_result_columns(coord_df, annot_df))]

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _metadata_columns(df: pd.DataFrame) -> List[str]:
        """Metadata columns: every column except the canonical core."""
        return [c for c in df.columns if c not in ("chr", "start", "end")]

    @staticmethod
    def _row_id_column(columns, preferred: str) -> str:
        """Collision-safe internal row-identity column name."""
        name = preferred
        suffix = 2
        while name in columns:
            name = f"{preferred}_{suffix}"
            suffix += 1
        return name

    @staticmethod
    def _prepare_backend_frame(df: pd.DataFrame, row_id: str) -> pl.DataFrame:
        """
        Convert a canonical pandas table into a polars-bio backend frame.

        - renames ``chr`` to polars-bio's documented interval column name
          ``chrom``;
        - casts core columns to the documented dtypes;
        - appends a stable positional row-identity column (Int64);
        - stamps the per-frame coordinate-system metadata (0-based,
          half-open) so polars-bio operations interpret intervals
          half-open without any process-global option state.
        """
        frame = pl.from_pandas(df)
        frame = frame.rename({"chr": "chrom"})
        frame = frame.with_columns([
            pl.col("chrom").cast(pl.Utf8),
            pl.col("start").cast(pl.Int64),
            pl.col("end").cast(pl.Int64),
        ])
        frame = frame.with_row_index(row_id)
        frame = frame.with_columns(pl.col(row_id).cast(pl.Int64))
        frame.config_meta.set(coordinate_system_zero_based=True)
        return frame

    @staticmethod
    def _canonical_rename_map(q_meta, a_meta, q_id, a_id):
        """
        Explicit raw-output rename map derived from the input schemas.

        Returns (rename_dict, expected_raw_column_set). Provenance is
        defined by input position (which columns came from which input),
        never by output suffix heuristics.
        """
        s1, s2 = _PB_SUFFIXES
        rename = {
            f"chrom{s1}": "coord_chr",
            f"start{s1}": "coord_start",
            f"end{s1}": "coord_end",
            f"chrom{s2}": "annot_chr",
            f"start{s2}": "annot_start",
            f"end{s2}": "annot_end",
            f"{q_id}{s1}": _PB_Q_ID_COLUMN,
            f"{a_id}{s2}": _PB_A_ID_COLUMN,
        }
        for column in q_meta:
            rename[f"{column}{s1}"] = f"coord_{column}"
        for column in a_meta:
            rename[f"{column}{s2}"] = f"annot_{column}"
        return rename, set(rename)

    @staticmethod
    def _unmatched_query_rows(
        coord_df: pd.DataFrame, q_meta, a_meta, positions
    ) -> pd.DataFrame:
        """
        One canonical unmatched row per query position (left mode).

        Annot fields are the canonical missing value; the row-identity
        columns carry the query position and a sentinel -1 annotation
        position.
        """
        n = len(positions)
        sub = coord_df.iloc[positions]
        out = pd.DataFrame({
            "coord_chr": sub["chr"].to_numpy(),
            "coord_start": sub["start"].astype("int64").to_numpy(),
            "coord_end": sub["end"].astype("int64").to_numpy(),
        })
        for column in q_meta:
            out[f"coord_{column}"] = sub[column].to_numpy()
        out["annot_chr"] = pd.array([CANONICAL_MISSING] * n, dtype=object)
        out["annot_start"] = pd.array([CANONICAL_MISSING] * n, dtype="Int64")
        out["annot_end"] = pd.array([CANONICAL_MISSING] * n, dtype="Int64")
        for column in a_meta:
            out[f"annot_{column}"] = pd.array([CANONICAL_MISSING] * n, dtype=object)
        out[HAS_OVERLAP_COLUMN] = False
        out[_PB_Q_ID_COLUMN] = np.asarray(positions, dtype="int64")
        out[_PB_A_ID_COLUMN] = np.full(n, -1, dtype="int64")
        return out

def get_summary_stats(result_df: pd.DataFrame, coord_df: pd.DataFrame) -> Dict:
    """
    Generate summary statistics about annotation results
    (Standalone function now, or static method)
    """
    if result_df.empty:
        return {
            "total_coordinates": len(coord_df),
            "annotated_coordinates": 0,
            "total_annotations": 0,
            "unique_chromosomes": 0,
            "annotation_rate": 0.0
        }
    
    return {
        "total_coordinates": len(coord_df),
        "annotated_coordinates": result_df['coord_chr'].nunique() if 'coord_chr' in result_df.columns else len(result_df),
        "total_annotations": len(result_df),
        "unique_chromosomes": result_df['coord_chr'].nunique() if 'coord_chr' in result_df.columns else 0,
        "annotation_rate": len(result_df) / len(coord_df) if len(coord_df) > 0 else 0.0
    }


class ProgressiveAnnotator:
    """
    Annotate large files in chunks with progress tracking
    """
    
    def __init__(self, chunk_size: int = 100000):
        """
        Initialize progressive annotator
        
        Args:
            chunk_size: Number of rows to process at once
        """
        self.chunk_size = chunk_size
    
    def annotate_large_file(
        self,
        coord_file: str,
        annot_df: pd.DataFrame,
        engine: AnnotationEngine,
        progress_callback: Optional[callable] = None
    ) -> pd.DataFrame:
        """
        Annotate a large coordinate file in chunks
        
        Args:
            coord_file: Path to coordinate file
            annot_df: Annotation DataFrame
            engine: AnnotationEngine instance
            progress_callback: Function to call with progress (0.0 to 1.0)
            
        Returns:
            Complete annotated DataFrame
        """
        results = []
        
        # Read file in chunks
        chunks = pd.read_csv(coord_file, sep='\t', chunksize=self.chunk_size)
        
        total_chunks = sum(1 for _ in pd.read_csv(coord_file, sep='\t', chunksize=self.chunk_size))
        
        for i, chunk in enumerate(chunks):
            # Annotate chunk
            result = engine.intersect(chunk, annot_df)
            results.append(result)
            
            # Report progress
            if progress_callback:
                progress = (i + 1) / total_chunks
                progress_callback(progress)
        
        # Combine results
        return pd.concat(results, ignore_index=True)
