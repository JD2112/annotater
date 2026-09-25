"""
Canonical schema contract for AnnotateR (PLAN Task 2)

This module is the single place where the canonical representation of
genomic intervals and annotation results is defined.

Canonical interval table (the normalized input consumed by every engine)
--------------------------------------------------------------------------

- ``chr``    chromosome, string
- ``start``  integer, 0-based inclusive
- ``end``    integer, 0-based exclusive (half-open ``[start, end)``)
- ``strand`` optional; ``'+'`` / ``'-'`` or canonical missing (``pd.NA``)
- any number of metadata columns, keeping their source names

Valid interval: ``start >= 0`` and ``end > start``.

Canonical annotation result (the public output contract)
---------------------------------------------------------

- core columns::

    coord_chr coord_start coord_end
    annot_chr annot_start annot_end
    has_overlap

- metadata preserved with explicit provenance as
  ``coord_<original_name>`` / ``annot_<original_name>``
- deterministic column order: coord core, coord metadata (input order),
  annot core, annot metadata (input order), ``has_overlap`` last
- missing values are dataframe-native missing (``pd.NA``); backend
  sentinels such as ``"."`` or ``"-1"`` are normalized away on unmatched
  rows and must never appear in public output
- matched rows (``has_overlap=True``) must carry a valid canonical
  annotation interval; malformed matched coordinates are rejected rather
  than coerced to missing
- ``has_overlap`` is boolean
- duplicated input rows are preserved, never collapsed

Deterministic row-order policy
------------------------------

Results must be ordered by original query row order, then by original
annotation row order within each query; an unmatched query row appears
exactly once at its own query position (left-join order). The engine
layer is responsible for emitting rows in this order; ``canonicalize_
annotation_result`` preserves the order it receives and enforces the
column/missing-value/type contract. Enforcing the ordering through
internal row identity is part of the Task 4/5 engine adapters.

External-library column suffixes (``_1``, ``_2``, ``_right``) are backend
intermediates and must never appear in canonical output; the canonical
result enforces the exact expected column set, so any leaked suffix
column is rejected.
"""

from __future__ import annotations

from typing import Iterable, Tuple

import pandas as pd

#: Reserved core columns of a canonical interval table.
INTERVAL_COLUMNS = ("chr", "start", "end")

#: Optional canonical strand column.
STRAND_COLUMN = "strand"

#: Values accepted in the canonical strand column (otherwise missing).
STRAND_VALUES = ("+", "-")

#: Prefixes reserved for canonical result provenance. Source metadata
#: columns may not use them, because result provenance is unambiguous
#: only when a ``coord_*``/``annot_*`` name can come from one input only.
RESERVED_RESULT_PREFIXES = ("coord_", "annot_")

#: Canonical missing-value representation (dataframe-native).
CANONICAL_MISSING = pd.NA

CANONICAL_RESULT_COORD_CORE = ("coord_chr", "coord_start", "coord_end")
CANONICAL_RESULT_ANNOT_CORE = ("annot_chr", "annot_start", "annot_end")
HAS_OVERLAP_COLUMN = "has_overlap"


class CanonicalSchemaError(Exception):
    """Data does not conform to the canonical schema contract."""


class InvalidIntervalError(CanonicalSchemaError):
    """Interval coordinates violate the canonical invariants."""


class MalformedFileError(CanonicalSchemaError):
    """A source file contains structurally invalid records."""


def interval_metadata_columns(df: pd.DataFrame) -> list:
    """
    Metadata columns of an interval table.

    Everything except the reserved coordinate keys ``chr``/``start``/
    ``end``; this includes ``strand`` when present, so that it is carried
    through results with explicit provenance (``coord_strand``/
    ``annot_strand``).
    """
    return [c for c in df.columns if c not in INTERVAL_COLUMNS]


def _require_integer_series(series: pd.Series, column: str, df: pd.DataFrame) -> pd.Series:
    """Return ``series`` as int64 or raise ``InvalidIntervalError``."""
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.isna().any():
        rows = df.index[numeric.isna()].tolist()
        raise InvalidIntervalError(
            f"'{column}' must be integer-valued; invalid value at row(s) {rows[:5]}"
        )
    if not (numeric == numeric.round()).all():
        rows = df.index[numeric != numeric.round()].tolist()
        raise InvalidIntervalError(
            f"'{column}' must be integer-valued; non-integer at row(s) {rows[:5]}"
        )
    return numeric.astype("int64")


def validate_canonical_interval_table(df: pd.DataFrame) -> None:
    """
    Validate a canonical interval table.

    Raises ``CanonicalSchemaError``/``InvalidIntervalError`` on any
    contract violation; returns ``None`` when the table is canonical.
    """
    missing = [c for c in INTERVAL_COLUMNS if c not in df.columns]
    if missing:
        raise CanonicalSchemaError(
            f"canonical interval table is missing required column(s): {missing}"
        )
    if df["chr"].isna().any():
        raise InvalidIntervalError("chromosome values must be present on every row")
    start = _require_integer_series(df["start"], "start", df)
    end = _require_integer_series(df["end"], "end", df)
    if (start < 0).any():
        rows = df.index[start < 0].tolist()
        raise InvalidIntervalError(
            f"canonical start must be >= 0; violated at row(s) {rows[:5]}"
        )
    if not (end > start).all():
        rows = df.index[end <= start].tolist()
        raise InvalidIntervalError(
            f"canonical intervals require end > start; violated at row(s) {rows[:5]}"
        )
    if STRAND_COLUMN in df.columns:
        strand = df[STRAND_COLUMN]
        invalid = strand[~strand.isna()]
        if not invalid.astype(str).isin(STRAND_VALUES).all():
            bad = sorted(set(invalid.astype(str).tolist()))
            raise InvalidIntervalError(
                f"strand must be '+' or '-' (or missing); got {bad}"
            )


def canonical_result_columns(
    coord_df: pd.DataFrame, annot_df: pd.DataFrame
) -> Tuple[str, ...]:
    """
    Deterministic canonical result column order.

    ``coord`` core, ``coord`` metadata (in input order), ``annot`` core,
    ``annot`` metadata (in input order), then ``has_overlap``.
    """
    return (
        CANONICAL_RESULT_COORD_CORE
        + tuple(f"coord_{c}" for c in interval_metadata_columns(coord_df))
        + CANONICAL_RESULT_ANNOT_CORE
        + tuple(f"annot_{c}" for c in interval_metadata_columns(annot_df))
        + (HAS_OVERLAP_COLUMN,)
    )


def _empty_canonical_result(columns: Iterable[str]) -> pd.DataFrame:
    """Empty result frame with the full canonical schema and dtypes."""
    dtypes = {
        "coord_start": "int64",
        "coord_end": "int64",
        "annot_start": "Int64",
        "annot_end": "Int64",
        HAS_OVERLAP_COLUMN: "bool",
        # Canonical closest distance (SPEC 8.6, Task 6E): nullable
        # integer even in an empty result.
        "distance": "Int64",
    }
    return pd.DataFrame(
        {
            c: pd.Series(dtype=dtypes.get(c, "object"))
            for c in columns
        }
    )


def canonicalize_annotation_result(
    result_df: pd.DataFrame,
    coord_df: pd.DataFrame,
    annot_df: pd.DataFrame,
    *,
    extra_columns: Iterable[str] = (),
) -> pd.DataFrame:
    """
    Enforce the canonical result contract on a backend output.

    ``result_df`` must already use ``coord_*``/``annot_*`` column naming
    (as produced by the backend adapters). This function:

    - rejects any missing expected column and any unexpected column
      (including backend-suffixed columns such as ``_1``/``_2``/
      ``_right``);
    - requires ``has_overlap`` and normalizes it to boolean;
    - requires query coordinates to be valid canonical intervals on
      every row (``coord_chr`` present, integer ``coord_start >= 0``,
      integer ``coord_end > coord_start``);
    - requires matched rows (``has_overlap=True``) to carry a valid
      canonical annotation interval (``annot_chr`` present, integer
      ``annot_start >= 0``, integer ``annot_end > annot_start``);
      malformed matched annotation coordinates are rejected with
      ``CanonicalSchemaError`` rather than coerced to missing;
    - converts coordinate fields to integer dtypes;
    - replaces all ``annot_*`` values on unmatched rows with canonical
      missing (``pd.NA``), so sentinels like ``"."``/``"-1"`` never leak;
    - reorders columns to the deterministic canonical order.
    
    Row order is preserved exactly as the engine emitted it; duplicated
    rows are never collapsed. An empty result yields an empty frame with
    the full canonical schema.

    ``extra_columns`` declares operation-specific additions (for example
    ``distance`` for closest mode) that are allowed beyond the core
    schema; anything undeclared is rejected.
    """
    expected = list(canonical_result_columns(coord_df, annot_df)) + list(extra_columns)

    if result_df is None or len(result_df.columns) == 0:
        return _empty_canonical_result(expected)

    missing = [c for c in expected if c not in result_df.columns]
    if missing:
        raise CanonicalSchemaError(
            f"backend result is missing canonical column(s): {missing}"
        )
    unexpected = [c for c in result_df.columns if c not in expected]
    if unexpected:
        raise CanonicalSchemaError(
            "backend result carries non-canonical column(s) that must be "
            "mapped by the engine adapter before canonicalization: "
            f"{unexpected}"
        )

    out = result_df.copy()

    has_overlap = out[HAS_OVERLAP_COLUMN]
    if not has_overlap.isin([True, False, 1, 0]).all():
        raise CanonicalSchemaError(
            "has_overlap must contain boolean values on every row"
        )
    out[HAS_OVERLAP_COLUMN] = has_overlap.astype(bool)
    matched = out[HAS_OVERLAP_COLUMN]
    
    # Query coordinates: valid canonical intervals on every row.
    # The string sentinel "." (a documented backend missing value)
    # counts as missing here.
    out["coord_chr"] = out["coord_chr"].astype(object)
    coord_chr_missing = out["coord_chr"].isna() | out["coord_chr"].astype(
        str
    ).str.strip().eq(".")
    if coord_chr_missing.any():
        rows = out.index[coord_chr_missing].tolist()
        raise CanonicalSchemaError(
            f"coord_chr must be present on every row; missing at row(s) {rows[:5]}"
        )
    for column in ("coord_start", "coord_end"):
        numeric = pd.to_numeric(out[column], errors="coerce")
        if numeric.isna().any():
            rows = out.index[numeric.isna()].tolist()
            raise CanonicalSchemaError(
                f"{column} must be a valid integer on every row; invalid at row(s) {rows[:5]}"
            )
        if not (numeric == numeric.round()).all():
            rows = out.index[numeric != numeric.round()].tolist()
            raise CanonicalSchemaError(
                f"{column} must be integer-valued on every row; non-integer at row(s) {rows[:5]}"
            )
        out[column] = numeric.astype("int64")
    if (out["coord_start"] < 0).any():
        rows = out.index[out["coord_start"] < 0].tolist()
        raise CanonicalSchemaError(
            f"coord_start must be >= 0; violated at row(s) {rows[:5]}"
        )
    if not (out["coord_end"] > out["coord_start"]).all():
        rows = out.index[out["coord_end"] <= out["coord_start"]].tolist()
        raise CanonicalSchemaError(
            f"coord_end must be > coord_start; violated at row(s) {rows[:5]}"
        )
    
    # Matched rows must already carry a valid canonical annotation
    # interval: malformed matched values are rejected, never coerced to
    # missing (that would fabricate a valid-looking canonical row).
    if matched.any():
        annot_numeric = {}
        for column in ("annot_start", "annot_end"):
            numeric = pd.to_numeric(out[column], errors="coerce")
            bad = matched & numeric.isna()
            if bad.any():
                rows = out.index[bad].tolist()
                raise CanonicalSchemaError(
                    f"{column} must be a valid integer on matched rows; invalid at row(s) {rows[:5]}"
                )
            non_int = matched & (numeric != numeric.round())
            if non_int.any():
                rows = out.index[non_int].tolist()
                raise CanonicalSchemaError(
                    f"{column} must be integer-valued on matched rows; non-integer at row(s) {rows[:5]}"
                )
            annot_numeric[column] = numeric
        m = out.index[matched]
        if annot_numeric["annot_start"].loc[m].lt(0).any():
            rows = m[annot_numeric["annot_start"].loc[m].lt(0)].tolist()
            raise CanonicalSchemaError(
                f"annot_start must be >= 0 on matched rows; violated at row(s) {rows[:5]}"
            )
        if not (annot_numeric["annot_end"].loc[m] > annot_numeric["annot_start"].loc[m]).all():
            rows = m[
                annot_numeric["annot_end"].loc[m] <= annot_numeric["annot_start"].loc[m]
            ].tolist()
            raise CanonicalSchemaError(
                f"annot_end must be > annot_start on matched rows; violated at row(s) {rows[:5]}"
            )
        if (
            out["annot_chr"].loc[m].isna()
            | out["annot_chr"].loc[m].astype(str).str.strip().eq(".")
        ).any():
            rows = m[
                out["annot_chr"].loc[m].isna()
                | out["annot_chr"].loc[m].astype(str).str.strip().eq(".")
            ].tolist()
            raise CanonicalSchemaError(
                f"annot_chr must be present on matched rows; missing at row(s) {rows[:5]}"
            )
    
    out["annot_chr"] = out["annot_chr"].astype(object)
    for column in ("annot_start", "annot_end"):
        out[column] = pd.to_numeric(out[column], errors="coerce").astype("Int64")

    # Canonical missing on unmatched rows: every annot_* field.
    # Guard: with no unmatched rows the assignment is a value no-op, but
    # pandas 3.x still validates the scalar against each column dtype and
    # raises for bool annot_* columns (verified on pinned pandas 3.0.6;
    # other dtype-mismatched columns may raise depending on version).
    # Discovered by the Task 3 parity harness, which feeds all-matched
    # frames through this path.
    annot_cols = [c for c in expected if c.startswith("annot_")]
    if (~matched).any():
        out.loc[~matched, annot_cols] = CANONICAL_MISSING

    # Deterministic object dtype for all remaining text/metadata columns.
    for column in expected:
        if column in (
            "coord_chr",
            "coord_start",
            "coord_end",
            "annot_chr",
            "annot_start",
            "annot_end",
            HAS_OVERLAP_COLUMN,
        ):
            continue
        if column.startswith("coord_") or column.startswith("annot_"):
            out[column] = out[column].astype(object)

    return out[expected]