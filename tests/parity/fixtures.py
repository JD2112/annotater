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
# Shared known-deviation reasons (Task 3; detailed inventory in
# docs/implementation-notes.md). Reasons name the exact root cause and the
# normative requirement violated.
# ---------------------------------------------------------------------------

POLARS_SCHEMA_REASON = (
    "PolarsBioEngine output is not canonical: _post_process prefixes BOTH frames "
    "with coord_, keeps polars-bio _1/_2 suffixes, leaks the internal pb_row_id "
    "column (inner mode; left-mode reconstruction drops it), and no annot_* "
    "columns exist, so canonicalize_annotation_result "
    "rejects the frame before any semantic comparison (SPEC 6 exact canonical "
    "column set with provenance prefixes; SPEC 9.2; engine-contract section 3). "
    "Task 4 result-adapter work."
)

POLARS_TOUCHING_REASON = (
    "Two independent known deviations (both Task 4). (1) PolarsBioEngine output is not "
    "canonical: _post_process prefixes both frames with coord_, keeps polars-bio _1/_2 "
    "suffixes, leaks pb_row_id (inner mode), and no annot_* columns exist, so "
    "canonicalize_annotation_result rejects the frame before any semantic comparison "
    "(SPEC 6; engine-contract section 3). (2) PolarsBioEngine does not declare the "
    "coordinate system; polars-bio 0.35.1 defaults to 1-based CLOSED intervals, so "
    "canonical 0-based half-open data is re-interpreted and touching intervals are "
    "reported as overlapping (SPEC 5; engine-contract section 4)."
)

POLARS_COORD_SYSTEM_REASON = (
    "PolarsBioEngine does not declare the coordinate system; polars-bio 0.35.1 "
    "defaults to 1-based CLOSED intervals (global "
    "datafusion.bio.coordinate_system_zero_based unset), so canonical 0-based "
    "half-open data is re-interpreted and touching intervals are reported as "
    "overlapping (SPEC 5 canonical 0-based half-open model; engine-contract "
    "section 4: boundary-touching intervals do not overlap). Task 4."
)

POLARS_SWALLOW_REASON = (
    "PolarsBioEngine._join_overlap catches ALL pb.overlap exceptions and returns "
    "an empty DataFrame (logger.error only); SPEC 9.2 forbids swallowing backend "
    "exceptions and converting them into scientifically plausible empty results. "
    "Task 4."
)

POLARS_NEAR_SWALLOW_REASON = (
    "PolarsBioEngine._find_nearest catches ALL pb.nearest exceptions and returns "
    "an empty DataFrame; SPEC 9.2 forbids swallowing backend exceptions into "
    "empty results. Task 4."
)

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

POLARS_LEFT_EMPTY_ANNOT_REASON = (
    "PolarsBioEngine left mode with an empty annotation table preserves the "
    "query rows (reconstruction works) but the output is not canonical: only "
    "coord_* and suffixed backend columns exist, no annot_* columns, so "
    "canonicalize_annotation_result rejects the frame (SPEC 6; Task 4). "
    "Semantically the row preservation itself is correct."
)