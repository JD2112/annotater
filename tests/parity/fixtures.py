"""
Explicit parity fixtures (PLAN Task 3) — the primary semantic oracle.

Every fixture is a tiny in-memory canonical interval table (0-based
half-open ``[start, end)``) plus an **explicit expected row list**
derived from documented genomic interval semantics, independent of any
backend output:

- ordinary overlap exists iff ``max(a_start, b_start) < min(a_end, b_end)``
  (SPEC.md section 5; ``docs/engine-contract.md`` section 4);
- touching intervals do **not** overlap;
- ``how="left"`` preserves every query row; an unmatched query appears
  exactly once with ``has_overlap=False`` and canonical-missing
  ``annot_*`` fields (SPEC.md section 7.2).

Expected rows are ``(query_row_index, annot_row_index_or_None)`` tuples
in the exact canonical row order (query input order, then annotation
input order within a query; unmatched rows at their own query position,
per ``docs/engine-contract.md`` section 7).

``None`` as an annot index marks an unmatched query row.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .comparator import interval_table

CHR = "chrA"


@dataclass(frozen=True)
class ParityCase:
    """One parity case: inputs + expected rows + optional per-engine deviations.

    ``bedtools_xfail`` / ``polars_xfail``: when set (with a precise
    root-cause reason), the case is known to deviate for that engine and
    is marked ``xfail(strict=True)``. An empty reason means the case is
    expected to pass for that engine today.
    """

    name: str
    coord_df: object
    annot_df: object
    pairs: tuple
    how: str = "inner"
    bedtools_xfail: str = ""
    polars_xfail: str = ""
    engine_kwargs: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Shared known-deviation reasons (detailed inventory in
# docs/implementation-notes.md). Reasons name the exact root cause and the
# normative requirement violated. The Task 3 Polars-Bio reasons
# (non-canonical schema, coordinate-system default, swallowed backend
# errors, empty-annotation left mode) were resolved in Task 4 and removed.
# ---------------------------------------------------------------------------

BEDTOOLS_EMPTY_LEFT_REASON = (
    "BedtoolsEngine.intersect returns an empty frame whenever EITHER input is "
    "empty, so how='left' with an empty annotation table drops every unmatched "
    "query row instead of preserving it (SPEC 7.2: left mode MUST preserve every "
    "input query row; engine-contract section 6)."
)

BEDTOOLS_METADATA_MISSING_REASON = (
    "BedtoolsEngine stringifies metadata on the way to BED: a missing metadata "
    "value round-trips as the '.' sentinel and the column degrades to string, "
    "but the canonical contract requires canonical missing (pd.NA) and "
    "deterministic metadata preservation (SPEC 6; engine-contract section 8)."
)

BEDTOOLS_METADATA_TYPE_REASON = (
    "bedtools to_dataframe re-infers column dtypes from text: string metadata "
    "with numeric-looking values ('3.5') round-trips as float 3.5, changing the "
    "metadata value type (SPEC 6: input metadata MUST be preserved "
    "deterministically; SPEC 10.3 dtype-relevant comparison)."
)

BEDTOOLS_LEFT_SENTINELS_REASON = (
    "BedtoolsEngine raw left-mode output keeps bedtools -loj sentinel values "
    "('.'/'-1') in unmatched annotation fields instead of canonical missing "
    "values (engine-contract section 6/8). Currently masked at the public level "
    "by canonicalize_annotation_result; the engine must emit canonical missing "
    "directly. Task 5."
)

BEDTOOLS_SCHEMA_REASON = (
    "BedtoolsEngine output deviates from the canonical result schema "
    "(SPEC 6; engine-contract section 3)."
)