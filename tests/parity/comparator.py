"""
Canonical result comparator for the parity harness (PLAN Task 3).

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

The strict comparator itself (``assert_canonical_equal`` and its
helpers) lives in ``streamlit_app/core/comparison.py`` so the production
Docker image can run the same parity gate inside the container (the
benchmark smoke does not ship ``tests/``).  This module re-exports it;
all existing imports (``from tests.parity.comparator import
assert_canonical_equal`` etc.) continue to work.  The test-only drivers
(``run_engine``, ``run_and_canonicalize``, ``build_expected_result``,
``interval_table``, ``check_expected``) stay in this module.
"""

from __future__ import annotations

import pandas as pd

from streamlit_app.core.comparison import (
    _NORMATIVE_DTYPES,
    _dtype_ok,
    _values_equal,
    assert_canonical_equal,
    is_missing,
)
from streamlit_app.core.schema import (
    HAS_OVERLAP_COLUMN,
    canonical_result_columns,
    canonicalize_annotation_result,
    interval_metadata_columns,
)

__all__ = [
    "assert_canonical_equal",
    "is_missing",
    "run_engine",
    "run_and_canonicalize",
    "build_expected_result",
    "interval_table",
    "check_expected",
]


def run_engine(engine_cls, coord_df: pd.DataFrame, annot_df: pd.DataFrame,
               how: str = "inner", **engine_kwargs) -> pd.DataFrame:
    """Run an engine and return its raw (pre-canonicalization) result."""
    engine = engine_cls(**engine_kwargs)
    return engine.intersect(coord_df, annot_df, how=how)


def run_and_canonicalize(engine_cls, coord_df: pd.DataFrame,
                         annot_df: pd.DataFrame, how: str = "inner",
                         extra_columns: tuple = (),
                         **engine_kwargs) -> pd.DataFrame:
    """
    Run an engine and apply the canonical result adapter.

    This is the contract boundary tested by the parity harness: the
    engine may emit any intermediate schema, but
    ``canonicalize_annotation_result`` MUST accept it and produce a
    canonical frame. If the engine leaks backend artifacts or omits
    canonical columns, canonicalization raises ``CanonicalSchemaError``
    and the test fails at exactly that layer.

    ``extra_columns`` declares operation-specific additions (for
    example ``("distance",)`` for closest mode, SPEC 8.6 / Task 6E).
    """
    result = run_engine(engine_cls, coord_df, annot_df, how=how, **engine_kwargs)
    return canonicalize_annotation_result(
        result, coord_df, annot_df, extra_columns=extra_columns
    )


def build_expected_result(
    coord_df: pd.DataFrame,
    annot_df: pd.DataFrame,
    pairs: list,
    distances: tuple = None,
) -> pd.DataFrame:
    """
    Build the normative expected canonical result from explicit pairs.

    ``pairs`` is a list of ``(query_row_index, annot_row_index_or_None)``
    in the exact expected canonical row order: original query row order,
    then original annotation row order within each query; an unmatched
    query (``None``) appears exactly once at its own query position.

    ``distances`` (optional, Task 6E) is a tuple aligned with ``pairs``
    giving the EXPLICIT expected canonical closest distance per row — an
    ``int`` for matched rows, ``None`` for unmatched rows. When given,
    the expected frame gains the ``distance`` column (nullable integer).
    The values come from the test case (derived from the SPEC 8.6
    formula by hand), never from any backend output.

    The expected frame is derived purely from the two input tables and
    the explicit pair list — no backend output is involved.
    """
    if distances is not None and len(distances) != len(pairs):
        raise AssertionError(
            f"distances ({len(distances)}) must align with pairs ({len(pairs)})"
        )
    columns = canonical_result_columns(coord_df, annot_df)
    if distances is not None:
        columns = columns + ("distance",)
    coord_meta = interval_metadata_columns(coord_df)
    annot_meta = interval_metadata_columns(annot_df)

    records = []
    for row_index, (qi, ai) in enumerate(pairs):
        row = {}
        qrow = coord_df.iloc[qi]
        row["coord_chr"] = qrow["chr"]
        row["coord_start"] = int(qrow["start"])
        row["coord_end"] = int(qrow["end"])
        for name in coord_meta:
            value = qrow[name]
            row[f"coord_{name}"] = pd.NA if is_missing(value) else value

        if ai is None:
            for name in ("chr", "start", "end", *annot_meta):
                row[f"annot_{name}"] = pd.NA
            row[HAS_OVERLAP_COLUMN] = False
        else:
            arow = annot_df.iloc[ai]
            row["annot_chr"] = arow["chr"]
            row["annot_start"] = int(arow["start"])
            row["annot_end"] = int(arow["end"])
            for name in annot_meta:
                value = arow[name]
                row[f"annot_{name}"] = pd.NA if is_missing(value) else value
            row[HAS_OVERLAP_COLUMN] = True
        if distances is not None:
            value = distances[row_index]
            row["distance"] = pd.NA if value is None else int(value)
        records.append(row)

    frame = pd.DataFrame(records, columns=columns)
    out = pd.DataFrame(index=frame.index)
    for col in columns:
        out[col] = frame[col].astype(_NORMATIVE_DTYPES.get(col, "object"))
    return out


def interval_table(chr_values, start_values, end_values, **metadata) -> pd.DataFrame:
    """Build a small canonical interval table (0-based half-open)."""
    data = {
        "chr": list(chr_values),
        "start": [int(v) for v in start_values],
        "end": [int(v) for v in end_values],
    }
    for name, values in metadata.items():
        data[name] = list(values)
    return pd.DataFrame(data)


def check_expected(
    engine_cls,
    coord_df: pd.DataFrame,
    annot_df: pd.DataFrame,
    pairs: list,
    how: str = "inner",
    label: str = "",
    distances: tuple = None,
    **engine_kwargs,
) -> None:
    """
    Layer 1+2 of the oracle: run ``engine_cls`` and compare the
    canonicalized result strictly against the explicit expected frame.

    ``distances`` (closest mode, Task 6E) supplies the explicit expected
    canonical distance per row and switches on the ``distance`` extra
    column at the canonicalization layer.
    """
    extra_columns = ("distance",) if distances is not None else ()
    actual = run_and_canonicalize(
        engine_cls, coord_df, annot_df, how=how,
        extra_columns=extra_columns, **engine_kwargs,
    )
    expected = build_expected_result(coord_df, annot_df, pairs, distances=distances)
    assert_canonical_equal(actual, expected, label=label)