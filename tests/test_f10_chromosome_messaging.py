"""
Task B / F10 regression: chromosome-conversion messaging must match the
converter's actual capability.

The converter only maps between UCSC-style and Ensembl-style
identifiers. NCBI-style identifiers (NC_000001.11) have NO mapping to
either style: convert() returns them unchanged. Pre-fix,
find_mismatches reported can_auto_convert=True for ANY pair of
differing detected styles (including NCBI vs UCSC), so the app
standardized "both files to UCSC style" as a no-op and then displayed
"Chromosome IDs standardized." — a false success claim — while the
result silently contained no matches.

Required behavior covered here:

1. UCSC <-> Ensembl still auto-converts (behavior unchanged) and shows
   the standardization notice.
2. An unsupported pair (NCBI vs UCSC) never shows a success/
   standardization caption.
3. For an unsupported pair the identifiers are left unchanged.
4. When no shared chromosome identifiers remain after any conversion,
   a clear warning is shown.
5. A valid overlap produces NO false warning.
6. The behavior is identical for both backends.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from streamlit_app.core.chromosome import ChromosomeMapper

APP_ENTRYPOINT = Path(__file__).parent.parent / "streamlit_app" / "streamlit_app.py"

COORD_UCSC = b"chr1\t100\t200\tq1\n"
COORD_NCBII = b"NC_000001.11\t100\t200\tq1\n"
ANNOT_ENSEMBL = (
    b"##gff-version 3\n"
    b"1\tsrc\tgene\t150\t250\t.\t+\t.\tID=g1;Name=G1\n"
)
ANNOT_UCSC = (
    b"##gff-version 3\n"
    b"chr1\tsrc\tgene\t150\t250\t.\t+\t.\tID=g1;Name=G1\n"
)


# ---------------------------------------------------------------------------
# Unit level: capability of the converter
# ---------------------------------------------------------------------------

def test_conversion_supported_matrix():
    m = ChromosomeMapper()
    # The only pair with an actual mapping is UCSC <-> Ensembl.
    assert m.conversion_supported("ucsc", "ensembl") is True
    assert m.conversion_supported("ensembl", "ucsc") is True
    # NCBI-style identifiers have no mapping to any style.
    assert m.conversion_supported("ncbi", "ucsc") is False
    assert m.conversion_supported("ncbi", "ensembl") is False
    # Missing/unknown styles and identical styles: nothing to convert.
    assert m.conversion_supported(None, "ucsc") is False
    assert m.conversion_supported("unknown", "ucsc") is False
    assert m.conversion_supported("ucsc", "ucsc") is False


def test_find_mismatches_ncbi_vs_ucsc_cannot_auto_convert():
    m = ChromosomeMapper()
    info = m.find_mismatches(["NC_000001.11", "NC_000002.11"], ["chr1", "chr2"])
    assert info["styles_match"] is False
    assert info["can_auto_convert"] is False


def test_find_mismatches_ucsc_vs_ensembl_can_still_auto_convert():
    m = ChromosomeMapper()
    info = m.find_mismatches(["chr1"], ["1"])
    assert info["styles_match"] is False
    assert info["can_auto_convert"] is True


def test_ncbi_identifiers_are_never_rewritten():
    m = ChromosomeMapper()
    df = pd.DataFrame({
        "chr": ["NC_000001.11", "chrM"],
        "start": [0, 0],
        "end": [10, 10],
    })
    result, source, _ = m.standardize_dataframe(df, "chr", "ucsc")
    # UCSC rows are kept, NCBI rows have no mapping and stay unchanged.
    assert result["chr"].tolist() == ["NC_000001.11", "chrM"]


# ---------------------------------------------------------------------------
# App level: user-visible messaging
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


def _captions(at: AppTest):
    return [c.value.lower() for c in at.get("caption")]


def _warnings(at: AppTest):
    return [w.value.lower() for w in at.get("warning")]


def _upload_and_run(coord_bytes, annot_bytes, engine=None):
    at = AppTest.from_file(str(APP_ENTRYPOINT), default_timeout=120)
    at.run()
    if engine is not None:
        _widget(at, "radio", "engine").set_value(engine)
    _widget(at, "file_uploader", "coord_file").set_value(
        ("q.bed", coord_bytes, "application/octet-stream")
    )
    _widget(at, "file_uploader", "annot_file").set_value(
        ("a.gff3", annot_bytes, "application/octet-stream")
    )
    at.run()
    _assert_no_exception(at)
    return _press_run(at)


def test_ucsc_vs_ensembl_still_auto_converts_and_matches():
    at = _upload_and_run(COORD_UCSC, ANNOT_ENSEMBL)
    # Behavior unchanged: both standardized to UCSC and an overlap found.
    assert any("standardized" in c for c in _captions(at))
    result = at.session_state["result_df"]
    assert len(result) == 1
    assert bool(result["has_overlap"].iloc[0]) is True


def test_ncbi_vs_ucsc_does_not_claim_successful_conversion():
    at = _upload_and_run(COORD_NCBII, ANNOT_UCSC)
    # No success/standardization claim may be shown for an unsupported
    # style pair; a warning must explain the situation instead.
    assert not any("standardized" in c for c in _captions(at))
    assert _warnings(at)


def test_ncbi_identifiers_left_unchanged_in_result():
    at = _upload_and_run(COORD_NCBII, ANNOT_UCSC)
    result = at.session_state["result_df"]
    # The query identifier must still be the original NCBI id: nothing
    # was (or pretended to be) converted.
    assert result["coord_chr"].iloc[0] == "NC_000001.11"
    assert bool(result["has_overlap"].iloc[0]) is False


def test_no_shared_identifiers_warning_is_shown():
    at = _upload_and_run(COORD_NCBII, ANNOT_UCSC)
    assert any(
        "no shared chromosome identifiers" in w for w in _warnings(at)
    ), f"warnings were: {[w for w in _warnings(at)]}"


def test_no_false_warning_when_valid_overlap_exists():
    at = _upload_and_run(COORD_UCSC, ANNOT_UCSC)
    assert not any(
        "no shared chromosome identifiers" in w for w in _warnings(at)
    )
    result = at.session_state["result_df"]
    assert bool(result["has_overlap"].iloc[0]) is True


def test_unsupported_pair_behaves_identically_on_polars_bio_engine():
    at = _upload_and_run(COORD_NCBII, ANNOT_UCSC, engine="Polars-Bio")
    assert not any("standardized" in c for c in _captions(at))
    assert any("no shared chromosome identifiers" in w for w in _warnings(at))
    result = at.session_state["result_df"]
    assert result["coord_chr"].iloc[0] == "NC_000001.11"
    assert bool(result["has_overlap"].iloc[0]) is False