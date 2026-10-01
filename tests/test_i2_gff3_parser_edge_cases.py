"""
Task I2 — GFF3/GTF parser robustness (F-NEW-03, F-NEW-04).

F-NEW-03: the GFF3/GTF unknown-strand token ``?`` is treated as missing
(like ``.``); it never becomes a canonical strand value. Other
unsupported tokens are still rejected explicitly, and the BED / custom
canonical boundary is unchanged.

F-NEW-04: a ``##FASTA`` directive ends the annotation section (the
embedded sequence is ignored); an annotation record that is not exactly
9 tab-separated columns fails with ``MalformedFileError``, never an
opaque ``TypeError``.

Expected values are hand-written from the literal fixtures.
"""

from __future__ import annotations

import pandas as pd
import pytest

from streamlit_app.core import BedtoolsEngine, PolarsBioEngine
from streamlit_app.core.normalization import normalize_intervals, parse_and_normalize
from streamlit_app.core.schema import InvalidIntervalError, MalformedFileError

ENGINES = [
    pytest.param(BedtoolsEngine, id="bedtools"),
    pytest.param(PolarsBioEngine, id="polars-bio"),
]

HEADER = "##gff-version 3\n"


def _row(start, end, strand, attrs="ID=x", feature="gene"):
    return f"chr1\tsrc\t{feature}\t{start}\t{end}\t.\t{strand}\t.\t{attrs}\n"


def _write(tmp_path, text, name="a.gff3"):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def _strands(df):
    return [None if pd.isna(v) else v for v in df["strand"].tolist()]


# --- F-NEW-03: strand ------------------------------------------------------


class TestStrand:
    MIXED = (
        HEADER
        + _row(1, 10, "+", "ID=p")
        + _row(11, 20, "-", "ID=m")
        + _row(21, 30, ".", "ID=d")
        + _row(31, 40, "?", "ID=q")
    )

    @pytest.mark.parametrize(
        "token,expected", [("+", "+"), ("-", "-"), (".", None), ("?", None)]
    )
    def test_single_token(self, tmp_path, token, expected):
        df = parse_and_normalize(_write(tmp_path, HEADER + _row(1, 10, token)))
        assert _strands(df) == [expected]

    def test_mixed_file(self, tmp_path):
        df = parse_and_normalize(_write(tmp_path, self.MIXED))
        assert _strands(df) == ["+", "-", None, None]
        assert df["ID"].tolist() == ["p", "m", "d", "q"]
        assert df["start"].tolist() == [0, 10, 20, 30]

    def test_question_mark_is_not_canonical_strand(self, tmp_path):
        df = parse_and_normalize(_write(tmp_path, self.MIXED))
        assert "?" not in set(df["strand"].dropna())

    def test_gtf_unknown_strand(self, tmp_path):
        gtf = (
            'chr1\tsrc\tgene\t1\t10\t.\t+\t.\tgene_id "a";\n'
            'chr1\tsrc\tgene\t11\t20\t.\t?\t.\tgene_id "b";\n'
            'chr1\tsrc\tgene\t21\t30\t.\t.\t.\tgene_id "c";\n'
        )
        df = parse_and_normalize(_write(tmp_path, gtf, "a.gtf"))
        assert _strands(df) == ["+", None, None]
        assert df["gene_id"].tolist() == ["a", "b", "c"]

    @pytest.mark.parametrize("token", ["foo", "forward", "reverse", "1", "*"])
    def test_arbitrary_token_still_rejected(self, tmp_path, token):
        with pytest.raises(InvalidIntervalError, match="strand"):
            parse_and_normalize(_write(tmp_path, HEADER + _row(1, 10, token)))

    def test_bed_question_mark_still_rejected(self, tmp_path):
        path = _write(tmp_path, "chr1\t0\t10\tn\t0\t?\n", "a.bed")
        with pytest.raises(InvalidIntervalError, match="strand"):
            parse_and_normalize(path)

    def test_canonical_boundary_still_rejects_question_mark(self):
        df = pd.DataFrame(
            {"chr": ["chr1"], "start": [0], "end": [10], "strand": ["?"]}
        )
        with pytest.raises(InvalidIntervalError, match="strand"):
            normalize_intervals(df, coordinate_system="0-based")


# --- F-NEW-04: embedded FASTA ---------------------------------------------


class TestEmbeddedFasta:
    BODY = HEADER + _row(1, 10, "+", "ID=g1;Name=A") + _row(11, 20, "-", "ID=g2")
    FASTA = "##FASTA\n>chr1\nACGTACGTAC\nGGTTAACCGG\n>chr2\nTTTT\n"

    def test_without_fasta_unchanged(self, tmp_path):
        df = parse_and_normalize(_write(tmp_path, self.BODY))
        assert len(df) == 2

    def test_rows_before_fasta_parse_and_sequence_ignored(self, tmp_path):
        df = parse_and_normalize(_write(tmp_path, self.BODY + self.FASTA))
        assert len(df) == 2
        assert df["chr"].tolist() == ["chr1", "chr1"]
        assert df["start"].tolist() == [0, 10]
        assert df["end"].tolist() == [10, 20]
        assert _strands(df) == ["+", "-"]
        assert df["ID"].tolist() == ["g1", "g2"]
        assert df["Name"].tolist()[0] == "A"
        assert not df["chr"].str.startswith(">").any()
        assert not df["chr"].str.contains("ACGT").any()

    def test_fasta_only_after_header_has_no_rows(self, tmp_path):
        df = parse_and_normalize(_write(tmp_path, HEADER + self.FASTA))
        assert len(df) == 0

    def test_other_directives_and_comments_preserved(self, tmp_path):
        text = (
            HEADER
            + "##sequence-region chr1 1 1000\n"
            + "# a comment\n"
            + _row(1, 10, "+")
            + "\n"
            + self.FASTA
        )
        assert len(parse_and_normalize(_write(tmp_path, text))) == 1

    def test_crlf_line_endings(self, tmp_path):
        text = (self.BODY + self.FASTA).replace("\n", "\r\n")
        path = tmp_path / "a.gff3"
        path.write_bytes(text.encode())
        assert len(parse_and_normalize(str(path))) == 2

    def test_malformed_line_before_fasta_fails(self, tmp_path):
        text = HEADER + "chr1\tsrc\tgene\t1\t10\t.\t+\t.\n" + self.FASTA
        with pytest.raises(MalformedFileError, match="line 2"):
            parse_and_normalize(_write(tmp_path, text))

    def test_malformed_line_after_fasta_is_ignored(self, tmp_path):
        text = self.BODY + "##FASTA\nnot\ta\tgff\trow\n"
        assert len(parse_and_normalize(_write(tmp_path, text))) == 2


# --- F-NEW-04: malformed records ------------------------------------------


class TestMalformedRecords:
    @pytest.mark.parametrize(
        "line",
        [
            "chr1\tsrc\tgene\t1\t10\t.\t+\t.\n",  # 8 columns
            "chr1\tsrc\tgene\t1\t10\n",  # 5 columns
            "chr1\tsrc\tgene\t1\t10\t.\t+\t.\tID=x\textra\n",  # 10 columns
        ],
    )
    @pytest.mark.parametrize("name", ["a.gff3", "a.gtf"])
    def test_wrong_column_count(self, tmp_path, name, line):
        text = HEADER + _row(1, 10, "+") + line
        with pytest.raises(MalformedFileError, match=r"line 3: expected 9"):
            parse_and_normalize(_write(tmp_path, text, name))

    def test_empty_attributes_field_means_no_attributes(self, tmp_path):
        text = HEADER + "chr1\tsrc\tgene\t1\t10\t.\t+\t.\t\n"
        df = parse_and_normalize(_write(tmp_path, text))
        assert len(df) == 1
        assert df["ID"].isna().all()

    def test_no_type_error_leaks(self, tmp_path):
        text = HEADER + "chr1\tsrc\tgene\t1\t10\t.\t+\t.\n"
        with pytest.raises(MalformedFileError):
            parse_and_normalize(_write(tmp_path, text))


# --- Parser -> engine ------------------------------------------------------


@pytest.mark.parametrize("engine_cls", ENGINES)
class TestParserToEngine:
    ANNOT = (
        HEADER
        + _row(1, 100, "?", "ID=unknown")
        + _row(1, 100, "+", "ID=plus")
        + "##FASTA\n>chr1\nACGT\n"
    )

    def _annot(self, tmp_path):
        return parse_and_normalize(_write(tmp_path, self.ANNOT))

    def _query(self, strand):
        return pd.DataFrame(
            {"chr": ["chr1"], "start": [10], "end": [20], "strand": [strand]}
        )

    def test_canonical_frame(self, engine_cls, tmp_path):
        annot = self._annot(tmp_path)
        assert annot["chr"].tolist() == ["chr1", "chr1"]
        assert annot["start"].tolist() == [0, 0]
        assert annot["end"].tolist() == [100, 100]
        assert _strands(annot) == [None, "+"]

    def test_unstranded_matches_both(self, engine_cls, tmp_path):
        out = engine_cls(use_strand=False).intersect(
            self._query("+"), self._annot(tmp_path)
        )
        assert sorted(out["annot_ID"].tolist()) == ["plus", "unknown"]

    def test_stranded_matches_only_explicit_compatible(self, engine_cls, tmp_path):
        out = engine_cls(use_strand=True).intersect(
            self._query("+"), self._annot(tmp_path)
        )
        assert out["annot_ID"].tolist() == ["plus"]

    def test_stranded_missing_query_matches_nothing(self, engine_cls, tmp_path):
        out = engine_cls(use_strand=True).intersect(
            self._query(None), self._annot(tmp_path)
        )
        assert out["annot_ID"].dropna().tolist() == []
