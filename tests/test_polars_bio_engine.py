"""
Focused regression tests for the Polars-Bio engine rewrite (PLAN Task 4).

These pin the Task 4 guarantees that the parity suite only exercises
indirectly:

- the coordinate system is declared PER FRAME via ``config_meta``, never
  by mutating the process-wide polars-bio option: the engine is correct
  whether or not ``coordinate_system_zero_based`` is set globally, and
  it leaves the global option untouched (so BedtoolsEngine and
  PolarsBioEngine can run in the same streamlit process without
  interfering);
- no backend artifacts leak into raw output (no polars-bio ``_1``/``_2``
  column suffixes, no internal row-id columns, no bare column names);
- genuinely empty inputs produce genuinely empty results (no exception,
  no phantom rows);
- the raw output is accepted as-is by
  ``canonicalize_annotation_result`` for every how/mode combination
  (the schema guarantee lives at the raw layer, not in the public
  normalizer).
"""

from __future__ import annotations

import pandas as pd
import pytest
import polars_bio

from streamlit_app.core import PolarsBioEngine
from streamlit_app.core.schema import canonical_result_columns, canonicalize_annotation_result
from tests.parity.comparator import interval_table

CHR = "chrA"

# polars-bio process-wide option (Rust BioSessionContext); polars-bio's own
# default is "false" (1-based CLOSED), which is the WRONG model for canonical
# 0-based half-open data. The engine must never depend on it.
COORD_SYSTEM_OPTION = "datafusion.bio.coordinate_system_zero_based"

QUERY = interval_table([CHR, CHR], [10, 100], [20, 200], gene=["g1", "g2"])
ANNOT = interval_table([CHR, CHR], [5, 25], [15, 35], feature=["f1", "f2"])


def _query():
    return interval_table([CHR], [10], [20], gene=["g1"])


def _annot():
    return interval_table([CHR], [15], [25], feature=["f1"])


def _empty_interval_table(**meta):
    return interval_table([], [], [], **meta)


def test_polars_half_open_semantics_with_global_option_set_wrong():
    """Per-frame stamping must override a (wrong) global option setting.

    SPEC 5: canonical 0-based half-open semantics. If the engine depended
    on the process-wide polars-bio option, the 1-based closed global
    default (polars-bio's own default) would make touching intervals
    overlap.
    """
    import contextlib

    @contextlib.contextmanager
    def _global_option(value):
        original = polars_bio.get_option(COORD_SYSTEM_OPTION)
        polars_bio.set_option(COORD_SYSTEM_OPTION, value)
        try:
            yield
        finally:
            polars_bio.set_option(COORD_SYSTEM_OPTION, original)

    with _global_option(False):  # 1-based closed, the wrong model
        engine = PolarsBioEngine()
        # touching [10,20) and [20,25): must NOT overlap
        touching = engine.intersect(
            interval_table([CHR], [10], [20], gene=["g1"]),
            interval_table([CHR], [20], [25], feature=["f1"]),
            how="inner",
        )
        assert len(touching) == 0

        # true overlap [10,20) and [15,25): MUST overlap exactly once
        overlap = engine.intersect(
            interval_table([CHR], [10], [20], gene=["g1"]),
            interval_table([CHR], [15], [25], feature=["f1"]),
            how="inner",
        )
        assert len(overlap) == 1


def test_polars_engine_does_not_mutate_global_coordinate_option():
    """The engine must only stamp frames; the process-wide option (shared
    state) must come out exactly as it went in."""
    original = polars_bio.get_option(COORD_SYSTEM_OPTION)
    PolarsBioEngine().intersect(_query(), _annot(), how="inner")
    PolarsBioEngine(mode="closest").intersect(_query(), _annot())
    assert polars_bio.get_option(COORD_SYSTEM_OPTION) == original


def test_polars_raw_output_has_no_backend_artifacts():
    """Raw output must be exactly the canonical column set: no polars-bio
    ``_1``/``_2`` suffixes, no internal row-id columns, no bare names
    (SPEC 6; SPEC 9.2: provenance is explicit, never suffix-inferred)."""
    for how in ("inner", "left"):
        raw = PolarsBioEngine().intersect(QUERY, ANNOT, how=how)
        assert list(raw.columns) == list(canonical_result_columns(QUERY, ANNOT))
        for col in raw.columns:
            assert not col.endswith("_1") and not col.endswith("_2")
            assert "row_id" not in col


def test_polars_raw_accepted_by_canonicalizer_for_all_how_modes():
    """The schema guarantee lives at the raw layer: canonicalize must
    accept the engine output as-is for every how/mode combination."""
    for mode in ("overlap", "closest"):
        for how in ("inner", "left"):
            raw = PolarsBioEngine(mode=mode).intersect(QUERY, ANNOT, how=how)
            extra = ("distance",) if mode == "closest" else ()
            canonicalize_annotation_result(raw, QUERY, ANNOT, extra_columns=extra)  # must not raise


def test_polars_inner_empty_inputs_return_empty_result():
    """Genuinely empty input -> genuinely empty result (SPEC 9.2: this is
    NOT an error). inner mode always yields 0 rows for any empty side;
    left mode yields exactly the (non-empty) query rows, each unmatched;
    closest mode yields one row per query only when an annotation exists
    (k=1), so an empty annotation table yields 0 rows in every case."""
    empty = _empty_interval_table()
    for mode in ("overlap", "closest"):
        for left, right in (
            (empty, ANNOT),
            (QUERY, empty),
            (empty, empty),
        ):
            for how in ("inner", "left"):
                result = PolarsBioEngine(mode=mode).intersect(left, right, how=how)
                if mode == "closest":
                    expected = len(left) if len(right) else 0
                elif how == "left":
                    expected = len(left)
                else:
                    expected = 0
                assert len(result) == expected, (mode, how, left.shape, right.shape)
                if how == "left" and len(left) and expected == len(left):
                    assert not result["has_overlap"].any()


def test_polars_left_empty_annotation_preserves_queries():
    """SPEC 7.2: left mode with an empty annotation table preserves every
    query row exactly once, unmatched, with canonical missing annot
    fields."""
    result = PolarsBioEngine().intersect(QUERY, _empty_interval_table(), how="left")
    assert len(result) == 2
    assert list(result["has_overlap"]) == [False, False]
    for col in result.columns:
        if col.startswith("annot_"):
            assert result[col].isna().all(), col
    # query values preserved in input order
    assert list(result["coord_start"]) == [10, 100]
    assert list(result["coord_gene"]) == ["g1", "g2"]


def test_polars_nearest_distance_column_is_canonical_extra():
    """closest mode keeps the backend distance as an explicit extra column
    (documented in the engine docstring), appended after the canonical
    columns."""
    q = interval_table([CHR], [100], [200], gene=["g1"])
    a = interval_table([CHR], [15], [25], feature=["f1"])
    raw = PolarsBioEngine(mode="closest").intersect(q, a, how="inner")
    canonical = list(canonical_result_columns(q, a))
    assert list(raw.columns)[: len(canonical)] == canonical
    assert list(raw.columns)[len(canonical):] == ["distance"]
    # half-open gap between [15,25) and [100,200) is 100 - 25 = 75
    assert raw["distance"].iloc[0] == 75


def test_polars_malformed_input_raises_explicit_error():
    """Engine inputs must be canonical interval tables (engine-contract
    section 2); malformed input fails explicitly, not silently."""
    bad = pd.DataFrame({"start": [10], "end": [20]})  # no 'chr'
    with pytest.raises(Exception) as excinfo:
        PolarsBioEngine().intersect(bad, _annot(), how="inner")
    assert not isinstance(excinfo.value, AssertionError)