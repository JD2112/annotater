"""
Backend-independent normalization boundary (PLAN Task 2)

``parse_and_normalize`` is the single choke point through which source
files enter the canonical coordinate space, shared by every annotation
engine. It deliberately accepts no engine/backend argument: choosing
Bedtools or Polars-Bio later must not change how the same source is
interpreted, and parser selection stays decoupled from backend selection
(backend selection is a later stage, handled by the engine adapters).

Coordinate systems
------------------

- ``bed``: BED is already 0-based half-open; coordinates pass through.
- ``gff``/``gtf``: 1-based inclusive; converted to 0-based half-open by
  ``start = start - 1`` (``end`` is unchanged because an inclusive end
  maps to an exclusive end of the same value).
- ``vcf``: VCF ``POS`` is 1-based. The parser builds the interval
  occupied by the reference sequence per the VCF specification,
  ``[POS, POS + max(1, len(REF)) - 1]``, or ``[POS, END]`` (both
  1-based inclusive) when ``INFO/END`` is present, and this module
  converts that 1-based span to the canonical half-open form. Source
  metadata (raw INFO field, FORMAT and sample columns when the header
  declares them) is retained by the parser as additional metadata
  columns; VCF ``.`` is mapped to canonical missing without changing
  biological meaning.
- ``custom``: no fixed coordinate columns exist before explicit column
  mapping; normalizing a custom file before mapping raises ``ValueError``.
  After mapping, the user's declared coordinate system applies,
  defaulting to 0-based (the historical effective behavior for custom
  tables: no conversion).
"""

from __future__ import annotations

import pandas as pd

from .parsers import BEDParser, GFFParser, VCFParser, FormatDetector
from .schema import (
    INTERVAL_COLUMNS,
    RESERVED_RESULT_PREFIXES,
    STRAND_COLUMN,
    STRAND_VALUES,
    CanonicalSchemaError,
    InvalidIntervalError,
    validate_canonical_interval_table,
)

#: Fixed source coordinate system per supported format.
FORMAT_COORDINATE_SYSTEMS = {
    "bed": "0-based",
    "gff": "1-based",
    "gtf": "1-based",
    "vcf": "1-based",
}

#: Default coordinate system for custom (unmapped) tables: historically
#: custom tables were treated as already-canonical 0-based half-open.
CUSTOM_DEFAULT_SYSTEM = "0-based"

_VALID_SYSTEMS = ("0-based", "1-based")

#: Strand tokens that mean "unknown" in source formats.
_STRAND_MISSING_TOKENS = ("", ".")


def coordinate_system_for(format_name, declared_system=None) -> str:
    """
    Resolve the source coordinate system for a parsed table.

    Known formats have a fixed, specification-defined system; an explicit
    ``declared_system`` must not silently re-interpret them. Custom tables
    use the user's declared system, defaulting to 0-based.
    """
    known = FORMAT_COORDINATE_SYSTEMS.get((format_name or "").lower())
    if known is not None:
        return known
    if declared_system in _VALID_SYSTEMS:
        return declared_system
    return CUSTOM_DEFAULT_SYSTEM


def normalize_intervals(df: pd.DataFrame, *, coordinate_system: str) -> pd.DataFrame:
    """
    Convert a parsed interval table to the canonical 0-based half-open
    model and return it with deterministic column order:

    ``chr, start, end, [strand], <metadata in source order>``.

    Raises ``CanonicalSchemaError`` for missing required columns or
    metadata using reserved result prefixes, and ``InvalidIntervalError``
    for coordinate/strand invariant violations. The input frame is not
    mutated.
    """
    if coordinate_system not in _VALID_SYSTEMS:
        raise CanonicalSchemaError(f"unknown coordinate system: {coordinate_system!r}")

    missing = [c for c in INTERVAL_COLUMNS if c not in df.columns]
    if missing:
        raise CanonicalSchemaError(
            f"interval table is missing required column(s): {missing}"
        )

    meta_cols = [
        c for c in df.columns if c not in INTERVAL_COLUMNS and c != STRAND_COLUMN
    ]
    reserved = [c for c in meta_cols if c.startswith(RESERVED_RESULT_PREFIXES)]
    if reserved:
        raise CanonicalSchemaError(
            f"metadata column(s) {reserved} use the reserved canonical result "
            "prefixes coord_/annot_; rename them before normalization"
        )

    out = df.copy()

    # Coordinates: cast to numeric first (so the 1-based shift below never
    # operates on user-supplied strings), then validate integrality after.
    for column in ("start", "end"):
        numeric = pd.to_numeric(out[column], errors="coerce")
        if numeric.isna().any():
            rows = out.index[numeric.isna()].tolist()
            raise InvalidIntervalError(
                f"'{column}' must be integer-valued; invalid value at row(s) {rows[:5]}"
            )
        out[column] = numeric

    if coordinate_system == "1-based":
        # 1-based inclusive [S, E]  ->  0-based half-open [S-1, E)
        out["start"] = out["start"] - 1

    for column in ("start", "end"):
        numeric = out[column]
        if not (numeric == numeric.round()).all():
            rows = out.index[numeric != numeric.round()].tolist()
            raise InvalidIntervalError(
                f"'{column}' must be integer-valued; non-integer at row(s) {rows[:5]}"
            )
        out[column] = numeric.astype("int64")

    # chr: must be present on every row.
    if out["chr"].isna().any():
        rows = out.index[out["chr"].isna()].tolist()
        raise InvalidIntervalError(
            f"chromosome values must be present on every row; missing at row(s) {rows[:5]}"
        )
    out["chr"] = out["chr"].astype(object)

    if (out["start"] < 0).any():
        rows = out.index[out["start"] < 0].tolist()
        raise InvalidIntervalError(
            f"canonical start must be >= 0; violated at row(s) {rows[:5]}"
        )
    if not (out["end"] > out["start"]).all():
        rows = out.index[out["end"] <= out["start"]].tolist()
        raise InvalidIntervalError(
            f"canonical intervals require end > start; violated at row(s) {rows[:5]}"
        )

    # Strand: '+'/'-' or canonical missing.
    if STRAND_COLUMN in out.columns:
        normalized = []
        for value in out[STRAND_COLUMN].tolist():
            if pd.isna(value):
                normalized.append(pd.NA)
            else:
                text = str(value).strip()
                normalized.append(
                    pd.NA if text in _STRAND_MISSING_TOKENS else text
                )
        strand = pd.Series(normalized, index=out.index, dtype=object)
        present = strand[~strand.isna()]
        if not present.isin(STRAND_VALUES).all():
            bad = sorted(set(present.tolist()))
            raise InvalidIntervalError(
                f"strand must be '+' or '-' (or missing); got {bad}"
            )
        out[STRAND_COLUMN] = strand

    # Canonical invariants, one final check on the normalized frame.
    validate_canonical_interval_table(out)

    ordered = (
        list(INTERVAL_COLUMNS)
        + ([STRAND_COLUMN] if STRAND_COLUMN in out.columns else [])
        + meta_cols
    )
    return out[ordered]


def parse_and_normalize(
    filepath,
    *,
    fmt=None,
    declared_system=None,
    **parse_kwargs,
) -> pd.DataFrame:
    """
    Parse a source file and return its canonical 0-based half-open
    interval table.

    This is the shared choke point for all annotation backends; there is
    no backend/engine parameter by design.

    - ``fmt`` overrides ``FormatDetector.detect`` (otherwise the format is
      detected from the file extension).
    - ``declared_system`` applies only to custom tables (after column
      mapping); it is ignored for known formats, whose coordinate
      semantics are fixed by the format specification.
    - ``parse_kwargs`` are forwarded to the format parser (for example
      ``feature_types`` for GFF/GTF).

    Custom files have no fixed coordinate columns before explicit column
    mapping, so they raise ``ValueError`` here; normalize the mapped
    frame directly with :func:`normalize_intervals`.
    """
    fmt_key = (fmt or FormatDetector.detect(str(filepath))).lower()

    if fmt_key == "bed":
        df = BEDParser.parse(str(filepath))
    elif fmt_key in ("gff", "gtf"):
        df = GFFParser.parse(str(filepath), **parse_kwargs)
    elif fmt_key == "vcf":
        df = VCFParser.parse(str(filepath))
    else:
        raise ValueError(
            f"format {fmt_key!r} has no fixed coordinate columns; custom files "
            "require explicit column mapping before normalization"
        )

    system = coordinate_system_for(fmt_key, declared_system)
    return normalize_intervals(df, coordinate_system=system)