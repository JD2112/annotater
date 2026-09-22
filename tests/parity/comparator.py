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
"""

from __future__ import annotations

import pandas as pd

from streamlit_app.core.schema import (
    HAS_OVERLAP_COLUMN,
    canonical_result_columns,
    canonicalize_annotation_result,
    interval_metadata_columns,
)

#: Columns whose dtype is contractually normative in canonical results.
_NORMATIVE_DTYPES = {
    "coord_start": "int64",
    "coord_end": "int64",
    "annot_start": "Int64",
    "annot_end": "Int64",
    HAS_OVERLAP_COLUMN: "bool",
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


def run_engine(engine_cls, coord_df: pd.DataFrame, annot_df: pd.DataFrame,
               how: str = "inner", **engine_kwargs) -> pd.DataFrame:
    """Run an engine and return its raw (pre-canonicalization) result."""
    engine = engine_cls(**engine_kwargs)
    return engine.intersect(coord_df, annot_df, how=how)


def run_and_canonicalize(engine_cls, coord_df: pd.DataFrame,
                         annot_df: pd.DataFrame, how: str = "inner",
                         **engine_kwargs) -> pd.DataFrame:
    """
    Run an engine and apply the canonical result adapter.

    This is the contract boundary tested by the parity harness: the
    engine may emit any intermediate schema, but
    ``canonicalize_annotation_result`` MUST accept it and produce a
    canonical frame. If the engine leaks backend artifacts or omits
    canonical columns, canonicalization raises ``CanonicalSchemaError``
    and the test fails at exactly that layer.
    """
    result = run_engine(engine_cls, coord_df, annot_df, how=how, **engine_kwargs)
    return canonicalize_annotation_result(result, coord_df, annot_df)


def build_expected_result(
    coord_df: pd.DataFrame,
    annot_df: pd.DataFrame,
    pairs: list,
) -> pd.DataFrame:
    """
    Build the normative expected canonical result from explicit pairs.

    ``pairs`` is a list of ``(query_row_index, annot_row_index_or_None)``
    in the exact expected canonical row order: original query row order,
    then original annotation row order within each query; an unmatched
    query (``None``) appears exactly once at its own query position.

    The expected frame is derived purely from the two input tables and
    the explicit pair list — no backend output is involved.
    """
    columns = canonical_result_columns(coord_df, annot_df)
    coord_meta = interval_metadata_columns(coord_df)
    annot_meta = interval_metadata_columns(annot_df)

    records = []
    for qi, ai in pairs:
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
    **engine_kwargs,
) -> None:
    """
    Layer 1+2 of the oracle: run ``engine_cls`` and compare the
    canonicalized result strictly against the explicit expected frame.
    """
    actual = run_and_canonicalize(
        engine_cls, coord_df, annot_df, how=how, **engine_kwargs
    )
    expected = build_expected_result(coord_df, annot_df, pairs)
    assert_canonical_equal(actual, expected, label=label)