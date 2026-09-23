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
#: <row id>.
_BT_COLUMNS_PER_SIDE = 4
#: When the non-normative closest placeholder runs with ``use_strand``,
#: bedtools ``-s`` requires a strand in column 6, so that path
#: additionally carries a placeholder score column and an explicit strand
#: column (chr, start, end, <row id>, ".", strand). The overlap path
#: NEVER uses the stranded layout: strand qualification is the shared
#: canonical post-filter (SPEC 8.3, Task 6B).
_BT_COLUMNS_PER_SIDE_STRANDED = 6


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
      missing/unknown strand is not a wildcard. (The stranded
      serialization + native ``-s`` remain only in the non-normative
      closest placeholder, unchanged by Task 6B.)
    - ``min_overlap`` (Task 6A) is NOT forwarded to bedtools ``-f``:
      the canonical query-fraction contract (SPEC 8.2) is applied as
      the shared post-filter ``min_overlap_keep_mask`` over ordinary
      overlap pairs, after matching and before left reconstruction.
      ``-f``/``-F`` remain available internally only for the
      non-normative contains/within placeholders; note bedtools itself
      rejects ``-f 0.0`` (its range is ``(0.0, 1.0]``), so a native
      mapping could not even express the valid no-op threshold ``0``.
    - Backend and conversion exceptions propagate to the caller. A 0-row
      result with no exception is a genuine no-match (a valid empty
      result), never a swallowed failure (SPEC 9.2).
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

        if self.mode == "overlap":
            return self._overlap(coord_df, annot_df, how)
        if self.mode in ("contains", "within"):
            # Non-normative placeholder mapping (engine-contract section
            # 11): -f 1.0 / -F 1.0 as before; the exact contains/within
            # contract is fixed in Task 6 and is deliberately not touched
            # here.
            fraction_kwarg = "f" if self.mode == "contains" else "F"
            return self._overlap(
                coord_df, annot_df, how="inner", **{fraction_kwarg: 1.0}
            )
        if self.mode == "closest":
            return self._closest(coord_df, annot_df)
        raise ValueError(f"Unknown mode: {self.mode}")

    # ------------------------------------------------------------------
    # Overlap (inner + left) and contains/within placeholders
    # ------------------------------------------------------------------

    def _overlap(
        self,
        coord_df: pd.DataFrame,
        annot_df: pd.DataFrame,
        how: str,
        *,
        f: Optional[float] = None,
        F: Optional[float] = None,
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
        # min_overlap is deliberately NOT forwarded to bedtools -f, and
        # use_strand is deliberately NOT forwarded to bedtools -s: the
        # canonical query-fraction contract (SPEC 8.2, Task 6A) and the
        # same-strand contract (SPEC 8.3, Task 6B) are applied by the
        # shared post-filters below so both backends enforce identical
        # predicates. Explicit f/F kwargs remain only for the
        # non-normative contains/within placeholders.
        kwargs = {"wa": True, "wb": True}
        if f is not None:
            kwargs["f"] = f
        if F is not None:
            kwargs["F"] = F
        if how == "left":
            kwargs["loj"] = True

        # Backend failures MUST propagate (SPEC 9.2): a valid no-match is
        # not an exception and remains a valid empty result, but a backend
        # or conversion error must never be reported as "no matches".
        try:
            result = self._to_bed(coord_df, q_id, stranded=False).intersect(
                self._to_bed(annot_df, a_id, stranded=False), **kwargs
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
        # also applies to the non-normative contains/within placeholder
        # paths (engine-contract section 10; implementation-notes
        # Task 6B "No mode gating").
        if self.use_strand:
            mask = strand_keep_mask(out, q_meta, a_meta)
            mask = mask | (out[a_id].to_numpy() < 0)
            out = out[mask].reset_index(drop=True)

        # Canonical min_overlap post-filter (SPEC 8.2, Task 6A): the
        # shared query-fraction predicate, applied AFTER the backend
        # match and BEFORE left reconstruction, so a query whose matches
        # all fail the threshold is emitted exactly once as unmatched
        # (left mode) or omitted (inner mode). Unmatched (-loj sentinel)
        # rows pass through untouched. SPEC 8.2 is defined for the
        # overlap method, so the filter applies to overlap mode only;
        # the non-normative contains/within placeholders keep their
        # pre-Task-6A behavior (Task 6A review finding).
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
    # Closest (non-normative; layout adaptation only — Task 6)
    # ------------------------------------------------------------------

    def _closest(self, coord_df: pd.DataFrame, annot_df: pd.DataFrame) -> pd.DataFrame:
        q_meta = self._metadata_columns(coord_df)
        a_meta = self._metadata_columns(annot_df)
        q_id = self._row_id_column(coord_df.columns, _BT_QUERY_ROW_ID)
        a_id = self._row_id_column(annot_df.columns, _BT_ANNOT_ROW_ID)

        # closest (t="first") emits one row per query; with either input
        # empty there is no deterministic result to emit.
        if len(coord_df) == 0 or len(annot_df) == 0:
            return pd.DataFrame()

        per_side = (
            _BT_COLUMNS_PER_SIDE_STRANDED if self.use_strand else _BT_COLUMNS_PER_SIDE
        )
        logger.debug(
            "Running bedtools closest on %d x %d rows",
            len(coord_df), len(annot_df),
        )
        # Backend failures MUST propagate (SPEC 9.2), same principle as
        # overlap. Closest is the non-normative placeholder (Task 6E
        # scope): its native ``-s`` forwarding is unchanged by Task 6B.
        try:
            result = self._to_bed(coord_df, q_id, stranded=self.use_strand).closest(
                self._to_bed(annot_df, a_id, stranded=self.use_strand),
                d=True, t="first", s=self.use_strand,
            )
            raw = result.to_dataframe(header=None, dtype=str)
        finally:
            pybedtools.cleanup()

        if raw.empty:
            return pd.DataFrame()
        expected_columns = 2 * per_side + 1  # + trailing distance column
        if raw.shape[1] != expected_columns:
            raise CanonicalSchemaError(
                "bedtools raw closest output has an unexpected column layout; "
                f"expected {expected_columns} columns (A coordinates + "
                "query row id, B coordinates + annotation row id, distance), "
                f"got {raw.shape[1]}."
            )

        qid = self._parse_row_ids(raw.iloc[:, 3].to_numpy(), "query")
        aid_raw = raw.iloc[:, expected_columns - 2].to_numpy()
        # Structural match determination, same rule as overlap: '.' in the
        # internal annotation row-id column is only ever a bedtools
        # sentinel (no nearest feature found).
        unmatched = aid_raw == "."
        aid = np.full(len(aid_raw), -1, dtype="int64")
        aid[~unmatched] = self._parse_row_ids(aid_raw[~unmatched], "annotation")

        # One row per query; order by query input position.
        order = np.argsort(qid, kind="stable")
        distance = pd.array([pd.NA] * len(aid), dtype="Int64")
        for i in np.where(aid >= 0)[0]:
            try:
                distance[i] = int(raw.iloc[i, expected_columns - 1])
            except ValueError as exc:
                raise CanonicalSchemaError(
                    f"bedtools closest distance column is not an integer "
                    f"(row {i}): {raw.iloc[i, 8]!r}"
                ) from exc

        out = self._build_result(
            coord_df, annot_df, q_meta, a_meta, qid[order], aid[order], q_id, a_id
        )
        out["distance"] = distance[order]
        columns = list(canonical_result_columns(coord_df, annot_df)) + ["distance"]
        return out[columns]

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
        internal row ids), always 4 columns per side on the overlap path;
        the stranded 6-column layout exists only in the non-normative
        closest placeholder and is not parsed here. Every published value is re-attached from
        the ORIGINAL input frames by row identity, so no user data is
        re-inferred from text and no backend sentinel can reach the output.
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
        out["coord_chr"] = self._values_from(coord_df, "chr", qid)
        out["coord_start"] = self._values_from(coord_df, "start", qid).astype("int64")
        out["coord_end"] = self._values_from(coord_df, "end", qid).astype("int64")
        for name in q_meta:
            out[f"coord_{name}"] = self._values_from(coord_df, name, qid)
        out["annot_chr"] = self._values_from(annot_df, "chr", aid)
        out["annot_start"] = self._nullable_int_values(annot_df, "start", aid)
        out["annot_end"] = self._nullable_int_values(annot_df, "end", aid)
        for name in a_meta:
            out[f"annot_{name}"] = self._values_from(annot_df, name, aid)
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
        self, df: pd.DataFrame, row_id: str, *, stranded: bool
    ) -> pybedtools.BedTool:
        """
        Identity-only serialization of a canonical interval table.

        Only coordinates and the internal row-identity column cross the
        bedtools text boundary; user metadata is re-attached from the
        original frame after matching (see ``_build_result``). With
        ``stranded=True`` (only the non-normative closest placeholder
        requests this), bedtools ``-s`` additionally requires column 6:
        a placeholder score plus an explicit strand column (user
        ``strand`` metadata when present, else "." = unstranded).
        """
        bed_df = pd.DataFrame(
            {
                "chr": df["chr"].astype(str),
                "start": df["start"].astype("int64"),
                "end": df["end"].astype("int64"),
                row_id: np.arange(len(df), dtype="int64"),
            }
        )
        if stranded:
            bed_df["score"] = "."
            if "strand" in df.columns:
                strand = df["strand"]
                bed_df["strand"] = strand.where(strand.notna(), ".").astype(str)
            else:
                bed_df["strand"] = "."
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
    def _python_scalar(value):
        """Reduce numpy scalar types to their Python equivalents.

        The canonicalizer publishes object-dtype metadata columns built
        via ``astype(object)`` (Python ``int``/``float``/``bool``), so the
        adapter must emit the same scalar types for identical input values.
        """
        if isinstance(value, np.bool_):
            return bool(value)
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            return float(value)
        return value

    @staticmethod
    def _values_from(df: pd.DataFrame, column: str, row_ids: np.ndarray) -> np.ndarray:
        """
        Original values of ``df[column]`` at positional ``row_ids``.

        Missing input values become canonical missing (``pd.NA``); a row id
        of -1 (unmatched row) is always canonical missing. Values keep
        their original semantic type (numpy scalars are reduced to the
        equivalent Python scalars, mirroring the canonicalizer's
        object-dtype publication) — no value or dtype re-inference.
        """
        series = df[column]
        values = series.to_numpy()
        missing = series.isna().to_numpy()
        out = np.full(len(row_ids), pd.NA, dtype=object)
        valid = row_ids >= 0
        rv = row_ids[valid]
        out[valid] = [
            pd.NA if m else BedtoolsEngine._python_scalar(v)
            for m, v in zip(missing[rv], values[rv])
        ]
        return out

    @staticmethod
    def _nullable_int_values(df: pd.DataFrame, column: str, row_ids: np.ndarray):
        """Integer coordinate values at ``row_ids``; -1 (unmatched) -> pd.NA."""
        values = df[column].to_numpy()
        out = pd.array([pd.NA] * len(row_ids), dtype="Int64")
        for i, rid in enumerate(row_ids):
            if rid >= 0:
                out[i] = int(values[rid])
        return out

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
    - ``pb.overlap`` / ``pb.nearest`` are invoked with explicit
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
    - Backend exceptions propagate to the caller. A valid no-match is
      not an exception: it remains a valid empty (0-row) result.
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

        if self.mode == "overlap":
            return self._overlap(coord_df, annot_df, how)
        if self.mode == "closest":
            return self._nearest(coord_df, annot_df)
        if self.mode in ("contains", "within"):
            # Non-normative placeholder mapping (engine-contract 9/11):
            # plain overlap for now; _filter_fraction is a documented no-op.
            return self._filter_fraction(
                self._overlap(coord_df, annot_df, how), mode=self.mode
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
        # also applies to the non-normative contains/within placeholder
        # paths (engine-contract section 10; implementation-notes
        # Task 6B "No mode gating").
        if self.use_strand:
            df = df[strand_keep_mask(df, q_meta, a_meta)].reset_index(drop=True)

        # Canonical min_overlap post-filter (SPEC 8.2, Task 6A) — the
        # same shared predicate as BedtoolsEngine. Every raw pb.overlap
        # row is a matched pair, so the mask applies to all rows;
        # queries losing every match are reconstructed as unmatched
        # below (left mode). SPEC 8.2 is defined for the overlap method,
        # so the filter applies to overlap mode only; the non-normative
        # contains/within placeholders keep their pre-Task-6A behavior
        # (Task 6A review finding).
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
    # Closest (non-normative)
    # ------------------------------------------------------------------

    def _nearest(self, coord_df: pd.DataFrame, annot_df: pd.DataFrame) -> pd.DataFrame:
        q_meta = self._metadata_columns(coord_df)
        a_meta = self._metadata_columns(annot_df)
        q_id = self._row_id_column(coord_df.columns, _PB_QUERY_ROW_ID)
        a_id = self._row_id_column(annot_df.columns, _PB_ANNOT_ROW_ID)
        q_frame = self._prepare_backend_frame(coord_df, q_id)
        a_frame = self._prepare_backend_frame(annot_df, a_id)

        logger.debug("Running pb.nearest on %d x %d rows", len(coord_df), len(annot_df))
        # Backend failures MUST propagate (SPEC 9.2), same principle as
        # overlap: a valid no-match is a valid empty result, but a backend
        # exception must never be reported as "no matches".
        raw = pb.nearest(
            q_frame,
            a_frame,
            suffixes=_PB_SUFFIXES,
            cols1=list(_PB_INTERVAL_COLUMNS),
            cols2=list(_PB_INTERVAL_COLUMNS),
            output_type="polars.DataFrame",
        )

        if raw.is_empty():
            return pd.DataFrame()

        rename, expected = self._canonical_rename_map(q_meta, a_meta, q_id, a_id)
        df = raw.to_pandas()
        missing = [c for c in expected if c not in df.columns]
        # pb.nearest additionally emits an unsuffixed "distance" column.
        unexpected = [c for c in df.columns if c not in expected and c != "distance"]
        if missing or unexpected:
            raise CanonicalSchemaError(
                "polars-bio raw nearest output columns do not match the "
                "expected suffixed mapping; column provenance cannot be "
                f"determined explicitly. missing={missing}, unexpected={unexpected}"
            )
        df = df.rename(columns=rename)

        # When no annotation exists, pb.nearest still emits one row per
        # query with ALL annotation fields null (k=1, no neighbor). Those
        # rows do not represent a real match; drop them so closest mode
        # with an empty annotation table returns a genuinely empty result
        # (SPEC 9.2: a valid empty, not phantom "nearest" hits).
        df = df[df[_PB_A_ID_COLUMN].notna()].reset_index(drop=True)
        if df.empty:
            return pd.DataFrame()

        # One row per query row (k=1); order by query input position.
        df = df.sort_values(_PB_Q_ID_COLUMN, kind="stable")
        df[HAS_OVERLAP_COLUMN] = True
        df = df.drop(columns=[_PB_Q_ID_COLUMN, _PB_A_ID_COLUMN])
        columns = list(canonical_result_columns(coord_df, annot_df))
        if "distance" in df.columns:
            columns.append("distance")
        return df[columns]

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _filter_fraction(self, res: pd.DataFrame, mode: str) -> pd.DataFrame:
        # Non-normative contains/within placeholder (engine-contract 9/11):
        # no fractional filtering is applied yet; pass through unchanged.
        return res

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
