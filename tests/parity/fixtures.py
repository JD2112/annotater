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
    #: Task 6E (closest cases only): explicit expected canonical
    #: distances aligned with ``pairs`` — an ``int`` for matched rows,
    #: ``None`` for unmatched rows. Values are hand-derived from the
    #: SPEC 8.6 half-open gap formula, never from backend output. An
    #: empty tuple means "no distances" (every non-closest case).
    distances: tuple = ()


# ---------------------------------------------------------------------------
# Shared known-deviation reasons (detailed inventory in
# docs/implementation-notes.md). Reasons name the exact root cause and the
# normative requirement violated. The Task 3 Polars-Bio reasons
# (non-canonical schema, coordinate-system default, swallowed backend
# errors, empty-annotation left mode) were resolved in Task 4 and removed;
# the Task 3 Bedtools reasons (B1-B5) were resolved in Task 5 and removed.
# No known-deviation reasons remain as of Task 5.
# ---------------------------------------------------------------------------