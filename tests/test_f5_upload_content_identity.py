"""
Task B / F5 regression: upload identity must reflect file CONTENT.

Pre-fix identity was (filename, size). Two uploads with the same
filename and the same byte length but different genomic coordinates
were treated as the same input: the old parsed frame and the old
annotation result stayed visible after the replacement, and a re-run
used the stale content.

Hand-computed scenario (both files are 16 bytes, same name "q.bed"):

    first:  chr1  100  200  q1   -> canonical [100, 200)
    second: chr1  700  800  q1   -> canonical [700, 800)
    annotation GFF3: chr1 gene 700-900 (1-based) -> canonical [699, 900)

  * first  -> [100, 200) only touches/misses [699, 900) -> NO overlap
  * second -> [700, 800) overlaps [699, 900)            -> overlap

Tested through the real Streamlit state path (AppTest):
upload first -> run -> verify; replace with second (same name/size)
without re-running -> the stored parse and result state must be
invalidated; re-run -> the result must correspond to the SECOND file.
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_ENTRYPOINT = Path(__file__).parent.parent / "streamlit_app" / "streamlit_app.py"

Q1 = b"chr1\t100\t200\tq1\n"
Q2 = b"chr1\t700\t800\tq1\n"
ANNOT_GFF = (
    b"##gff-version 3\n"
    b"chr1\tsrc\tgene\t700\t900\t.\t+\t.\tID=g1;Name=G1\n"
)


def test_fixture_files_are_genuinely_ambiguous_to_name_and_size():
    # The whole point of this regression: the two uploads are identical
    # in every field the pre-fix identity considered.
    assert Q1 != Q2
    assert len(Q1) == len(Q2) == 16


def _widget(at: AppTest, etype: str, key: str):
    for element in at.get(etype):
        if getattr(element, "key", None) == key:
            return element
    raise KeyError(f"no {etype} with key {key!r}")


def _assert_no_exception(at: AppTest):
    if at.exception:
        raise at.exception[0].value


def _press_run(at: AppTest) -> AppTest:
    _widget(at, "button", "run_button").set_value(True)
    at.run()
    _assert_no_exception(at)
    return at


def _captions(at: AppTest):
    return [c.value for c in at.get("caption")]


def test_same_name_same_size_different_content_invalidates_state():
    at = AppTest.from_file(str(APP_ENTRYPOINT), default_timeout=120)
    at.run()
    _widget(at, "file_uploader", "coord_file").set_value(
        ("q.bed", Q1, "application/octet-stream")
    )
    _widget(at, "file_uploader", "annot_file").set_value(
        ("a.gff3", ANNOT_GFF, "application/octet-stream")
    )
    at.run()
    _assert_no_exception(at)

    # 1) First upload: [100, 200) vs [699, 900) -> no positive overlap.
    at = _press_run(at)
    result = at.session_state["result_df"]
    assert len(result) == 1
    assert bool(result["has_overlap"].iloc[0]) is False
    assert int(result["coord_start"].iloc[0]) == 100

    # 2) Replace the upload: SAME filename, SAME byte length, different
    #    coordinates.
    _widget(at, "file_uploader", "coord_file").set_value(
        ("q.bed", Q2, "application/octet-stream")
    )
    at.run()
    _assert_no_exception(at)

    # 3) The stored parsed frame must already reflect the NEW content
    #    (the content-derived identity changed).
    assert at.session_state["coord_parse"]["df"][
        ["chr", "start", "end"]
    ].values.tolist() == [["chr1", 700, 800]]

    # 4) The stored result state must be invalidated: the previous
    #    result belonged to a different file and must not be displayed
    #    as if it belonged to this one.
    assert at.session_state.get("result_df") is None

    # 5) Re-run: the result must correspond to the SECOND file:
    #    [700, 800) overlaps [699, 900).
    at = _press_run(at)
    result = at.session_state["result_df"]
    assert len(result) == 1
    assert bool(result["has_overlap"].iloc[0]) is True
    assert int(result["coord_start"].iloc[0]) == 700
    assert int(result["coord_end"].iloc[0]) == 800


def test_annotation_side_content_change_also_invalidates():
    # The same content-identity rule must apply to the annotation upload:
    # same filename + same size, different annotation coordinates, must
    # not keep the stale annotation frame or result.
    at = AppTest.from_file(str(APP_ENTRYPOINT), default_timeout=120)
    at.run()
    _widget(at, "file_uploader", "coord_file").set_value(
        ("q.bed", b"chr1\t100\t200\tq1\n", "application/octet-stream")
    )
    _widget(at, "file_uploader", "annot_file").set_value(
        ("a.gff3",
         b"##gff-version 3\n"
         b"chr1\tsrc\tgene\t100\t200\t.\t+\t.\tID=g1;Name=G1\n",
         "application/octet-stream")
    )
    at.run()
    _assert_no_exception(at)
    at = _press_run(at)
    result = at.session_state["result_df"]
    assert bool(result["has_overlap"].iloc[0]) is True
    assert int(result["annot_start"].iloc[0]) == 99

    # Same name, same byte length, different coordinates: gene 700-900.
    _widget(at, "file_uploader", "annot_file").set_value(
        ("a.gff3",
         b"##gff-version 3\n"
         b"chr1\tsrc\tgene\t700\t900\t.\t+\t.\tID=g1;Name=G1\n",
         "application/octet-stream")
    )
    at.run()
    _assert_no_exception(at)

    assert at.session_state["annot_parse"]["df"][
        ["chr", "start", "end"]
    ].values.tolist() == [["chr1", 699, 900]]
    assert at.session_state.get("result_df") is None

    at = _press_run(at)
    result = at.session_state["result_df"]
    assert len(result) == 1
    assert bool(result["has_overlap"].iloc[0]) is False