"""
Task A / F9 regression: custom query column mapping must preserve
metadata.

All unmapped user columns survive the mapping in original input order,
reach the canonical engine, and appear in the canonical result as
``coord_<column>``. A preserved ``strand`` column must participate
normally in strand-aware annotation. Collisions with canonical column
names (chr/start/end) must fail with a clear mapping error — never
silently overwrite or drop data.

Expected rows are hand-computed from the SPEC contract:

    query (0-based)  chr1 [100, 200)  name=q1  strand=+
    query (0-based)  chr1 [100, 200)  name=q2  strand=-
    annotation (GFF3 1-based) chr1 (150, 250) strand=+ -> canonical [149, 250)

    overlap mode, use_strand=True, left join:
      q1 (+): intersects [149, 250) with equal strand -> MATCH
      q2 (-): intersects but opposite strand          -> unmatched
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from streamlit_app.core import (
    CustomParser,
    canonicalize_annotation_result,
    normalize_intervals,
    parse_and_normalize,
)
from streamlit_app.core.annotator import BedtoolsEngine, PolarsBioEngine
from tests.parity.comparator import check_expected

APP_ENTRYPOINT = Path(__file__).parent.parent / "streamlit_app" / "streamlit_app.py"

ENGINES = [BedtoolsEngine, PolarsBioEngine]

CUSTOM_QUERY = (
    "chrom\tpos\tstop\tname\tstrand\n"
    "chr1\t100\t200\tq1\t+\n"
    "chr1\t100\t200\tq2\t-\n"
)
ANNOT_GFF = (
    b"##gff-version 3\n"
    b"chr1\tsrc\tgene\t150\t250\t.\t+\t.\tID=g1;Name=G1\n"
)


def _write_gff(tmp_path) -> str:
    path = tmp_path / "a.gff"
    path.write_bytes(ANNOT_GFF)
    return str(path)


def _mapped_custom_query(tmp_path, text=CUSTOM_QUERY, extra=None):
    """The exact contract path the app uses: parse -> map -> normalize."""
    tsv = tmp_path / "q.tsv"
    tsv.write_text(text)
    raw = CustomParser.parse(str(tsv))
    additional = extra if extra is not None else [
        c for c in raw.columns if c not in ("chrom", "pos", "stop")
    ]
    mapped = CustomParser.map_columns(raw, "chrom", "pos", "stop", additional)
    return normalize_intervals(mapped, coordinate_system="0-based")


class TestUnmappedColumnsPreserved:
    def test_unmapped_columns_preserved_in_original_input_order(self, tmp_path):
        result = _mapped_custom_query(tmp_path)

        # Canonical order: chr, start, end, [strand], <metadata in source
        # order>; name (after strand in the source) stays after strand.
        assert list(result.columns) == ["chr", "start", "end", "strand", "name"]
        assert result["name"].tolist() == ["q1", "q2"]
        assert result["strand"].tolist() == ["+", "-"]

    @pytest.mark.parametrize("engine_cls", ENGINES)
    def test_stranded_matching_uses_preserved_strand_and_metadata_survives(
        self, engine_cls, tmp_path
    ):
        coord_df = _mapped_custom_query(tmp_path)
        annot_df = parse_and_normalize(_write_gff(tmp_path))

        # q1 (+) vs annotation (+): overlap [149, 200), strands equal ->
        # match. q2 (-): opposite strand -> no stranded match (SPEC 8.3);
        # the left join keeps it exactly once as unmatched.
        check_expected(
            engine_cls, coord_df, annot_df,
            pairs=[(0, 0), (1, None)], how="left", use_strand=True,
        )

        raw = engine_cls(mode="overlap", use_strand=True).intersect(
            coord_df, annot_df, how="left"
        )
        result = canonicalize_annotation_result(raw, coord_df, annot_df)

        assert len(result) == 2
        # The preserved columns reach the canonical result as coord_*.
        assert "coord_name" in result.columns
        assert "coord_strand" in result.columns
        assert result["coord_name"].tolist() == ["q1", "q2"]
        assert result["coord_strand"].tolist() == ["+", "-"]
        assert result["has_overlap"].tolist() == [True, False]
        assert int(result["annot_start"].iloc[0]) == 149
        assert int(result["annot_end"].iloc[0]) == 250
        assert pd.isna(result["annot_chr"].iloc[1])


class TestMappingCollisionSafety:
    def test_unmapped_column_named_like_canonical_name_raises(self, tmp_path):
        tsv = tmp_path / "q.tsv"
        tsv.write_text(
            "chrom\tpos\tstop\tend\n"
            "chr1\t100\t200\tx\n"
        )
        raw = CustomParser.parse(str(tsv))
        # The user maps chrom/pos/stop; the leftover column is literally
        # named "end" and collides with a canonical name.
        with pytest.raises(ValueError, match="collid"):
            CustomParser.map_columns(raw, "chrom", "pos", "stop", ["end"])

    def test_same_column_mapped_to_two_canonical_roles_raises(self, tmp_path):
        tsv = tmp_path / "q.tsv"
        tsv.write_text("chrom\tpos\tstop\nchr1\t100\t200\n")
        raw = CustomParser.parse(str(tsv))
        with pytest.raises(ValueError, match="same column"):
            CustomParser.map_columns(raw, "pos", "pos", "stop")


class TestAppEndToEndMetadataAndStrand:
    def test_result_carries_coord_name_and_coord_strand_with_stranded_matching(self):
        from tests.test_custom_annotation_coordinate_system import (
            _app,
            _assert_no_exception,
            _press_run,
            _widget,
        )

        at = _app()
        at.run()
        _widget(at, "file_uploader", "coord_file").set_value(
            ("q.tsv", CUSTOM_QUERY.encode(), "application/octet-stream")
        )
        _widget(at, "file_uploader", "annot_file").set_value(
            ("a.gff", ANNOT_GFF, "application/octet-stream")
        )
        at.run()
        _assert_no_exception(at)
        _widget(at, "selectbox", "map_chr_col").set_value("chrom")
        _widget(at, "selectbox", "map_start_col").set_value("pos")
        _widget(at, "selectbox", "map_end_col").set_value("stop")
        _widget(at, "checkbox", "use_strand").set_value(True)
        _widget(at, "button", "apply_mapping").set_value(True)
        at.run()
        _assert_no_exception(at)
        at = _press_run(at)

        result = at.session_state["result_df"]
        # Metadata preserved through mapping, engine, and canonical result.
        assert "coord_name" in result.columns
        assert "coord_strand" in result.columns
        assert result["coord_name"].tolist() == ["q1", "q2"]
        assert result["coord_strand"].tolist() == ["+", "-"]
        assert result["has_overlap"].tolist() == [True, False]