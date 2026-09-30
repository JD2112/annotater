"""
Task A / F4 regression: coordinate-system precedence.

Maintainer-resolved policy (2025-06):

- Known format by authoritative extension (.bed, .gff, .gff3, .gtf,
  .vcf): the format specification's coordinate system is authoritative;
  a user coordinate declaration must NOT reinterpret the file.
- Extension-neutral files (.tsv, .txt, .csv, no extension): an explicit
  user coordinate declaration takes precedence over content sniffing;
  Auto-detect keeps the sniffed semantics.

Hand-computed fixture (extension-neutral, headerless, BED-like):

    chr1<TAB>100<TAB>200        (.tsv)

  * explicit 1-based  -> treated as a 1-based table [100, 200]
                          = canonical [99, 200)
  * explicit 0-based  -> canonical [100, 200)
  * Auto-detect       -> sniffed as BED -> canonical [100, 200)

The AppTest proves the UI/state behavior: changing the declaration of an
extension-neutral file invalidates the cached parsed frame and any stored
result whose coordinate interpretation changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from streamlit_app.core import FormatDetector
from streamlit_app.core.normalization import (
    coordinate_system_for,
    extension_authoritative_for,
    parse_and_normalize,
)

APP_ENTRYPOINT = Path(__file__).parent.parent / "streamlit_app" / "streamlit_app.py"

TSV_CONTENT = b"chr1\t100\t200\n"
ANNOT_GFF = (
    b"##gff-version 3\n"
    b"chr1\tsrc\tgene\t90\t110\t.\t+\t.\tID=g1;Name=G1\n"
)

AUTO_DETECT = "Auto-detect"
ZERO_BASED = "0-based (BED)"
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


class TestExtensionNeutralPrecedence:
    """Extension-neutral (.tsv) files: explicit declaration > sniffing."""

    def test_explicit_1_based_overrides_sniffed_bed(self, tmp_path):
        # Fails on the pre-F4 state: the declaration was silently
        # ignored and the sniffed BED system (0-based) was used.
        tsv = tmp_path / "regions.tsv"
        tsv.write_bytes(TSV_CONTENT)
        assert FormatDetector.detect(str(tsv)) == "bed"
        out = parse_and_normalize(str(tsv), declared_system="1-based")
        assert out[["chr", "start", "end"]].values.tolist() == [
            ["chr1", 99, 200]
        ]

    def test_explicit_0_based_keeps_canonical_interval(self, tmp_path):
        tsv = tmp_path / "regions.tsv"
        tsv.write_bytes(TSV_CONTENT)
        out = parse_and_normalize(str(tsv), declared_system="0-based")
        assert out[["chr", "start", "end"]].values.tolist() == [
            ["chr1", 100, 200]
        ]

    def test_auto_detect_retains_sniffed_bed_semantics(self, tmp_path):
        tsv = tmp_path / "regions.tsv"
        tsv.write_bytes(TSV_CONTENT)
        out = parse_and_normalize(str(tsv))
        assert out[["chr", "start", "end"]].values.tolist() == [
            ["chr1", 100, 200]
        ]

    def test_explicit_declaration_applies_to_sniffed_gff3_too(self, tmp_path):
        # Extension-neutral file sniffed as GFF3: an explicit 0-based
        # declaration wins over the sniffed 1-based system (policy B),
        # symmetric with the BED-like case.
        tsv = tmp_path / "features.tsv"
        tsv.write_bytes(b"chrA\tref\tgene\t5\t15\t.\t+\t.\tID=g1\n")
        assert FormatDetector.detect(str(tsv)) == "gff"
        out = parse_and_normalize(str(tsv), declared_system="0-based")
        assert out[["chr", "start", "end"]].values.tolist() == [
            ["chrA", 5, 15]
        ]
        default = parse_and_normalize(str(tsv))
        assert default[["chr", "start", "end"]].values.tolist() == [
            ["chrA", 4, 15]
        ]


class TestKnownFormatExtensionAuthority:
    """Authoritative extensions: the format specification wins."""

    def test_bed_extension_ignores_contradictory_declaration(self, tmp_path):
        bed = tmp_path / "regions.bed"
        bed.write_bytes(TSV_CONTENT)
        out = parse_and_normalize(str(bed), declared_system="1-based")
        assert out[["chr", "start", "end"]].values.tolist() == [
            ["chr1", 100, 200]
        ]

    @pytest.mark.parametrize(
        ("name", "content", "expected"),
        [
            (
                "f.gff3",
                b"##gff-version 3\nchrA\tref\tgene\t5\t15\t.\t+\t.\tID=g1\n",
                ["chrA", 4, 15],
            ),
            (
                "f.gtf",
                b'chrA\tsrc\tgene\t5\t15\t.\t+\t.\tgene_id "g1";\n',
                ["chrA", 4, 15],
            ),
            (
                "f.vcf",
                b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
                b"chrA\t100\t.\tA\tG\t.\tPASS\t.\n",
                ["chrA", 99, 100],
            ),
        ],
    )
    def test_one_based_formats_ignores_contradictory_declaration(
        self, tmp_path, name, content, expected
    ):
        path = tmp_path / name
        path.write_bytes(content)
        out = parse_and_normalize(str(path), declared_system="0-based")
        assert out[["chr", "start", "end"]].values.tolist() == [expected]


class TestSystemResolutionUnits:
    def test_authoritative_extension_keeps_fixed_system(self):
        assert (
            coordinate_system_for("bed", "1-based", extension=".bed")
            == "0-based"
        )
        assert (
            coordinate_system_for("gff", "0-based", extension=".gff3")
            == "1-based"
        )
        assert (
            coordinate_system_for("vcf", "0-based", extension=".vcf")
            == "1-based"
        )

    def test_extension_neutral_honors_declaration(self):
        assert coordinate_system_for("bed", "1-based", extension=".tsv") == "1-based"
        assert coordinate_system_for("bed", "0-based", extension=".tsv") == "0-based"
        # Auto-detect (no declaration) keeps the sniffed semantics.
        assert coordinate_system_for("bed", None, extension=".tsv") == "0-based"
        # No extension at all is also extension-neutral.
        assert coordinate_system_for("bed", "1-based", extension="") == "1-based"

    def test_legacy_callers_without_extension_keep_fixed_system(self):
        # Direct callers without file context: known formats stay fixed.
        assert coordinate_system_for("bed", "1-based") == "0-based"
        assert coordinate_system_for("gff", "0-based") == "1-based"

    def test_extension_authoritative_for(self):
        assert extension_authoritative_for("bed", ".bed")
        assert extension_authoritative_for("bed", ".BED")
        assert extension_authoritative_for("gff", ".gff3")
        assert extension_authoritative_for("gtf", ".gtf")
        assert not extension_authoritative_for("bed", ".tsv")
        assert not extension_authoritative_for("bed", "")
        assert not extension_authoritative_for("custom", ".tsv")


class TestAppDeclarationInvalidation:
    """UI/state: changing the declaration of an extension-neutral file
    invalidates the cached parsed frame and stored results."""

    def _upload(self, at: AppTest) -> AppTest:
        at.run()
        _widget(at, "file_uploader", "coord_file").set_value(
            ("regions.tsv", TSV_CONTENT, "application/octet-stream")
        )
        _widget(at, "file_uploader", "annot_file").set_value(
            ("annot.gff3", ANNOT_GFF, "application/octet-stream")
        )
        at.run()
        _assert_no_exception(at)
        return at

    def _press_run(self, at: AppTest) -> AppTest:
        _widget(at, "button", "run_button").set_value(True)
        at.run()
        _assert_no_exception(at)
        return at

    def test_declaration_change_invalidates_frame_and_result(self):
        at = self._upload(_app())

        # Auto-detect: the BED-like .tsv is sniffed as BED -> [100, 200).
        # Annotation GFF 90-110 (1-based) -> canonical [89, 110).
        assert at.session_state["coord_parse"]["df"][
            ["chr", "start", "end"]
        ].values.tolist() == [["chr1", 100, 200]]
        at = self._press_run(at)
        result = at.session_state["result_df"]
        assert bool(result["has_overlap"].iloc[0]) is True
        assert int(result["coord_start"].iloc[0]) == 100

        # Explicit 0-based: same canonical interval, explicit intent.
        _widget(at, "selectbox", "coord_system").set_value(ZERO_BASED)
        at.run()
        _assert_no_exception(at)
        at = self._press_run(at)
        result = at.session_state["result_df"]
        assert int(result["coord_start"].iloc[0]) == 100

        # Explicit 1-based (without re-uploading): the cached frame and
        # the stored result must be invalidated and the declaration
        # honored: [100, 200] 1-based -> canonical [99, 200).
        _widget(at, "selectbox", "coord_system").set_value(ONE_BASED)
        at.run()
        _assert_no_exception(at)
        assert at.session_state["coord_parse"]["df"][
            ["chr", "start", "end"]
        ].values.tolist() == [["chr1", 99, 200]]
        at = self._press_run(at)
        result = at.session_state["result_df"]
        assert bool(result["has_overlap"].iloc[0]) is True
        assert int(result["coord_start"].iloc[0]) == 99
        assert int(result["coord_end"].iloc[0]) == 200