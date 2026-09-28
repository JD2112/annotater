"""
Strict canonical-frame comparison (shared parity contract).

This module is the single source of truth for the *strict* comparator
used by the parity test suite and the backend benchmark
(``benchmarks/benchmark_engines.py``).

``assert_canonical_equal`` is a strict comparison of two *canonicalized*
annotation results against the AnnotateR canonical result contract
(SPEC.md section 6, ``streamlit_app/core/schema.py``):

- exact column set AND deterministic column order;
- exact row count (row multiplicity — duplicates are never collapsed);
- exact row order (deterministic canonical ordering);
- value equality with explicit missing-value (``pd.NA``) semantics;
- boolean columns compared as real booleans (never ``1``/``0``);
- contractually-relevant dtypes: ``coord_start``/``coord_end`` int64,
  ``annot_start``/``annot_end`` nullable Int64, ``has_overlap`` bool.

It deliberately does NOT compare:
- row counts alone (values and order are checked);
- stringified frame representations (values are compared cell-wise);
- incidental metadata-column dtypes beyond the contract (dedicated tests
  assert type stability of metadata where the contract requires it).

Any backend artifact (``_1``/``_2``/``_right`` suffixes, ``pb_row_id``,
sentinel strings) either fails the exact-column check or shows up as a
value mismatch here; it cannot be silently ignored.

Why this lives in the package (and ``tests/parity/comparator.py``
re-exports it):
- The production Docker image runs the benchmark smoke inside the
  container (PLAN Task 8).  The benchmark's correctness gate must be the
  *same* strict comparator the parity suite uses, and the image does not
  ship ``tests/``.
- A strict canonical-frame comparator is part of the canonical contract
  (SPEC 4.6 / 8.4), so the package is a reasonable home.

The test-only drivers (``run_engine``, ``run_and_canonicalize``,
``build_expected_result``, ``interval_table``, ``check_expected``) stay
in ``tests/parity/comparator.py``.
"""

from __future__ import annotations

import pandas as pd

from streamlit_app.core.schema import HAS_OVERLAP_COLUMN

#: Columns whose dtype is contractually normative in canonical results.
_NORMATIVE_DTYPES = {
    "coord_start": "int64",
    "coord_end": "int64",
    "annot_start": "Int64",
    "annot_end": "Int64",
    HAS_OVERLAP_COLUMN: "bool",
    # Canonical closest distance (SPEC 8.6, Task 6E): nullable integer
    # on every closest result (matched rows carry an integer >= 0,
    # unmatched left rows carry pd.NA).
    "distance": "Int64",
}


def is_missing(value) -> bool:
    """True for canonical missing values (``pd.NA``/``None``/``NaN``)."""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _values_equal(actual, expected) -> bool:
    """Cell-wise equality with contract semantics.

    - booleans must be booleans on both sides (``1`` != ``True``);
    - numerics compare numerically (``7 == 7.0``) — an intentional
      tolerance: contractually normative dtypes (``coord_*``,
      ``annot_*`` coordinates, ``has_overlap``) are enforced separately
      by ``_NORMATIVE_DTYPES``, so a coordinate or flag column cannot
      drift int<->float; metadata dtype stability for str->float drift
      is pinned by the ``metadata_string_numeric_looks`` fixture;
    - strings and everything else must match type and value exactly, so
      a backend sentinel like ``"."`` or ``"True"`` for a missing/bool
      value is a mismatch.
    """
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(actual) is bool and type(expected) is bool and actual == expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return actual == expected
    return type(actual) is type(expected) and actual == expected


def _dtype_ok(dtype, expected: str) -> bool:
    if expected == "Int64":
        return str(dtype) == "Int64"
    return str(dtype) == expected


def assert_canonical_equal(
    actual: pd.DataFrame,
    expected: pd.DataFrame,
    label: str = "",
) -> None:
    """Strictly compare a canonicalized engine result with an expected frame."""
    ctx = f" [{label}]" if label else ""

    def fail(detail: str) -> None:
        raise AssertionError(
            f"canonical result mismatch{ctx}: {detail}\n"
            f"--- actual ---\n{actual.to_string()}\n"
            f"--- expected ---\n{expected.to_string()}"
        )

    if list(actual.columns) != list(expected.columns):
        fail(
            "column set/order differs\n"
            f"  actual:   {list(actual.columns)}\n"
            f"  expected: {list(expected.columns)}"
        )

    if len(actual) != len(expected):
        fail(f"row count differs: actual {len(actual)}, expected {len(expected)}")

    for col in expected.columns:
        for i, (av, ev) in enumerate(zip(actual[col], expected[col])):
            a_na, e_na = is_missing(av), is_missing(ev)
            if a_na != e_na:
                fail(
                    f"row {i}, column {col!r}: missing-value mismatch "
                    f"(actual={av!r}, expected={ev!r})"
                )
            if not a_na and not _values_equal(av, ev):
                fail(
                    f"row {i}, column {col!r}: value mismatch "
                    f"(actual={av!r} {type(av).__name__}, "
                    f"expected={ev!r} {type(ev).__name__})"
                )

    for col, want in _NORMATIVE_DTYPES.items():
        if col in expected.columns and not _dtype_ok(actual[col].dtype, want):
            fail(f"dtype of {col!r} is {actual[col].dtype}, contract requires {want}")