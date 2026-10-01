"""
Task I4: extension-neutral input detection and '#'-prefixed custom headers.

- F-NEW-08: a custom table whose header line starts with '#' lost its
  header (read as a comment) and its first data record (promoted to the
  header).
- FormatDetector sniffed GFF/GTF only for four feature-type names, so
  extension-neutral files starting with mRNA / lnc_RNA / ... were
  classified 'custom'. Detection is now structural.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from streamlit_app.core import FormatDetector
from streamlit_app.core.normalization import parse_and_normalize
from streamlit_app.core.parsers import CustomParser
from streamlit_app.core.schema import MalformedFileError

APP_ENTRYPOINT = Path(__file__).parent.parent / "streamlit_app" / "streamlit_app.py"

UCSC_COLUMNS = ["bin", "name", "chrom", "start", "end"]
UCSC_ROWS = [
    ["585", "NM_1", "chr1", "100", "200"],
    ["586", "NM_2", "chr1", "300", "400"],
    ["587", "NM_3", "chr2", "10", "20"],
]


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def _tsv(*rows):
    return "".join("\t".join(r) + "\n" for r in rows)


UCSC_BODY = _tsv(*UCSC_ROWS)


# ---------------------------------------------------------------------------
# '#' header
# ---------------------------------------------------------------------------

class TestHashPrefixedCustomHeader:
    def test_header_preserved_and_no_row_lost(self, tmp_path):
        path = _write(tmp_path, "t.tsv", "#bin\tname\tchrom\tstart\tend\n" + UCSC_BODY)
        assert FormatDetector.detect(path) == "custom"
        df = CustomParser.parse(path)
        assert list(df.columns) == UCSC_COLUMNS
        assert df.values.tolist() == UCSC_ROWS

    def test_ordinary_comment_before_hash_header(self, tmp_path):
        path = _write(
            tmp_path, "t.tsv",
            "# exported from UCSC\n#bin\tname\tchrom\tstart\tend\n" + UCSC_BODY,
        )
        df = CustomParser.parse(path)
        assert list(df.columns) == UCSC_COLUMNS
        assert df.values.tolist() == UCSC_ROWS

    def test_multiple_comments_before_header(self, tmp_path):
        path = _write(
            tmp_path, "t.tsv",
            "# line one\n## line two\n# a b c\n\n"
            "#bin\tname\tchrom\tstart\tend\n" + UCSC_BODY,
        )
        df = CustomParser.parse(path)
        assert list(df.columns) == UCSC_COLUMNS
        assert len(df) == 3

    def test_comment_after_header_remains_comment(self, tmp_path):
        path = _write(
            tmp_path, "t.tsv",
            "#bin\tname\tchrom\tstart\tend\n" + UCSC_BODY
            + "# trailing note\n" + _tsv(["588", "NM_4", "chr3", "1", "2"]),
        )
        df = CustomParser.parse(path)
        assert list(df.columns) == UCSC_COLUMNS
        assert len(df) == 4
        assert df.iloc[-1].tolist() == ["588", "NM_4", "chr3", "1", "2"]

    def test_marker_followed_by_space(self, tmp_path):
        path = _write(tmp_path, "t.tsv", "# bin\tname\tchrom\tstart\tend\n" + UCSC_BODY)
        assert list(CustomParser.parse(path).columns) == UCSC_COLUMNS

    def test_comma_delimited(self, tmp_path):
        path = _write(
            tmp_path, "t.csv",
            "#bin,name,chrom,start,end\n"
            + "".join(",".join(r) + "\n" for r in UCSC_ROWS),
        )
        df = CustomParser.parse(path)
        assert list(df.columns) == UCSC_COLUMNS
        assert len(df) == 3

    def test_crlf_line_endings(self, tmp_path):
        path = tmp_path / "t.tsv"
        text = "#bin\tname\tchrom\tstart\tend\n" + UCSC_BODY
        path.write_bytes(text.replace("\n", "\r\n").encode())
        df = CustomParser.parse(str(path))
        assert list(df.columns) == UCSC_COLUMNS
        assert len(df) == 3

    def test_duplicate_header_names_mangled_like_pandas(self, tmp_path):
        path = _write(tmp_path, "t.tsv", "#a\ta\tb\n1\t2\t3\n")
        df = CustomParser.parse(path)
        assert list(df.columns) == ["a", "a.1", "b"]
        assert len(df) == 1

    def test_non_hash_header_unchanged(self, tmp_path):
        path = _write(tmp_path, "t.tsv", "bin\tname\tchrom\tstart\tend\n" + UCSC_BODY)
        df = CustomParser.parse(path)
        assert list(df.columns) == UCSC_COLUMNS
        assert df.values.tolist() == UCSC_ROWS

    def test_comment_then_plain_header_unchanged(self, tmp_path):
        # Same width, but F is a text header: the '#' line stays a comment.
        path = _write(
            tmp_path, "t.tsv",
            "# a\tb\tc\tstart\tend\nbin\tname\tchrom\tstart\tend\n" + UCSC_BODY,
        )
        df = CustomParser.parse(path)
        assert list(df.columns) == UCSC_COLUMNS
        assert len(df) == 3

    def test_prose_comment_of_different_width_is_comment(self, tmp_path):
        path = _write(
            tmp_path, "t.tsv",
            "# just a note\nbin\tname\tchrom\tstart\tend\n" + UCSC_BODY,
        )
        df = CustomParser.parse(path)
        assert list(df.columns) == UCSC_COLUMNS
        assert len(df) == 3

    def test_whitespace_delimited_is_never_reinterpreted(self, tmp_path):
        path = _write(
            tmp_path, "t.txt",
            "# note about file\nbin name chrom\n1 a chr1\n",
        )
        df = CustomParser.parse(path)
        assert list(df.columns) == ["bin", "name", "chrom"]
        assert len(df) == 1

    def test_double_hash_line_is_comment(self, tmp_path):
        path = _write(
            tmp_path, "t.tsv",
            "##bin\tname\tchrom\tstart\tend\nbin\tname\tchrom\tstart\tend\n" + UCSC_BODY,
        )
        df = CustomParser.parse(path)
        assert list(df.columns) == UCSC_COLUMNS
        assert len(df) == 3

    def test_ambiguous_hash_line_fails_explicitly(self, tmp_path):
        # Same width as the data rows, numeric tokens: neither a plausible
        # header nor safely a comment -> explicit error, no silent drop.
        path = _write(tmp_path, "t.tsv", "#1\t2\t3\n4\t5\t6\n7\t8\t9\n")
        with pytest.raises(MalformedFileError, match="ambiguous"):
            CustomParser.parse(path)

    def test_has_header_false_untouched(self, tmp_path):
        path = _write(tmp_path, "t.tsv", "#bin\tname\tchrom\tstart\tend\n" + UCSC_BODY)
        df = CustomParser.parse(path, has_header=False)
        assert df.values.tolist() == UCSC_ROWS

    def test_bed_shaped_hash_header_follows_bed_behavior(self, tmp_path):
        path = _write(
            tmp_path, "t.tsv",
            "#chrom\tstart\tend\tname\nchr1\t100\t200\tq1\nchr1\t300\t400\tq2\n",
        )
        assert FormatDetector.detect(path) == "bed"
        out = parse_and_normalize(path)
        assert len(out) == 2
        assert out[["chr", "start", "end"]].values.tolist() == [
            ["chr1", 100, 200], ["chr1", 300, 400]
        ]

    def test_track_and_browser_lines_still_unsupported_in_bed(self, tmp_path):
        path = _write(
            tmp_path, "t.bed",
            'track name="x"\nchr1\t100\t200\n',
        )
        with pytest.raises(MalformedFileError):
            parse_and_normalize(path)
        path = _write(tmp_path, "u.bed", "browser position chr1:1-100\nchr1\t100\t200\n")
        with pytest.raises(MalformedFileError):
            parse_and_normalize(path)


# ---------------------------------------------------------------------------
# Structural GFF/GTF detection
# ---------------------------------------------------------------------------

def _gff_row(ftype, attrs="ID=x1;Name=X"):
    return f"chr1\tsrc\t{ftype}\t101\t200\t.\t+\t.\t{attrs}\n"


def _gtf_row(ftype):
    return f'chr1\tsrc\t{ftype}\t101\t200\t.\t+\t.\tgene_id "g1"; transcript_id "t1";\n'


FIRST_TYPES = ["gene", "transcript", "mRNA", "lnc_RNA", "ncRNA", "exon", "CDS"]


class TestStructuralGffDetection:
    @pytest.mark.parametrize("ext", ["txt", "tsv", "csv", ""])
    @pytest.mark.parametrize("ftype", FIRST_TYPES)
    def test_gff3_first_feature_types(self, tmp_path, ftype, ext):
        name = f"f.{ext}" if ext else "f"
        path = _write(tmp_path, name, _gff_row(ftype))
        assert FormatDetector.detect(path) == "gff"

    @pytest.mark.parametrize("ftype", FIRST_TYPES)
    def test_gtf_first_feature_types(self, tmp_path, ftype):
        path = _write(tmp_path, "f.txt", _gtf_row(ftype))
        assert FormatDetector.detect(path) == "gtf"

    @pytest.mark.parametrize("ftype", FIRST_TYPES)
    def test_parse_and_normalize_keeps_every_row(self, tmp_path, ftype):
        path = _write(
            tmp_path, "f.txt",
            "##gff-version 3\n" + _gff_row(ftype) + _gff_row("exon", "ID=e1;Parent=x1"),
        )
        out = parse_and_normalize(path)
        assert len(out) == 2
        assert out["feature"].tolist() == [ftype, "exon"]
        # 1-based inclusive [101, 200] -> canonical [100, 200)
        assert out[["start", "end"]].iloc[0].tolist() == [100, 200]

    def test_unusual_feature_type_not_in_any_whitelist(self, tmp_path):
        path = _write(tmp_path, "f.tsv", _gff_row("polypeptide_region"))
        assert FormatDetector.detect(path) == "gff"

    def test_directive_with_dot_attributes(self, tmp_path):
        path = _write(
            tmp_path, "f.txt",
            "##gff-version 3\nchr1\tsrc\tmRNA\t1\t10\t.\t+\t.\t.\n",
        )
        assert FormatDetector.detect(path) == "gff"

    def test_known_extensions_unchanged(self, tmp_path):
        # Authoritative extension wins regardless of content.
        path = _write(tmp_path, "f.gff3", "chr1\ta\tb\n")
        assert FormatDetector.detect(path) == "gff"
        path = _write(tmp_path, "f.gtf", "chr1\ta\tb\n")
        assert FormatDetector.detect(path) == "gtf"


class TestFalsePositiveGuards:
    def test_generic_nine_column_table(self, tmp_path):
        path = _write(
            tmp_path, "t.tsv",
            _tsv(
                ["id", "name", "kind", "score", "label", "a", "b", "c", "note"],
                ["1x", "n1", "k", "5", "L", "a", "b", "c", "some free text"],
            ),
        )
        assert FormatDetector.detect(path) == "custom"

    def test_nine_columns_with_numeric_coordinate_slots_but_no_gff_shape(self, tmp_path):
        path = _write(
            tmp_path, "t.tsv",
            _tsv(["chr1", "geneA", "gene", "10", "20", "0.5", "up", "7", "free text"]),
        )
        assert FormatDetector.detect(path) == "custom"

    def test_nine_column_numeric_table(self, tmp_path):
        path = _write(
            tmp_path, "t.tsv",
            _tsv(["a", "b", "c", "1", "2", "3", "4", "5", "6"]),
        )
        assert FormatDetector.detect(path) == "custom"

    def test_gff_like_but_free_text_attributes(self, tmp_path):
        path = _write(
            tmp_path, "t.tsv",
            _tsv(["chr1", "x", "gene", "1", "9", ".", "+", ".", "just a note"]),
        )
        assert FormatDetector.detect(path) == "custom"

    def test_gff_like_wrong_column_count(self, tmp_path):
        path = _write(tmp_path, "t.tsv", "chr1\tsrc\tgene\t1\t9\t.\t+\t.\n")
        assert FormatDetector.detect(path) == "custom"

    def test_bed_like_with_extra_columns_stays_bed(self, tmp_path):
        path = _write(
            tmp_path, "t.tsv",
            _tsv(["chr1", "100", "200", "n", "0", "+", "100", "200", "0", "1", "100", "0"]),
        )
        assert FormatDetector.detect(path) == "bed"

    def test_vcf_like_content_is_not_gff(self, tmp_path):
        path = _write(
            tmp_path, "t.txt",
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
            "chr1\t100\t.\tA\tG\t50\tPASS\tDP=10\n",
        )
        assert FormatDetector.detect(path) != "gff"
        assert FormatDetector.detect(path) != "gtf"

    def test_unrelated_custom_header(self, tmp_path):
        path = _write(
            tmp_path, "t.tsv",
            "Gene stable ID\tGene name\tChromosome\tStart\tEnd\n"
            "ENSG1\tA\t1\t100\t200\n",
        )
        assert FormatDetector.detect(path) == "custom"


# ---------------------------------------------------------------------------
# Coordinate precedence + real app path
# ---------------------------------------------------------------------------

def _widget(at, etype, key):
    for element in at.get(etype):
        if getattr(element, "key", None) == key:
            return element
    raise KeyError(f"no {etype} with key {key!r}")


def _app():
    return AppTest.from_file(str(APP_ENTRYPOINT), default_timeout=120)


def _no_exception(at):
    if at.exception:
        raise at.exception[0].value


COORD_BED = b"chr1\t100\t200\tq1\n"
MRNA_TXT = (
    b"chr1\tsrc\tmRNA\t101\t200\t.\t+\t.\tID=m1;Parent=g1\n"
    b"chr1\tsrc\texon\t101\t150\t.\t+\t.\tID=e1;Parent=m1\n"
)
HASH_TSV = ("#bin\tname\tchrom\tstart\tend\n" + UCSC_BODY).encode()


class TestCoordinatePrecedence:
    def test_declaration_overrides_sniffed_mrna_gff(self, tmp_path):
        path = _write(tmp_path, "a.txt", MRNA_TXT.decode())
        assert FormatDetector.detect(path) == "gff"
        auto = parse_and_normalize(path)
        assert auto[["start", "end"]].iloc[0].tolist() == [100, 200]
        zero = parse_and_normalize(path, declared_system="0-based")
        assert zero[["start", "end"]].iloc[0].tolist() == [101, 200]
        assert len(auto) == len(zero) == 2

    def test_authoritative_extension_ignores_declaration(self, tmp_path):
        path = _write(tmp_path, "a.gff3", MRNA_TXT.decode())
        out = parse_and_normalize(path, declared_system="0-based")
        assert out[["start", "end"]].iloc[0].tolist() == [100, 200]

    def test_custom_table_stays_custom_under_declaration(self, tmp_path):
        path = _write(tmp_path, "c.tsv", "#bin\tname\tchrom\tstart\tend\n" + UCSC_BODY)
        with pytest.raises(ValueError, match="custom"):
            parse_and_normalize(path, declared_system="1-based")


class TestAppPath:
    def _upload(self, coord, annot):
        at = _app()
        at.run()
        _widget(at, "file_uploader", "coord_file").set_value(
            (coord[0], coord[1], "application/octet-stream")
        )
        _widget(at, "file_uploader", "annot_file").set_value(
            (annot[0], annot[1], "application/octet-stream")
        )
        at.run()
        _no_exception(at)
        return at

    def test_mrna_txt_reaches_gff_parser_and_keeps_rows(self):
        at = self._upload(("q.bed", COORD_BED), ("annot.txt", MRNA_TXT))
        parsed = at.session_state["annot_parse"]
        assert parsed["format"] == "gff"
        assert len(parsed["df"]) == 2
        assert parsed["df"][["start", "end"]].iloc[0].tolist() == [100, 200]

    def test_hash_header_custom_table_keeps_all_rows_in_app(self):
        at = self._upload(("q.bed", COORD_BED), ("ucsc.tsv", HASH_TSV))
        parsed = at.session_state["annot_parse"]
        assert parsed["format"] == "custom"
        assert list(parsed["df"].columns) == UCSC_COLUMNS
        assert len(parsed["df"]) == 3

    def test_hash_header_custom_query_keeps_all_rows_in_app(self):
        at = self._upload(("ucsc.tsv", HASH_TSV), ("annot.txt", MRNA_TXT))
        parsed = at.session_state["coord_parse"]
        assert parsed["format"] == "custom"
        assert list(parsed["df"].columns) == UCSC_COLUMNS
        assert len(parsed["df"]) == 3
