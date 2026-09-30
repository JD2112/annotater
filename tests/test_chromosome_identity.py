"""
Task A / F1 regression: canonical chromosome identifiers are strings.

An all-numeric chromosome column (e.g. ``1``) must not be inferred as an
integer by pandas, and a leading-zero identifier (``"01"``) must survive
parsing/normalization exactly — chromosome identity is lexical, never
numeric (SPEC 5: "chromosome: string").

Every test here goes through the real ingestion boundary
(file -> parser -> normalization -> engine -> canonical result), not an
isolated helper. Expected values are hand-computed from the SPEC
contract, never derived from backend output.
"""

from __future__ import annotations

import pandas as pd
import pytest

from streamlit_app.core import (
    CustomParser,
    normalize_intervals,
    parse_and_normalize,
)
from streamlit_app.core.annotator import BedtoolsEngine, PolarsBioEngine
from tests.parity.comparator import (
    assert_canonical_equal,
    check_expected,
    run_and_canonicalize,
)

ENGINES = [BedtoolsEngine, PolarsBioEngine]

GFF_NUMERIC_CHR = (
    "1\tsrc\tgene\t100\t200\t.\t+\t.\tID=g1\n"
)
GTF_NUMERIC_CHR = (
    '1\tsrc\tgene\t100\t200\t.\t+\t.\tgene_id "g1";\n'
)
GFF_LEADING_ZERO = (
    "1\tsrc\tgene\t100\t200\t.\t+\t.\tID=g1\n"
    "01\tsrc\tgene\t300\t400\t.\t-\t.\tID=g2\n"
)


def _assert_canonical_chr_strings(df: pd.DataFrame) -> None:
    """The canonical chr column carries string values, never integers."""
    assert df["chr"].notna().all()
    for value in df["chr"].tolist():
        assert isinstance(value, str), f"canonical chr {value!r} is not a string"
        assert value == str(value)


class TestParserChromosomeIdentity:
    def test_gff_all_numeric_chr_remains_string(self, tmp_path):
        gff = tmp_path / "numeric.gff"
        gff.write_text(GFF_NUMERIC_CHR)

        result = parse_and_normalize(str(gff))

        # GFF 1-based inclusive (100, 200) -> canonical [99, 200).
        assert result[["chr", "start", "end"]].values.tolist() == [["1", 99, 200]]
        assert all(isinstance(v, str) for v in result["chr"].tolist())

    def test_gtf_all_numeric_chr_remains_string(self, tmp_path):
        gtf = tmp_path / "numeric.gtf"
        gtf.write_text(GTF_NUMERIC_CHR)

        result = parse_and_normalize(str(gtf))

        assert result[["chr", "start", "end"]].values.tolist() == [["1", 99, 200]]
        assert all(isinstance(v, str) for v in result["chr"].tolist())

    def test_gff_leading_zero_chr_is_not_numerically_normalized(self, tmp_path):
        gff = tmp_path / "leading_zero.gff"
        gff.write_text(GFF_LEADING_ZERO)

        result = parse_and_normalize(str(gff))

        # "01" must remain exactly "01" — it must NOT become "1" or 1.
        assert result["chr"].tolist() == ["1", "01"]
        _assert_canonical_chr_strings(result)

    def test_custom_all_numeric_chr_remains_string(self, tmp_path):
        tsv = tmp_path / "custom.tsv"
        tsv.write_text(
            "chrom\tpos\tstop\n"
            "1\t100\t200\n"
            "01\t300\t400\n"
        )

        raw = CustomParser.parse(str(tsv))
        mapped = CustomParser.map_columns(raw, "chrom", "pos", "stop")
        result = normalize_intervals(mapped, coordinate_system="0-based")

        assert result["chr"].tolist() == ["1", "01"]
        _assert_canonical_chr_strings(result)


class TestEngineLevelNumericChromosomeMatching:
    # BED query on chr "1" vs GFF annotation whose chr column is
    # all-numeric (so it must be read as the string "1"):
    #   query    chr1 [99, 100)
    #   annot    chr1 1-based (100, 200) -> canonical [99, 200)
    # overlap intersection is [99, 100) -> positive width -> one match.

    def _fixture(self, tmp_path):
        bed = tmp_path / "q.bed"
        bed.write_text("1\t99\t100\tq1\n")
        gff = tmp_path / "a.gff"
        gff.write_text("1\tsrc\tgene\t100\t200\t.\t+\t.\tID=g1\n")
        return (
            parse_and_normalize(str(bed)),
            parse_and_normalize(str(gff)),
        )

    @pytest.mark.parametrize("engine_cls", ENGINES)
    def test_overlap_matches_on_numeric_chromosome(self, engine_cls, tmp_path):
        coord_df, annot_df = self._fixture(tmp_path)
        _assert_canonical_chr_strings(coord_df)
        _assert_canonical_chr_strings(annot_df)

        check_expected(
            engine_cls, coord_df, annot_df,
            pairs=[(0, 0)], how="inner",
        )

        actual = run_and_canonicalize(engine_cls, coord_df, annot_df, how="inner")
        # Canonical result chromosome columns satisfy the string contract.
        for column in ("coord_chr", "annot_chr"):
            for value in actual[column].tolist():
                assert isinstance(value, str), (
                    f"{column} {value!r} is not a string"
                )

    def test_bedtools_and_polars_bio_agree_on_numeric_chromosome(self, tmp_path):
        coord_df, annot_df = self._fixture(tmp_path)

        bedtools_result = run_and_canonicalize(
            BedtoolsEngine, coord_df, annot_df, how="inner"
        )
        polars_result = run_and_canonicalize(
            PolarsBioEngine, coord_df, annot_df, how="inner"
        )
        assert_canonical_equal(bedtools_result, polars_result, label="numeric-chr overlap parity")


class TestClosestOnNumericChromosome:
    # closest, same numeric-chr fixture with the annotation moved away:
    #   query    chr1 [99, 100)
    #   annot    chr1 1-based (500, 600) -> canonical [499, 600)
    # canonical distance = max(0, 499 - 100, 99 - 600) = 399.
    # Same-chromosome candidate generation must find the annotation even
    # when both chr columns were all-numeric in the source.

    def _fixture(self, tmp_path):
        bed = tmp_path / "q.bed"
        bed.write_text("1\t99\t100\tq1\n")
        gff = tmp_path / "a.gff"
        gff.write_text("1\tsrc\tgene\t500\t600\t.\t+\t.\tID=g1\n")
        return (
            parse_and_normalize(str(bed)),
            parse_and_normalize(str(gff)),
        )

    @pytest.mark.parametrize("engine_cls", ENGINES)
    def test_closest_attaches_on_numeric_chromosome(self, engine_cls, tmp_path):
        coord_df, annot_df = self._fixture(tmp_path)
        check_expected(
            engine_cls, coord_df, annot_df,
            pairs=[(0, 0)], how="inner", distances=(399,), mode="closest",
        )

    def test_bedtools_and_polars_bio_agree_on_numeric_chromosome_closest(
        self, tmp_path
    ):
        coord_df, annot_df = self._fixture(tmp_path)

        bedtools_result = run_and_canonicalize(
            BedtoolsEngine, coord_df, annot_df, how="inner",
            extra_columns=("distance",), mode="closest",
        )
        polars_result = run_and_canonicalize(
            PolarsBioEngine, coord_df, annot_df, how="inner",
            extra_columns=("distance",), mode="closest",
        )
        assert_canonical_equal(
            bedtools_result, polars_result, label="numeric-chr closest parity"
        )