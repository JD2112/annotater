"""
Streamlit UI integration tests (Task 7)

Covers, through the real Streamlit app entrypoint (AppTest):

- backend selector: both engines exposed, selection reaches the engine;
- same input + same options -> contractually equivalent results on
  both backends, including exported content;
- all four operation modes through the UI;
- min_overlap gating (overlap-only; never leaks into other modes);
- strand control reaching the engine;
- closest mode: distance column, tie handling, empty result;
- backend execution failure surfaced as a concise labeled error (never
  st.exception, never a valid empty result);
- valid zero-match state shown as information, not an error;
- explicit invalidation of stale results when configuration changes;
- unavailable backend: explicit user-visible error, no fallback;
- preview/parse independence from the engine choice.
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from streamlit.testing.v1 import AppTest

from streamlit_app.core.annotator import BedtoolsEngine
from streamlit_app.core import canonicalize_annotation_result, parse_and_normalize
from streamlit_app.utils import save_uploaded_file
from streamlit_app.streamlit_app import convert_df_to_vcf
from tests.parity.comparator import assert_canonical_equal

from pathlib import Path

APP_ENTRYPOINT = Path(__file__).parent.parent / "streamlit_app" / "streamlit_app.py"

# ---------------------------------------------------------------------------
# Fixtures (minimal synthetic inputs; feature "gene" matches the default
# feature filter ["gene"])
# ---------------------------------------------------------------------------

COORD_BED = (
    b"chr1\t100\t200\tq1\n"
    b"chr1\t500\t600\tq2\n"
    b"chr1\t900\t1000\tq3\n"
)

ANNOT_GFF = (
    b"##gff-version 3\n"
    b"chr1\tsrc\tgene\t150\t250\t.\t+\t.\tID=g1;Name=G1\n"
    b"chr1\tsrc\tgene\t550\t700\t.\t-\t.\tID=g2;Name=G2\n"
    b"chr1\tsrc\tgene\t950\t1050\t.\t+\t.\tID=g3;Name=G3\n"
)

# Query [100,110): annotation A [39,50) -> distance 50; annotation B
# [160,171) -> distance 50. Equal distance on both sides: a tie, and
# SPEC 6.1 requires all tied nearest annotations.
COORD_TIE = b"chr1\t100\t110\tqt\n"
ANNOT_TIE = (
    b"##gff-version 3\n"
    b"chr1\tsrc\tgene\t40\t50\t.\t+\t.\tID=a1;Name=A1\n"
    b"chr1\tsrc\tgene\t161\t171\t.\t+\t.\tID=a2;Name=A2\n"
)

COORD_NO_MATCH = b"chr1\t100\t200\tq1\n"
ANNOT_OTHER_CHR = (
    b"##gff-version 3\n"
    b"chr2\tsrc\tgene\t150\t250\t.\t+\t.\tID=g1;Name=G1\n"
)

COORD_VCF = (
    b"##fileformat=VCFv4.2\n"
    b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    b"chr1\t150\t.\tA\tT\t.\t.\t.\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _widget(at: AppTest, etype: str, key: str):
    for element in at.get(etype):
        if getattr(element, "key", None) == key:
            return element
    raise KeyError(f"no {etype} with key {key!r}")


def _has_widget(at: AppTest, etype: str, key: str) -> bool:
    return any(getattr(el, "key", None) == key for el in at.get(etype))


def _app() -> AppTest:
    return AppTest.from_file(str(APP_ENTRYPOINT), default_timeout=120)


def _assert_no_exception(at: AppTest):
    if at.exception:
        raise at.exception[0].value


def _run_flow(
    at: AppTest,
    coord_name: str = "coords.bed",
    coord_content: bytes = COORD_BED,
    annot_name: str = "annot.gff",
    annot_content: bytes = ANNOT_GFF,
) -> AppTest:
    """Upload both files so parse/preview is live."""
    at.run()
    _widget(at, "file_uploader", "coord_file").set_value(
        (coord_name, coord_content, "application/octet-stream")
    )
    _widget(at, "file_uploader", "annot_file").set_value(
        (annot_name, annot_content, "application/octet-stream")
    )
    at.run()
    return at


def _configure_and_run(at: AppTest, widgets: dict) -> AppTest:
    """Apply {element_type: {key: value}} and press Run annotation."""
    for etype, changes in widgets.items():
        for key, value in changes.items():
            _widget(at, etype, key).set_value(value)
    at.run()
    _widget(at, "button", "run_button").set_value(True)
    at.run()
    _assert_no_exception(at)
    return at


def _result(at: AppTest) -> pd.DataFrame:
    assert "result_df" in at.session_state, "no result stored after run"
    return at.session_state["result_df"]


def _reference_result(coord_df: pd.DataFrame, annot_df: pd.DataFrame,
                      mode: str, use_strand: bool = False,
                      min_overlap=None) -> pd.DataFrame:
    """Independent engine reference, canonicalized at the same boundary."""
    raw = BedtoolsEngine(
        mode=mode, use_strand=use_strand, min_overlap=min_overlap
    ).intersect(coord_df, annot_df, how="left")
    return canonicalize_annotation_result(
        raw, coord_df, annot_df,
        extra_columns=("distance",) if mode == "closest" else (),
    )


def _fake_upload(name: str, content: bytes):
    """Minimal stand-in for a Streamlit UploadedFile (name + getvalue)."""
    bio = io.BytesIO(content)
    bio.name = name
    return bio


def _parse_pair(coord_name, coord_content, annot_name, annot_content):
    """Parse the same files the way the app does (backend-independent)."""
    coord_df = parse_and_normalize(
        save_uploaded_file(_fake_upload(coord_name, coord_content))
    )
    annot_df = parse_and_normalize(
        save_uploaded_file(_fake_upload(annot_name, annot_content))
    )
    return coord_df, annot_df


# ---------------------------------------------------------------------------
# Backend selector
# ---------------------------------------------------------------------------

class TestBackendSelector:
    def test_exposes_both_engines_with_bedtools_default(self):
        at = _app()
        at.run()
        _assert_no_exception(at)
        radio = _widget(at, "radio", "engine")
        assert radio.options == ["Bedtools", "Polars-Bio"]
        assert radio.value == "Bedtools"

    def test_selected_engine_reaches_the_engine(self):
        at = _run_flow(_app())
        at = _configure_and_run(at, {"radio": {"engine": "Polars-Bio"}})
        metrics = {m.label: m.value for m in at.get("metric")}
        assert metrics["Engine"] == "Polars-Bio"
        assert metrics["Operation"] == "overlap"
        assert int(metrics["Matched rows"].replace(",", "")) == 3

    def test_unavailable_backend_shows_warning_and_blocks_without_fallback(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            "streamlit_app.core.engine_registry.bedtools_available",
            lambda: False,
        )
        at = _run_flow(_app())
        assert any(
            "unavailable in this environment" in e.value
            for e in at.get("warning")
        )
        # Running with the unavailable default backend fails explicitly.
        _widget(at, "button", "run_button").set_value(True)
        at.run()
        _assert_no_exception(at)
        errors = [e.value for e in at.get("error")]
        assert any("unavailable in this environment" in e for e in errors)
        assert any("Polars-Bio" in e for e in errors)
        # No silent fallback: nothing was executed.
        assert "result_df" not in at.session_state


# ---------------------------------------------------------------------------
# Parity through the UI: same canonical input, both engines
# ---------------------------------------------------------------------------

class TestUIParity:
    def test_same_input_gives_equivalent_results_and_exports(self):
        at = _run_flow(_app())
        at = _configure_and_run(at, {})  # default: Bedtools
        bedtools_result = _result(at)

        at = _configure_and_run(at, {"radio": {"engine": "Polars-Bio"}})
        polars_result = _result(at)

        # Same canonical result per the repo's normative parity comparator
        # (schema, row multiplicity, order, values, contract dtypes).
        assert_canonical_equal(polars_result, bedtools_result,
                               label="engine parity")

        # Same exported content.
        assert bedtools_result.to_csv(index=False) == \
            polars_result.to_csv(index=False)
        assert bedtools_result.to_csv(index=False, sep="\t") == \
            polars_result.to_csv(index=False, sep="\t")

        # Matches both the independent engine reference.
        coord_df, annot_df = _parse_pair("coords.bed", COORD_BED,
                                         "annot.gff", ANNOT_GFF)
        assert_frame_equal(bedtools_result, _reference_result(
            coord_df, annot_df, "overlap"))

    def test_vcf_export_is_identical_for_both_engines(self):
        def run_vcf(engine: str) -> str:
            at = _run_flow(_app(), coord_name="coords.vcf",
                           coord_content=COORD_VCF)
            _configure_and_run(at, {"radio": {"engine": engine}})
            return convert_df_to_vcf(_result(at))

        a = run_vcf("Bedtools")
        b = run_vcf("Polars-Bio")

        def data_lines(vcf_text: str):
            return [
                line for line in vcf_text.splitlines()
                if line and not line.startswith("##")
            ]

        assert data_lines(a) == data_lines(b)
        # The reconstructed record keeps the variant at the original POS.
        assert any(
            line.startswith("chr1\t150\t") for line in data_lines(a)
            if not line.startswith("#CHROM")
        )

    def test_preview_is_independent_of_the_engine(self):
        at = _run_flow(_app())
        coord_before = at.session_state["coord_parse"]["df"]
        annot_before = at.session_state["annot_parse"]["df"]
        coord_df = parse_and_normalize(
            save_uploaded_file(_fake_upload("coords.bed", COORD_BED))
        )
        assert_frame_equal(coord_before, coord_df)
        # Switching the engine must not re-parse or alter the previews.
        _widget(at, "radio", "engine").set_value("Polars-Bio")
        at.run()
        _assert_no_exception(at)
        assert at.session_state["coord_parse"]["df"] is coord_before
        assert at.session_state["annot_parse"]["df"] is annot_before


# ---------------------------------------------------------------------------
# Operation modes through the UI
# ---------------------------------------------------------------------------

class TestOperationModes:
    @pytest.mark.parametrize("mode", ["overlap", "contains", "within", "closest"])
    def test_mode_reaches_the_engine_and_matches_reference(self, mode):
        at = _run_flow(_app())
        at = _configure_and_run(at, {"selectbox": {"mode": mode}})
        result = _result(at)
        metrics = {m.label: m.value for m in at.get("metric")}
        assert metrics["Operation"] == mode
        coord_df, annot_df = _parse_pair("coords.bed", COORD_BED,
                                         "annot.gff", ANNOT_GFF)
        expected = _reference_result(coord_df, annot_df, mode)
        assert_frame_equal(result, expected)
        if mode == "closest":
            assert "distance" in result.columns
            assert {m.label for m in at.get("metric")} >= {"Distance column present"}

    def test_closest_distance_values_and_ties(self):
        at = _run_flow(_app(), coord_name="coords.bed", coord_content=COORD_TIE,
                       annot_name="annot.gff", annot_content=ANNOT_TIE)
        at = _configure_and_run(at, {"selectbox": {"mode": "closest"}})
        result = _result(at)
        # Tied nearest annotations are all returned (SPEC 6.1).
        assert len(result) == 2
        assert result["has_overlap"].all()
        assert set(result["distance"]) == {50}

    def test_closest_empty_result_keeps_unmatched_row(self):
        at = _run_flow(_app(), coord_name="coords.bed",
                       coord_content=COORD_NO_MATCH,
                       annot_name="annot.gff",
                       annot_content=ANNOT_OTHER_CHR)
        at = _configure_and_run(at, {"selectbox": {"mode": "closest"}})
        result = _result(at)
        assert len(result) == 1
        assert not result["has_overlap"].item()
        assert pd.isna(result["distance"].item())
        assert not [e.value for e in at.get("error")]


# ---------------------------------------------------------------------------
# min_overlap gating
# ---------------------------------------------------------------------------

class TestMinOverlapGating:
    def test_slider_present_for_overlap_and_absent_elsewhere(self):
        at = _run_flow(_app())
        at.run()
        slider = _widget(at, "slider", "min_overlap")
        assert slider.value == 0.0  # slider-0 == ordinary positive overlap

        _widget(at, "selectbox", "mode").set_value("contains")
        at.run()
        _assert_no_exception(at)
        assert not _has_widget(at, "slider", "min_overlap")

    def test_min_overlap_reaches_the_engine(self):
        at = _run_flow(_app())
        # At fraction 0.99 none of the three overlaps (each ~51%) qualifies.
        at = _configure_and_run(at, {"slider": {"min_overlap": 0.99}})
        result = _result(at)
        assert len(result) == 3
        assert not result["has_overlap"].any()

        coord_df, annot_df = _parse_pair("coords.bed", COORD_BED,
                                         "annot.gff", ANNOT_GFF)
        assert_frame_equal(
            result, _reference_result(coord_df, annot_df, "overlap",
                                      min_overlap=0.99)
        )

    def test_stale_min_overlap_cannot_leak_into_other_modes(self):
        at = _run_flow(_app())
        _widget(at, "slider", "min_overlap").set_value(0.99)
        at.run()
        # Switch to contains; the hidden slider must have no effect.
        at = _configure_and_run(at, {"selectbox": {"mode": "contains"}})
        result = _result(at)
        coord_df, annot_df = _parse_pair("coords.bed", COORD_BED,
                                         "annot.gff", ANNOT_GFF)
        assert_frame_equal(result, _reference_result(
            coord_df, annot_df, "contains", min_overlap=None
        ))


# ---------------------------------------------------------------------------
# Strand control
# ---------------------------------------------------------------------------

class TestJoinBehavior:
    def test_left_keeps_unmatched_rows_and_inner_drops_them(self):
        at = _run_flow(_app(), coord_name="coords.bed",
                       coord_content=COORD_NO_MATCH,
                       annot_name="annot.gff",
                       annot_content=ANNOT_OTHER_CHR)
        # Default: left join keeps the unmatched query row.
        _configure_and_run(at, {})
        result = _result(at)
        assert len(result) == 1
        assert not result["has_overlap"].item()

        # Inner join keeps matched rows only: zero rows, informational.
        at = _configure_and_run(
            at, {"radio": {"join": "Matched rows only (inner join)"}}
        )
        result = _result(at)
        assert len(result) == 0
        assert not [e.value for e in at.get("error")]


class TestStrandControl:
    def test_strand_reaches_the_engine_and_is_recomputed(self):
        at = _run_flow(_app())
        at = _configure_and_run(at, {"checkbox": {"use_strand": True}})
        # BED queries carry no strand; with the strict strand policy
        # nothing qualifies.
        result = _result(at)
        assert not result["has_overlap"].any()

        # Toggle back off: results are recomputed, not shown stale.
        at = _configure_and_run(at, {"checkbox": {"use_strand": False}})
        result = _result(at)
        coord_df, annot_df = _parse_pair("coords.bed", COORD_BED,
                                         "annot.gff", ANNOT_GFF)
        assert_frame_equal(result, _reference_result(
            coord_df, annot_df, "overlap", use_strand=False
        ))
        assert int(result["has_overlap"].sum()) == 3


# ---------------------------------------------------------------------------
# Error and zero-match policy
# ---------------------------------------------------------------------------

class TestErrorAndZeroMatchPolicy:
    def test_backend_failure_is_a_labeled_error_not_an_empty_result(
        self, monkeypatch
    ):
        def boom(self, *args, **kwargs):
            raise RuntimeError("bedtools crashed (simulated)")

        monkeypatch.setattr(BedtoolsEngine, "intersect", boom)
        at = _run_flow(_app())
        _configure_and_run(at, {})
        _assert_no_exception(at)
        errors = [e.value for e in at.get("error")]
        assert any(
            "Bedtools" in e and "overlap" in e and "bedtools crashed" in e
            for e in errors
        )
        # Not a valid result: nothing stored, no "zero matches" messaging.
        assert "result_df" not in at.session_state

    def test_valid_zero_match_is_information_not_error(self):
        at = _run_flow(_app(), coord_name="coords.bed",
                       coord_content=COORD_NO_MATCH,
                       annot_name="annot.gff",
                       annot_content=ANNOT_OTHER_CHR)
        _configure_and_run(at, {})
        _assert_no_exception(at)
        assert not [e.value for e in at.get("error")]
        assert any(
            "No qualifying annotations" in e.value for e in at.get("info")
        )
        result = _result(at)
        assert not result["has_overlap"].any()


# ---------------------------------------------------------------------------
# State invalidation
# ---------------------------------------------------------------------------

class TestStateInvalidation:
    def test_engine_change_invalidates_stored_results(self):
        at = _run_flow(_app())
        _configure_and_run(at, {})
        assert "result_df" in at.session_state

        # Change the engine WITHOUT running: stored results are cleared
        # explicitly and must not be displayed as current.
        _widget(at, "radio", "engine").set_value("Polars-Bio")
        at.run()
        _assert_no_exception(at)
        assert "result_df" not in at.session_state
        assert any(
            "No results yet" in e.value for e in at.get("info")
        )

        # Running again with the new engine produces fresh results.
        _widget(at, "button", "run_button").set_value(True)
        at.run()
        _assert_no_exception(at)
        metrics = {m.label: m.value for m in at.get("metric")}
        assert metrics["Engine"] == "Polars-Bio"
        assert int(metrics["Matched rows"].replace(",", "")) == 3

    def test_mode_change_also_invalidates_stored_results(self):
        at = _run_flow(_app())
        _configure_and_run(at, {})
        assert "result_df" in at.session_state
        _widget(at, "selectbox", "mode").set_value("within")
        at.run()
        _assert_no_exception(at)
        assert "result_df" not in at.session_state