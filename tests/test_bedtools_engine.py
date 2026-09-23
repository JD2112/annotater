"""
Focused regression tests for the BedtoolsEngine rewrite (PLAN Task 5).

These pin the Task 5 guarantees that the parity suite only exercises
indirectly:

- the bedtools text file is an identity-only interop boundary (chr/
  start/end plus an internal row-id column per side); user metadata
  never crosses the text boundary, so no backend artifact (BED field
  names, internal row-id columns) can reach the raw output;
- the real-user-value regression (B2/B4): user metadata values that
  look like backend sentinels (``"."``, ``"-1"``) survive a matched
  round-trip verbatim, while missing values round-trip as canonical
  missing (``pd.NA``) and numeric-looking strings keep their type
  (B3);
- left mode with an empty annotation table is produced deterministically
  WITHOUT invoking bedtools (B1), preserving every query row unmatched;
- backend and conversion failures propagate instead of being reported
  as empty results (B5).
"""

from __future__ import annotations

import pandas as pd
import pybedtools
import pytest

from streamlit_app.core import BedtoolsEngine
from streamlit_app.core.schema import (
    canonical_result_columns,
    canonicalize_annotation_result,
    validate_canonical_interval_table,
)
from tests.parity.comparator import interval_table

CHR = "chrA"

QUERY = interval_table([CHR, CHR], [10, 100], [20, 200], gene=["g1", "g2"])
ANNOT = interval_table([CHR, CHR], [5, 25], [15, 35], feature=["f1", "f2"])


def _query():
    return interval_table([CHR], [10], [20], gene=["g1"])


def _annot():
    return interval_table([CHR], [15], [25], feature=["f1"])


def _empty_interval_table(**meta):
    return interval_table([], [], [], **meta)


def test_bedtools_raw_output_has_no_backend_artifacts():
    """Raw output must be exactly the canonical column set: no BED field
    names, no internal row-id columns, no positional ``col_N`` padding
    (SPEC 6; SPEC 9.2: provenance is explicit)."""
    for how in ("inner", "left"):
        raw = BedtoolsEngine().intersect(QUERY, ANNOT, how=how)
        assert list(raw.columns) == list(canonical_result_columns(QUERY, ANNOT))
        for col in raw.columns:
            assert not col.endswith("_1") and not col.endswith("_2")
            assert "row_id" not in col


def test_bedtools_raw_accepted_by_canonicalizer_for_all_how_modes():
    """The schema guarantee lives at the raw layer: canonicalize must
    accept the engine output as-is for every how/mode combination."""
    for mode in ("overlap", "closest"):
        for how in ("inner", "left"):
            raw = BedtoolsEngine(mode=mode).intersect(QUERY, ANNOT, how=how)
            extra = ("distance",) if mode == "closest" else ()
            canonicalize_annotation_result(raw, QUERY, ANNOT, extra_columns=extra)  # must not raise


def test_bedtools_left_empty_annotation_preserves_queries_without_bedtools(monkeypatch):
    """B1 (SPEC 7.2): left mode with an empty annotation table preserves
    every query row exactly once, unmatched, with canonical missing
    annot fields — and the canonical result is deterministic, so
    bedtools is not invoked at all."""
    calls = []
    monkeypatch.setattr(
        pybedtools.BedTool, "from_dataframe",
        lambda *a, **k: calls.append("from_dataframe"),
    )
    monkeypatch.setattr(
        pybedtools.BedTool, "intersect",
        lambda *a, **k: calls.append("intersect"),
    )

    result = BedtoolsEngine().intersect(QUERY, _empty_interval_table(feature=[]), how="left")

    assert calls == []  # deterministic result: no external call
    assert len(result) == 2
    assert list(result["has_overlap"]) == [False, False]
    for col in result.columns:
        if col.startswith("annot_"):
            assert result[col].isna().all(), col
    # query values preserved in input order
    assert list(result["coord_start"]) == [10, 100]
    assert list(result["coord_gene"]) == ["g1", "g2"]


def test_bedtools_real_user_sentinel_values_preserved():
    """B2/B4 regression: user metadata VALUES that look like backend
    sentinels (``"."``, ``"-1"``) must survive a matched round-trip
    verbatim — they must not be confused with missing values."""
    q = interval_table([CHR], [10], [20], label=["."], count=["-1"])
    a = interval_table([CHR], [15], [25], note=["."], kind=["-1"])
    raw = BedtoolsEngine().intersect(q, a, how="left")
    assert raw["coord_label"].iloc[0] == "."
    assert raw["coord_count"].iloc[0] == "-1"
    assert raw["annot_note"].iloc[0] == "."
    assert raw["annot_kind"].iloc[0] == "-1"
    assert bool(raw["has_overlap"].iloc[0])


def test_bedtools_missing_metadata_is_canonical_missing_not_dot():
    """B2: a genuinely missing metadata value on a MATCHED row must
    round-trip as canonical missing (pd.NA), never as the '.' sentinel
    string."""
    q = interval_table([CHR, CHR], [10, 100], [20, 200], gene=[None, "g2"])
    a = interval_table([CHR, CHR], [5, 25], [15, 35], feature=["f1", "f2"])
    raw = BedtoolsEngine().intersect(q, a, how="left")
    assert bool(raw["has_overlap"].iloc[0])
    assert raw["coord_gene"].iloc[0] is pd.NA or pd.isna(raw["coord_gene"].iloc[0])
    assert raw["coord_gene"].iloc[0] != "."


def test_bedtools_numeric_looking_strings_keep_type():
    """B3: string metadata with numeric-looking values ('3.5', '00123')
    must round-trip as the SAME strings — no dtype re-inference from
    text, no leading-zero loss."""
    q = interval_table([CHR], [10], [20], score=["3.5"], ref=["00123"])
    a = interval_table([CHR], [15], [25], value=["4.75"])
    raw = BedtoolsEngine().intersect(q, a, how="left")
    assert raw["coord_score"].iloc[0] == "3.5"
    assert raw["coord_ref"].iloc[0] == "00123"
    assert raw["annot_value"].iloc[0] == "4.75"
    assert not isinstance(raw["coord_score"].iloc[0], (int, float))


def test_bedtools_left_unmatched_annot_fields_are_canonical_missing():
    """B4: unmatched left rows must carry canonical missing (pd.NA) in
    every annot_* field — the bedtools -loj '.'/'-1' sentinels must not
    leak into the output."""
    q = interval_table([CHR], [10], [20], gene=["g1"])
    a = interval_table([CHR], [100], [200], feature=["f1"])  # no overlap
    raw = BedtoolsEngine().intersect(q, a, how="left")
    assert len(raw) == 1
    assert not raw["has_overlap"].iloc[0]
    for col in raw.columns:
        if col.startswith("annot_"):
            assert raw[col].isna().all(), col


def test_bedtools_empty_inputs_matrix():
    """Genuinely empty input -> genuinely empty result (SPEC 9.2: this is
    NOT an error). inner mode always yields 0 rows for any empty side;
    left mode yields exactly the (non-empty) query rows, each unmatched;
    closest mode yields one row per query only when an annotation exists,
    so an empty annotation table yields 0 rows in every case."""
    empty = _empty_interval_table(feature=[])
    for mode in ("overlap", "closest"):
        for left, right in (
            (empty, ANNOT),
            (QUERY, empty),
            (empty, empty),
        ):
            for how in ("inner", "left"):
                result = BedtoolsEngine(mode=mode).intersect(left, right, how=how)
                if mode == "closest":
                    expected = len(left) if len(right) else 0
                elif how == "left":
                    expected = len(left)
                else:
                    expected = 0
                assert len(result) == expected, (mode, how, left.shape, right.shape)
                if how == "left" and len(left) and expected == len(left):
                    assert not result["has_overlap"].any()


def test_bedtools_malformed_input_raises_explicit_error():
    """Engine inputs must be canonical interval tables (SPEC 4.2);
    malformed input fails explicitly, not silently."""
    bad = pd.DataFrame({"start": [10], "end": [20]})  # no 'chr'
    with pytest.raises(Exception) as excinfo:
        BedtoolsEngine().intersect(bad, _annot(), how="inner")
    assert not isinstance(excinfo.value, AssertionError)


def test_bedtools_malformed_non_integer_coordinates_raise():
    """Non-integer coordinates are rejected by canonical validation
    (SPEC 4.2), not converted or silently dropped."""
    bad = pd.DataFrame({"chr": [CHR], "start": [10.5], "end": [20.5], "gene": ["g1"]})
    with pytest.raises(Exception) as excinfo:
        BedtoolsEngine().intersect(bad, _annot(), how="inner")
    assert not isinstance(excinfo.value, AssertionError)
    # and the validation helper itself classifies the input
    with pytest.raises(Exception):
        validate_canonical_interval_table(bad)


def test_bedtools_to_dataframe_failure_propagates(monkeypatch):
    """B5: a result-conversion failure must propagate to the caller,
    never be swallowed and reported as an empty 'no match' result."""
    def boom(self, *args, **kwargs):
        raise RuntimeError("simulated conversion failure")

    monkeypatch.setattr(pybedtools.BedTool, "to_dataframe", boom)
    with pytest.raises(RuntimeError, match="simulated conversion failure"):
        BedtoolsEngine().intersect(QUERY, ANNOT, how="left")


def test_bedtools_backend_failure_propagates(monkeypatch):
    """B5: a bedtools backend failure must propagate (SPEC 9.2), not be
    reported as an empty result."""
    def boom(self, *args, **kwargs):
        raise pybedtools.helpers.BEDToolsError("cmd", "boom")

    monkeypatch.setattr(pybedtools.BedTool, "intersect", boom)
    with pytest.raises(pybedtools.helpers.BEDToolsError):
        BedtoolsEngine().intersect(QUERY, ANNOT, how="left")


def test_bedtools_duplicate_rows_preserve_identity_order():
    """Canonical ordering is by INPUT ROW IDENTITY, never by genomic
    coordinate: duplicate-valued query/annotation rows keep the
    (query input order, then annotation input order) expansion."""
    q = interval_table([CHR, CHR], [10, 10], [20, 20], gene=["q1", "q2"])
    a = interval_table([CHR, CHR], [15, 15], [25, 25], feature=["a1", "a2"])
    raw = BedtoolsEngine().intersect(q, a, how="left")
    # every query row matches both annotation rows: 4 rows
    assert len(raw) == 4
    # rows are ordered by query identity first, annotation identity second
    assert list(raw["coord_gene"]) == ["q1", "q1", "q2", "q2"]
    assert list(raw["annot_feature"]) == ["a1", "a2", "a1", "a2"]


def test_bedtools_closest_distance_column_is_canonical_extra():
    """closest mode keeps the backend distance as an explicit extra
    column (documented in the engine docstring), appended after the
    canonical columns; the layout is validated (9 raw columns)."""
    q = interval_table([CHR], [100], [200], gene=["g1"])
    a = interval_table([CHR], [15], [25], feature=["f1"])
    raw = BedtoolsEngine(mode="closest").intersect(q, a, how="inner")
    canonical = list(canonical_result_columns(q, a))
    assert list(raw.columns)[: len(canonical)] == canonical
    assert list(raw.columns)[len(canonical):] == ["distance"]
    # bedtools -d reports 76 for this pair (its own non-normative distance
    # definition — closest's full semantics are Task 6 scope); this pins
    # the lossless Int64 round-trip of the reported value, not the gap
    # arithmetic itself. Overlapping pairs report 0 (see parity cases).
    assert raw["distance"].iloc[0] == 76


def test_bedtools_overlap_does_not_delegate_strand_to_backend(monkeypatch):
    """Task 6B: the overlap path never delegates strand semantics to
    bedtools. ``use_strand=True`` runs an ordinary (unstranded)
    ``intersect`` — the shared canonical strand predicate is applied
    post-hoc in AnnotateR instead — so no ``s`` flag is forwarded. The
    non-normative closest placeholder keeps its native ``-s``."""
    seen_intersect = {}
    seen_closest = {}
    real_intersect = pybedtools.BedTool.intersect
    real_closest = pybedtools.BedTool.closest

    def intersect_spy(self, other, **kwargs):
        seen_intersect["s"] = kwargs.get("s")
        return real_intersect(self, other, **kwargs)

    def closest_spy(self, other, **kwargs):
        seen_closest["s"] = kwargs.get("s")
        return real_closest(self, other, **kwargs)

    monkeypatch.setattr(pybedtools.BedTool, "intersect", intersect_spy)
    monkeypatch.setattr(pybedtools.BedTool, "closest", closest_spy)

    BedtoolsEngine(use_strand=True).intersect(_query(), _annot(), how="left")
    assert seen_intersect["s"] is None  # never passed, not even s=False
    BedtoolsEngine().intersect(_query(), _annot(), how="left")
    assert seen_intersect["s"] is None

    # closest remains the non-normative placeholder (Task 6E scope):
    # its native -s forwarding is unchanged by Task 6B.
    BedtoolsEngine(use_strand=True, mode="closest").intersect(_query(), _annot())
    assert seen_closest["s"] is True
    BedtoolsEngine(mode="closest").intersect(_query(), _annot())
    assert seen_closest["s"] is False
