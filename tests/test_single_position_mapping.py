"""
Task A / F3 regression, through the real Streamlit application path
(AppTest against streamlit_app/streamlit_app.py).

A single-position custom query mapping is exactly one base:
  * 1-based position P  -> canonical [P-1, P);
  * 0-based position P  -> canonical [P, P+1).
"""

from __future__ import annotations

from tests.test_custom_annotation_coordinate_system import (
    _app,
    _assert_no_exception,
    _upload_both,
    _widget,
    ANNOT_GFF,
    ONE_BASED,
)

CUSTOM_QUERY_SINGLE_POS = b"chrom\tpos\tname\nchr1\t100\tx\n"


class TestSinglePositionCustomQueryMapping:
    def _map_single_position(self, at: AppTest):
        _widget(at, "selectbox", "map_chr_col").set_value("chrom")
        _widget(at, "selectbox", "map_start_col").set_value("pos")
        _widget(at, "selectbox", "map_end_col").set_value("None (single positions)")
        _widget(at, "button", "apply_mapping").set_value(True)
        at.run()
        _assert_no_exception(at)
        return at

    def test_one_based_single_position_is_exactly_one_base(self):
        at = _upload_both(
            _app(), "q.tsv", CUSTOM_QUERY_SINGLE_POS, "a.gff", ANNOT_GFF
        )
        _widget(at, "selectbox", "coord_system").set_value(ONE_BASED)
        at.run()
        _assert_no_exception(at)
        at = self._map_single_position(at)

        mapped = at.session_state["coord_mapped_df"]
        # 1-based position 100 -> canonical [99, 100): exactly one base.
        assert mapped[["chr", "start", "end"]].values.tolist() == [
            ["chr1", 99, 100]
        ]
        assert (mapped["end"] - mapped["start"]).tolist() == [1]
        # Metadata must survive the mapping (F9).
        assert "name" in mapped.columns
        assert mapped["name"].tolist() == ["x"]

    def test_zero_based_single_position_is_exactly_one_base(self):
        at = _upload_both(
            _app(), "q.tsv", CUSTOM_QUERY_SINGLE_POS, "a.gff", ANNOT_GFF
        )
        at = self._map_single_position(at)

        mapped = at.session_state["coord_mapped_df"]
        # 0-based position 100 -> canonical [100, 101): exactly one base.
        assert mapped[["chr", "start", "end"]].values.tolist() == [
            ["chr1", 100, 101]
        ]
        assert (mapped["end"] - mapped["start"]).tolist() == [1]

    def test_explicit_start_end_mapping_unchanged(self):
        """Regression guard: ordinary explicit start/end mapping keeps its
        existing, already-correct behavior (no double shift)."""
        custom_query = b"chrom\tpos\tstop\tname\nchr1\t100\t200\tx\n"
        at = _upload_both(
            _app(), "q.tsv", custom_query, "a.gff", ANNOT_GFF
        )
        _widget(at, "selectbox", "coord_system").set_value(ONE_BASED)
        at.run()
        _assert_no_exception(at)
        _widget(at, "selectbox", "map_chr_col").set_value("chrom")
        _widget(at, "selectbox", "map_start_col").set_value("pos")
        _widget(at, "selectbox", "map_end_col").set_value("stop")
        _widget(at, "button", "apply_mapping").set_value(True)
        at.run()
        _assert_no_exception(at)

        mapped = at.session_state["coord_mapped_df"]
        # 1-based inclusive (100, 200) -> canonical [99, 200).
        assert mapped[["chr", "start", "end"]].values.tolist() == [
            ["chr1", 99, 200]
        ]