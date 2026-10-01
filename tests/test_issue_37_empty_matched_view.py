"""
GitHub issue #37: selecting 'Matched only' on a result with no matched
rows crashed in Plotly (px.bar with an empty chromosome count frame).

An empty display subset is a valid view state, not a failure: the stored
result stays intact, an informational message is shown, no chart/gene
list is attempted, and the user can switch views.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
from streamlit.testing.v1 import AppTest

import streamlit_app.streamlit_app as app_module

ROOT = Path(__file__).parent.parent
APP_ENTRYPOINT = ROOT / "streamlit_app" / "streamlit_app.py"
EXAMPLES = ROOT / "data" / "examples"

ENGINES = ["Bedtools", "Polars-Bio"]

# Zero overlap between the query and the annotations (different chromosome).
COORD_NO_MATCH = b"chr1\t100\t200\tq1\nchr1\t300\t400\tq2\n"
ANNOT_OTHER_CHR = (
    b"##gff-version 3\n"
    b"chr2\tsrc\tgene\t150\t250\t.\t+\t.\tID=g1;Name=G1\n"
)
# One matched, one unmatched query row.
COORD_MIXED = b"chr1\t100\t200\tq1\nchr1\t5000\t5100\tq2\n"
ANNOT_MIXED = (
    b"##gff-version 3\n"
    b"chr1\tsrc\tgene\t150\t250\t.\t+\t.\tID=g1;Name=G1\n"
)


def _widget(at, etype, key):
    for element in at.get(etype):
        if getattr(element, "key", None) == key:
            return element
    raise KeyError(f"no {etype} with key {key!r}")


def _run(coord_name, coord, annot_name, annot, engine, join=None):
    at = AppTest.from_file(str(APP_ENTRYPOINT), default_timeout=120)
    at.run()
    _widget(at, "file_uploader", "coord_file").set_value(
        (coord_name, coord, "application/octet-stream")
    )
    _widget(at, "file_uploader", "annot_file").set_value(
        (annot_name, annot, "application/octet-stream")
    )
    at.run()
    _widget(at, "radio", "engine").set_value(engine)
    if join is not None:
        _widget(at, "radio", "join").set_value(join)
    at.run()
    _widget(at, "button", "run_button").set_value(True)
    at.run()
    assert not at.exception, at.exception[0].value if at.exception else None
    return at


def _show(at, view):
    _widget(at, "radio", "result_filter").set_value(view)
    at.run()
    return at


def _infos(at):
    return [i.value for i in at.get("info")]


def _example_run(engine):
    return _run(
        "example_coordinates.bed",
        (EXAMPLES / "example_coordinates.bed").read_bytes(),
        "example_strand_annotations.gff3",
        (EXAMPLES / "example_strand_annotations.gff3").read_bytes(),
        engine,
    )


@pytest.mark.parametrize("engine", ENGINES)
class TestIssue37Flow:
    def test_reported_example_files_matched_only_does_not_crash(self, engine):
        at = _example_run(engine)
        stored = at.session_state["result_df"]
        assert len(stored) > 0 and not stored["has_overlap"].any()

        _show(at, "Matched only")
        assert not at.exception
        assert not at.get("error")
        assert any(
            "No matched rows to display for the current filter." in m
            for m in _infos(at)
        )

    def test_stored_result_intact_and_views_still_switchable(self, engine):
        at = _example_run(engine)
        before = at.session_state["result_df"].copy()

        _show(at, "Matched only")
        assert at.session_state["result_df"].equals(before)
        assert len(at.dataframe[-1].value) == 0

        _show(at, "All")
        assert not at.exception
        assert len(at.dataframe[-1].value) == len(before)
        _show(at, "Unmatched only")
        assert not at.exception
        assert len(at.dataframe[-1].value) == len(before)
        assert not any("to display for the current filter" in m
                       for m in _infos(at))

    def test_no_charts_or_gene_list_rendered_for_empty_matched_view(self, engine):
        at = _example_run(engine)
        assert "Charts and gene list" in [e.label for e in at.expander]
        _show(at, "Matched only")
        assert not at.exception
        assert "Charts and gene list" not in [
            e.label for e in at.expander
        ]
        assert "Gene list (.txt)" not in [
            b.label for b in at.get("download_button")
        ]

    def test_unmatched_only_empty_when_everything_matches(self, engine):
        at = _run("q.bed", b"chr1\t100\t200\tq1\n", "a.gff", ANNOT_MIXED, engine)
        assert at.session_state["result_df"]["has_overlap"].all()
        _show(at, "Unmatched only")
        assert not at.exception
        assert any(
            "No unmatched rows to display for the current filter." in m
            for m in _infos(at)
        )
        _show(at, "Matched only")
        assert not at.exception
        assert len(at.dataframe[-1].value) == 1

    def test_inner_join_with_no_matches_unchanged(self, engine):
        at = _run("q.bed", COORD_NO_MATCH, "a.gff", ANNOT_OTHER_CHR, engine,
                  join="Matched rows only (inner join)")
        assert not at.exception
        assert at.session_state["result_df"].empty


@pytest.mark.parametrize("engine", ENGINES)
class TestNonEmptyViewsUnchanged:
    def test_matched_view_renders_charts_and_gene_list(self, engine):
        at = _run("q.bed", COORD_MIXED, "a.gff", ANNOT_MIXED, engine)
        result = at.session_state["result_df"]
        assert result["has_overlap"].tolist() == [True, False]

        _show(at, "Matched only")
        assert not at.exception
        assert len(at.dataframe[-1].value) == 1
        assert not any("to display for the current filter" in m
                       for m in _infos(at))
        labels = [b.label for b in at.get("download_button")]
        assert "Gene list (.txt)" in labels
        assert "Gene list (comma-separated)" in labels

    def test_all_view_renders_charts(self, engine):
        at = _run("q.bed", COORD_MIXED, "a.gff", ANNOT_MIXED, engine)
        assert not at.exception
        assert "Gene list (.txt)" in [
            b.label for b in at.get("download_button")
        ]


class TestEnginesConsistent:
    def test_both_engines_give_same_empty_view_state(self):
        outcomes = []
        for engine in ENGINES:
            at = _example_run(engine)
            _show(at, "Matched only")
            outcomes.append((
                len(at.session_state["result_df"]),
                len(at.dataframe[-1].value),
                [m for m in _infos(at) if "to display" in m],
                bool(at.exception),
            ))
        assert outcomes[0] == outcomes[1]


class TestChartHelperDirect:
    def test_empty_frame_is_handled_without_plotly(self):
        import pandas as pd

        empty = pd.DataFrame(
            {"coord_chr": pd.Series([], dtype=str),
             "annot_Name": pd.Series([], dtype=str),
             "has_overlap": pd.Series([], dtype=bool)}
        )
        with mock.patch.object(app_module.px, "bar") as bar, \
                mock.patch.object(app_module.px, "pie") as pie, \
                mock.patch.object(app_module.st, "info") as info:
            app_module._render_charts_and_gene_list(empty)
        bar.assert_not_called()
        pie.assert_not_called()
        info.assert_called_once()


# ---------------------------------------------------------------------------
# Empty display subset + VCF export (contract: the "Annotated VCF" control
# stays available and exports the displayed subset, here header-only).
# ---------------------------------------------------------------------------

QUERY_VCF = (
    b"##fileformat=VCFv4.2\n"
    b"##contig=<ID=chr1>\n"
    b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    b"chr1\t150\tv1\tA\tT\t.\t.\tDP=5\n"
    b"chr1\t160\tv2\tC\tG\t.\t.\tDP=6\n"
)


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize(
    ("annot", "view"),
    [
        (ANNOT_OTHER_CHR, "Matched only"),    # nothing matched
        (ANNOT_MIXED, "Unmatched only"),       # everything matched
    ],
)
def test_empty_view_vcf_export_is_safe_and_header_only(
    tmp_path, engine, annot, view
):
    at = _run("q.vcf", QUERY_VCF, "a.gff", annot, engine)
    stored = at.session_state["result_df"].copy()
    assert len(stored) >= 2

    _show(at, view)
    assert not at.exception
    assert len(at.dataframe[-1].value) == 0
    assert "Annotated VCF" in [b.label for b in at.get("download_button")]
    assert at.session_state["result_df"].equals(stored)

    # The export of the displayed (empty) subset, built exactly as the app
    # does: valid VCF, header only, none of the hidden rows.
    flag = view == "Matched only"
    subset = stored[stored["has_overlap"] == flag]
    assert subset.empty
    text = app_module.convert_df_to_vcf(
        subset,
        original_header_lines=at.session_state.get("result_vcf_header_lines"),
        contig_renames=at.session_state.get("result_vcf_contig_renames"),
    )
    lines = text.splitlines()
    assert lines[0] == "##fileformat=VCFv4.2"
    assert lines[-1].startswith("#CHROM")
    assert not [l for l in lines if l and not l.startswith("#")]

    pysam = pytest.importorskip("pysam", reason="independent VCF validation")
    path = tmp_path / "empty.vcf"
    path.write_text(text)
    with pysam.VariantFile(str(path)) as vf:
        assert list(vf.header.contigs) == ["chr1"]
        assert list(vf) == []

    # Switching back to a non-empty view still works and is unchanged.
    _show(at, "All")
    assert not at.exception
    assert len(at.dataframe[-1].value) == len(stored)
    assert at.session_state["result_df"].equals(stored)
