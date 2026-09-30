"""
Task A / F2 regression, through the real Streamlit application path
(AppTest against streamlit_app/streamlit_app.py).

Custom annotation tables must honor the declared coordinate system:
the user-selected "Annotation coordinates" declaration has to be
applied exactly once at the canonical boundary. The hand-computed
scenario:

    query BED   chr1 [99, 100)
    annotation  chr/start/end/name: chr1 100 200 G1

  * declared 1-based  -> annotation is 1-based inclusive [100, 200]
                          = canonical [99, 200) -> overlaps the query.
  * declared 0-based  -> annotation is canonical [100, 200), which only
                          touches [99, 100) -> NO positive overlap.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP_ENTRYPOINT = Path(__file__).parent.parent / "streamlit_app" / "streamlit_app.py"

COORD_BED = b"chr1\t99\t100\tq\n"
ANNOT_CUSTOM_TSV = b"chr\tstart\tend\tname\nchr1\t100\t200\tG1\n"
ANNOT_GFF = (
    b"##gff-version 3\n"
    b"chr1\tsrc\tgene\t90\t110\t.\t+\t.\tID=g1;Name=G1\n"
)

ONE_BASED = "1-based (GFF/GTF/VCF)"


def _widget(at: AppTest, etype: str, key: str):
    for element in at.get(etype):
        if getattr(element, "key", None) == key:
            return element
    raise KeyError(f"no {etype} with key {key!r}")


def _app() -> AppTest:
    return AppTest.from_file(str(APP_ENTRYPOINT), default_timeout=120)


def _assert_no_exception(at: AppTest):
    if at.exception:
        raise at.exception[0].value


def _upload_both(at: AppTest, coord_name, coord_content, annot_name, annot_content):
    at.run()
    _widget(at, "file_uploader", "coord_file").set_value(
        (coord_name, coord_content, "application/octet-stream")
    )
    _widget(at, "file_uploader", "annot_file").set_value(
        (annot_name, annot_content, "application/octet-stream")
    )
    at.run()
    _assert_no_exception(at)
    return at


def _press_run(at: AppTest) -> AppTest:
    _widget(at, "button", "run_button").set_value(True)
    at.run()
    _assert_no_exception(at)
    return at


class TestCustomAnnotationCoordinateSystem:
    def test_one_based_declaration_shifts_annotation_and_matches(self):
        at = _upload_both(
            _app(), "q.bed", COORD_BED, "a.tsv", ANNOT_CUSTOM_TSV
        )
        _widget(at, "selectbox", "annot_system").set_value(ONE_BASED)
        at.run()
        _assert_no_exception(at)

        # The parsed/normalized annotation frame the engine will receive
        # is canonical [99, 200) — the declaration is applied exactly
        # once, at parse time.
        annot_df = at.session_state["annot_parse"]["df"]
        assert annot_df[["chr", "start", "end"]].values.tolist() == [
            ["chr1", 99, 200]
        ]

        at = _press_run(at)
        result = at.session_state["result_df"]
        # [99, 200) vs [99, 100): one-base positive overlap.
        assert len(result) == 1
        assert bool(result["has_overlap"].iloc[0]) is True
        assert int(result["annot_start"].iloc[0]) == 99
        assert int(result["annot_end"].iloc[0]) == 200

    def test_zero_based_declaration_keeps_annotation_and_touches_only(self):
        at = _upload_both(
            _app(), "q.bed", COORD_BED, "a.tsv", ANNOT_CUSTOM_TSV
        )
        # Default declaration (Auto-detect -> custom default 0-based):
        # the annotation stays [100, 200), which only touches [99, 100).
        annot_df = at.session_state["annot_parse"]["df"]
        assert annot_df[["chr", "start", "end"]].values.tolist() == [
            ["chr1", 100, 200]
        ]

        at = _press_run(at)
        result = at.session_state["result_df"]
        assert len(result) == 1
        assert bool(result["has_overlap"].iloc[0]) is False
        # Left join: the unmatched query row is preserved exactly once.
        assert int(result["coord_start"].iloc[0]) == 99

    def test_changing_annotation_system_invalidates_parse_and_result_state(self):
        at = _upload_both(
            _app(), "q.bed", COORD_BED, "a.tsv", ANNOT_CUSTOM_TSV
        )
        at = _press_run(at)
        assert "result_df" in at.session_state
        # 0-based interpretation: touching only, no match.
        assert not at.session_state["result_df"]["has_overlap"].any()

        # Switch the annotation coordinate declaration WITHOUT re-uploading:
        # stored results must be invalidated...
        _widget(at, "selectbox", "annot_system").set_value(ONE_BASED)
        at.run()
        _assert_no_exception(at)
        assert "result_df" not in at.session_state

        # ...and the re-parse must use the new declaration (the cached
        # 0-based frame must not be served for the new selection).
        assert at.session_state["annot_parse"]["df"][
            ["chr", "start", "end"]
        ].values.tolist() == [["chr1", 99, 200]]

        # A fresh run under the new declaration now matches.
        at = _press_run(at)
        result = at.session_state["result_df"]
        assert len(result) == 1
        assert bool(result["has_overlap"].iloc[0]) is True


class TestCustomAnnotationCoordinateSystem:
    def test_one_based_declaration_shifts_annotation_and_matches(self):
        at = _upload_both(
            _app(), "q.bed", COORD_BED, "a.tsv", ANNOT_CUSTOM_TSV
        )
        _widget(at, "selectbox", "annot_system").set_value(ONE_BASED)
        at.run()
        _assert_no_exception(at)

        # The parsed/normalized annotation frame the engine will receive
        # is canonical [99, 200) — the declaration is applied exactly
        # once, at parse time.
        annot_df = at.session_state["annot_parse"]["df"]
        assert annot_df[["chr", "start", "end"]].values.tolist() == [
            ["chr1", 99, 200]
        ]

        at = _press_run(at)
        result = at.session_state["result_df"]
        # [99, 200) vs [99, 100): one-base positive overlap.
        assert len(result) == 1
        assert bool(result["has_overlap"].iloc[0]) is True
        assert int(result["annot_start"].iloc[0]) == 99
        assert int(result["annot_end"].iloc[0]) == 200

    def test_zero_based_declaration_keeps_annotation_and_touches_only(self):
        at = _upload_both(
            _app(), "q.bed", COORD_BED, "a.tsv", ANNOT_CUSTOM_TSV
        )
        # Default declaration (Auto-detect -> custom default 0-based):
        # the annotation stays [100, 200), which only touches [99, 100).
        annot_df = at.session_state["annot_parse"]["df"]
        assert annot_df[["chr", "start", "end"]].values.tolist() == [
            ["chr1", 100, 200]
        ]

        at = _press_run(at)
        result = at.session_state["result_df"]
        assert len(result) == 1
        assert bool(result["has_overlap"].iloc[0]) is False
        # Left join: the unmatched query row is preserved exactly once.
        assert int(result["coord_start"].iloc[0]) == 99

    def test_changing_annotation_system_invalidates_parse_and_result_state(self):
        at = _upload_both(
            _app(), "q.bed", COORD_BED, "a.tsv", ANNOT_CUSTOM_TSV
        )
        at = _press_run(at)
        assert "result_df" in at.session_state
        # 0-based interpretation: touching only, no match.
        assert not at.session_state["result_df"]["has_overlap"].any()

        # Switch the annotation coordinate declaration WITHOUT re-uploading:
        # stored results must be invalidated...
        _widget(at, "selectbox", "annot_system").set_value(ONE_BASED)
        at.run()
        _assert_no_exception(at)
        assert "result_df" not in at.session_state

        # ...and the re-parse must use the new declaration (the cached
        # 0-based frame must not be served for the new selection).
        assert at.session_state["annot_parse"]["df"][
            ["chr", "start", "end"]
        ].values.tolist() == [["chr1", 99, 200]]

        # A fresh run under the new declaration now matches.
        at = _press_run(at)
        result = at.session_state["result_df"]
        assert len(result) == 1
        assert bool(result["has_overlap"].iloc[0]) is True


