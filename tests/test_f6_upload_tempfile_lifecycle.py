"""
Task B / F6 regression: uploaded temp files must be lifecycle-managed.

Requirements covered:

1. A successful upload/parse leaves NO new files in the configured temp
   dir (they are deleted immediately after parsing).
2. A parse failure leaves NO new files either.
3. Two uploads with the same user-visible filename get distinct
   temporary paths (no collision/overwrite).
4. A user-controlled filename (including path separators) cannot
   determine the temporary filesystem path: only the file extension is
   kept, the file is created directly in the configured temp dir, and
   extension-based format detection still works.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from streamlit_app.config import Settings
from streamlit_app.core import FormatDetector
from streamlit_app.utils import save_uploaded_file

APP_ENTRYPOINT = Path(__file__).parent.parent / "streamlit_app" / "streamlit_app.py"


class _FakeUpload:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


def _temp_dir_listing() -> list[str]:
    d = Path(Settings.TEMP_DIR)
    if not d.exists():
        return []
    return sorted(p.name for p in d.iterdir())


# ---------------------------------------------------------------------------
# 3 + 4: helper-level path safety
# ---------------------------------------------------------------------------

def test_two_same_name_uploads_get_distinct_temp_paths(tmp_path):
    # Pre-fix: the path was "{second-resolution timestamp}_{user name}";
    # two same-named uploads within the same second produced the SAME
    # path and overwrote each other.
    p1 = save_uploaded_file(_FakeUpload("regions.bed", b"chr1\t1\t2\n"), tmp_path)
    p2 = save_uploaded_file(_FakeUpload("regions.bed", b"chr1\t1\t2\n"), tmp_path)
    assert p1 != p2
    assert p1.exists() and p2.exists()
    assert p1.read_bytes() == b"chr1\t1\t2\n"


def test_user_filename_components_do_not_affect_temp_path(tmp_path):
    # Path separators in the user-visible name must not push the temp
    # file outside the temp dir or crash the write.
    p = save_uploaded_file(_FakeUpload("a/b/evil.bed", b"chr1\t1\t2\n"), tmp_path)
    assert p.parent == Path(tmp_path)
    assert p.exists()
    assert p.read_bytes() == b"chr1\t1\t2\n"


def test_user_filename_not_embedded_but_extension_preserved(tmp_path):
    p = save_uploaded_file(_FakeUpload("my precious regions.bed", b"chr1\t1\t2\n"), tmp_path)
    # Only the extension may carry over from the user name.
    assert p.suffix == ".bed"
    assert "regions" not in p.name
    # Extension-based format detection must still work on the temp path.
    assert FormatDetector.detect(str(p)) == "bed"


# ---------------------------------------------------------------------------
# 1 + 2: app-level lifecycle (success and failure leave no files)
# ---------------------------------------------------------------------------

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


COORD_BED = b"chr1\t100\t200\tq1\n"
ANNOT_GFF = (
    b"##gff-version 3\n"
    b"chr1\tsrc\tgene\t150\t250\t.\t+\t.\tID=g1;Name=G1\n"
)


def test_successful_upload_and_parse_leave_no_new_temp_files():
    before = _temp_dir_listing()
    at = AppTest.from_file(str(APP_ENTRYPOINT), default_timeout=120)
    at.run()
    _widget(at, "file_uploader", "coord_file").set_value(
        ("q.bed", COORD_BED, "application/octet-stream")
    )
    _widget(at, "file_uploader", "annot_file").set_value(
        ("a.gff3", ANNOT_GFF, "application/octet-stream")
    )
    at.run()
    _assert_no_exception(at)
    at = _press_run(at)

    # Sanity: the run actually worked (files WERE parsed).
    assert at.session_state["coord_parse"]["df"] is not None
    assert at.session_state["result_df"] is not None

    # No file survives the successful upload/parse: the temp dir is
    # exactly as it was before this test's uploads.
    assert _temp_dir_listing() == before


def test_failed_parse_leaves_no_new_temp_files():
    before = _temp_dir_listing()
    at = AppTest.from_file(str(APP_ENTRYPOINT), default_timeout=120)
    at.run()
    # Invalid BED: non-numeric start/end.
    _widget(at, "file_uploader", "coord_file").set_value(
        ("bad.bed", b"chr1\tnotanum\t200\tq1\n", "application/octet-stream")
    )
    _widget(at, "file_uploader", "annot_file").set_value(
        ("a.gff3", ANNOT_GFF, "application/octet-stream")
    )
    at.run()
    _assert_no_exception(at)

    # The malformed query is reported as a parse error at render time
    # (the run button is disabled while there is no valid query parse).
    assert at.session_state.get("coord_parse") is None
    errors = [e.value for e in at.get("error")]
    assert any("could not parse" in e.lower() for e in errors)

    # Nothing was left behind in the configured temp dir: the failed
    # upload/parse cleaned up its transient file too.
    assert _temp_dir_listing() == before