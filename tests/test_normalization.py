"""
Tests for the canonical interval contract (PLAN Task 2).

These tests define the backend-independent normalization contract:

- the canonical interval model (0-based, half-open, validated);
- explicit per-format coordinate conversion (BED / GFF / GTF / VCF)
  with one-base boundary cases capable of detecting off-by-one errors;
- deterministic metadata preservation and column ordering;
- the canonical annotation-result schema (columns, order, missing
  values, ``has_overlap`` type, row policy);
- parser/normalization independence from annotation-engine choice.

Run from the repository root with::

    pytest tests/test_normalization.py -v
"""

import inspect

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from streamlit_app.core import (
    BEDParser,
    GFFParser,
    VCFParser,
)
from streamlit_app.core.normalization import (
    FORMAT_COORDINATE_SYSTEMS,
    coordinate_system_for,
    normalize_intervals,
    parse_and_normalize,
)
from streamlit_app.core.schema import (
    CanonicalSchemaError,
    InvalidIntervalError,
    MalformedFileError,
    canonical_result_columns,
    canonicalize_annotation_result,
    validate_canonical_interval_table,
)


GFF_HEADER = "##gff-version 3\n"
VCF_HEADER = (
    "##fileformat=VCFv4.2\n"
    '##INFO=<ID=END,Number=1,Type=Integer,Description="End position of the variant">\n'
    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
)


# ---------------------------------------------------------------------------
# Canonical interval validation
# ---------------------------------------------------------------------------


class TestCanonicalIntervalValidation:
    """The canonical interval model: 0-based half-open, start >= 0, end > start."""

    def test_valid_ordinary_interval(self):
        df = pd.DataFrame({"chr": ["chr1"], "start": [100], "end": [200]})
        out = normalize_intervals(df, coordinate_system="0-based")
        assert out["chr"].tolist() == ["chr1"]
        assert out["start"].tolist() == [100]
        assert out["end"].tolist() == [200]

    def test_start_zero_is_valid(self):
        """A half-open interval may legitimately start at position 0."""
        df = pd.DataFrame({"chr": ["chr1"], "start": [0], "end": [1]})
        out = normalize_intervals(df, coordinate_system="0-based")
        assert out["start"].tolist() == [0]
        assert out["end"].tolist() == [1]

    def test_negative_start_rejected(self):
        df = pd.DataFrame({"chr": ["chr1"], "start": [-1], "end": [10]})
        with pytest.raises(InvalidIntervalError):
            normalize_intervals(df, coordinate_system="0-based")

    def test_zero_width_interval_rejected(self):
        df = pd.DataFrame({"chr": ["chr1"], "start": [5], "end": [5]})
        with pytest.raises(InvalidIntervalError):
            normalize_intervals(df, coordinate_system="0-based")

    def test_end_before_start_rejected(self):
        df = pd.DataFrame({"chr": ["chr1"], "start": [200], "end": [100]})
        with pytest.raises(InvalidIntervalError):
            normalize_intervals(df, coordinate_system="0-based")

    def test_non_integer_coordinates_rejected(self):
        df = pd.DataFrame({"chr": ["chr1"], "start": [10.5], "end": [20]})
        with pytest.raises(InvalidIntervalError):
            normalize_intervals(df, coordinate_system="0-based")

    def test_missing_coordinate_values_rejected(self):
        df = pd.DataFrame({"chr": ["chr1"], "start": [pd.NA], "end": [20]})
        with pytest.raises(InvalidIntervalError):
            normalize_intervals(df, coordinate_system="0-based")

    def test_missing_core_column_rejected(self):
        df = pd.DataFrame({"chr": ["chr1"], "start": [100]})
        with pytest.raises(CanonicalSchemaError):
            normalize_intervals(df, coordinate_system="0-based")

    def test_missing_chr_rejected(self):
        df = pd.DataFrame({"chr": [None], "start": [100], "end": [200]})
        with pytest.raises(InvalidIntervalError):
            normalize_intervals(df, coordinate_system="0-based")

    def test_invalid_strand_rejected(self):
        df = pd.DataFrame(
            {"chr": ["chr1"], "start": [100], "end": [200], "strand": ["x"]}
        )
        with pytest.raises(InvalidIntervalError):
            normalize_intervals(df, coordinate_system="0-based")

    def test_valid_strands_preserved(self):
        df = pd.DataFrame(
            {
                "chr": ["chr1", "chr1"],
                "start": [100, 200],
                "end": [200, 300],
                "strand": ["+", "-"],
            }
        )
        out = normalize_intervals(df, coordinate_system="0-based")
        assert out["strand"].tolist() == ["+", "-"]

    def test_strand_missing_sentinel_becomes_canonical_missing(self):
        df = pd.DataFrame(
            {"chr": ["chr1", "chr2"], "start": [100, 200], "end": [200, 300], "strand": [".", "+"]}
        )
        out = normalize_intervals(df, coordinate_system="0-based")
        assert pd.isna(out["strand"].iloc[0])
        assert out["strand"].iloc[1] == "+"

    def test_validate_canonical_interval_table_passes_on_normalized_output(self):
        df = pd.DataFrame({"chr": ["chr1"], "start": [0], "end": [1]})
        out = normalize_intervals(df, coordinate_system="0-based")
        validate_canonical_interval_table(out)  # must not raise


# ---------------------------------------------------------------------------
# Format-specific coordinate-system resolution
# ---------------------------------------------------------------------------


class TestFormatSystemResolution:
    """Format-specific coordinate conventions, independent of any backend."""

    def test_known_format_systems(self):
        assert FORMAT_COORDINATE_SYSTEMS["bed"] == "0-based"
        assert FORMAT_COORDINATE_SYSTEMS["gff"] == "1-based"
        assert FORMAT_COORDINATE_SYSTEMS["gtf"] == "1-based"
        assert FORMAT_COORDINATE_SYSTEMS["vcf"] == "1-based"

    def test_known_format_ignores_declared_system(self):
        # Format semantics are fixed by the format specification; an
        # explicit user choice must not silently re-interpret them.
        assert coordinate_system_for("bed", declared_system="1-based") == "0-based"
        assert coordinate_system_for("gff", declared_system="0-based") == "1-based"

    def test_custom_uses_declared_system(self):
        assert coordinate_system_for("custom", declared_system="1-based") == "1-based"
        assert coordinate_system_for("custom", declared_system="0-based") == "0-based"

    def test_custom_defaults_to_zero_based(self):
        # Historical effective behavior: custom tables are treated as
        # already-canonical 0-based half-open coordinates.
        assert coordinate_system_for("custom", declared_system=None) == "0-based"
        assert coordinate_system_for(None, declared_system=None) == "0-based"


# ---------------------------------------------------------------------------
# BED boundaries
# ---------------------------------------------------------------------------


class TestBedBoundaries:
    """BED is already 0-based half-open: it must pass through unchanged."""

    def test_simple_bed_interval_unchanged(self, tmp_path):
        bed = tmp_path / "t.bed"
        bed.write_text("chr1\t100\t200\n")
        out = parse_and_normalize(str(bed), fmt="bed")
        expected = pd.DataFrame({"chr": ["chr1"], "start": [100], "end": [200]})
        # check_dtype=False: string-column dtype (object vs str) varies by
        # pandas version; the coordinate dtypes are asserted explicitly.
        assert_frame_equal(out, expected, check_dtype=False)
        assert pd.api.types.is_integer_dtype(out["start"])
        assert pd.api.types.is_integer_dtype(out["end"])

    def test_one_base_bed_interval_represents_exactly_one_base(self, tmp_path):
        bed = tmp_path / "t.bed"
        bed.write_text("chr1\t100\t101\n")
        out = parse_and_normalize(str(bed), fmt="bed")
        assert out["start"].tolist() == [100]
        assert out["end"].tolist() == [101]
        assert (out["end"] - out["start"]).tolist() == [1]

    def test_variable_width_bed_is_parsed_per_row(self, tmp_path):
        # BED rows may have 3..12+ columns; optional fields are NA per row.
        bed = tmp_path / "t.bed"
        bed.write_text(
            "chr1\t100\t200\n"
            "chr1\t300\t400\tnameA\n"
            "chr2\t500\t600\tnameB\t42\t-\n"
        )
        out = parse_and_normalize(str(bed), fmt="bed")
        # Core columns first, strand next, then metadata in source order.
        assert list(out.columns) == ["chr", "start", "end", "strand", "name", "score"]
        assert out["chr"].tolist() == ["chr1", "chr1", "chr2"]
        assert out["start"].tolist() == [100, 300, 500]
        assert out["end"].tolist() == [200, 400, 600]
        assert pd.isna(out["name"].iloc[0])
        assert out["name"].iloc[1] == "nameA"
        assert out["name"].iloc[2] == "nameB"
        assert out["score"].isna().tolist() == [True, True, False]
        assert float(out["score"].iloc[2]) == 42.0
        assert pd.isna(out["strand"].iloc[0])
        assert pd.isna(out["strand"].iloc[1])
        assert out["strand"].iloc[2] == "-"

    def test_malformed_bed_line_fails_explicitly(self, tmp_path):
        # A line with fewer than 3 fields is invalid BED. The contract is
        # to fail with a precise error, not to silently drop the record.
        bed = tmp_path / "t.bed"
        bed.write_text("chr1\t100\t200\nregion1\nchr2\t300\t400\tregion2\n")
        with pytest.raises(MalformedFileError, match="line 2"):
            parse_and_normalize(str(bed), fmt="bed")

    def test_non_integer_bed_coordinates_fail_explicitly(self, tmp_path):
        bed = tmp_path / "t.bed"
        bed.write_text("chr1\t100\t20.5\n")
        with pytest.raises(MalformedFileError, match="line 1"):
            parse_and_normalize(str(bed), fmt="bed")

    def test_empty_bed_file_yields_canonical_schema(self, tmp_path):
        bed = tmp_path / "t.bed"
        bed.write_text("# only a comment\n")
        out = parse_and_normalize(str(bed), fmt="bed")
        assert out.empty
        assert list(out.columns) == ["chr", "start", "end"]


# ---------------------------------------------------------------------------
# GFF / GTF boundaries (1-based inclusive -> 0-based half-open)
# ---------------------------------------------------------------------------


class TestGFFBoundaries:
    """GFF/GTF are 1-based inclusive: conversion must be explicit and tested."""

    def test_one_based_inclusive_interval_converted(self, tmp_path):
        gff = tmp_path / "t.gff"
        gff.write_text(GFF_HEADER + "chr1\tsrc\tgene\t50000\t150000\t.\t+\t.\tID=g1\n")
        out = parse_and_normalize(str(gff), fmt="gff")
        # 1-based [50000, 150000] == 0-based half-open [49999, 150000)
        assert out["chr"].tolist() == ["chr1"]
        assert out["start"].tolist() == [49999]
        assert out["end"].tolist() == [150000]

    def test_single_base_feature_catches_one_base_error(self, tmp_path):
        # A 1-based inclusive single-base feature [100, 100] must become
        # the one-base half-open interval [99, 100). Any off-by-one in
        # either direction (e.g. [100, 101) or [98, 99)) fails here.
        gff = tmp_path / "t.gff"
        gff.write_text(GFF_HEADER + "chr1\tsrc\texon\t100\t100\t.\t+\t.\t.\n")
        out = parse_and_normalize(str(gff), fmt="gff")
        assert out["start"].tolist() == [99]
        assert out["end"].tolist() == [100]
        assert (out["end"] - out["start"]).tolist() == [1]

    def test_one_based_start_at_one_converts_to_zero(self, tmp_path):
        gff = tmp_path / "t.gff"
        gff.write_text(GFF_HEADER + "chr1\tsrc\tgene\t1\t1\t.\t-\t.\t.\n")
        out = parse_and_normalize(str(gff), fmt="gff")
        assert out["start"].tolist() == [0]
        assert out["end"].tolist() == [1]

    def test_gtf_single_base_feature(self, tmp_path):
        gtf = tmp_path / "t.gtf"
        gtf.write_text(
            '# gene_id "ENSG001";\n'
            'chr1\tENSEMBL\texon\t100\t100\t.\t+\t.\tgene_id "ENSG001"; transcript_id "ENST001";\n'
        )
        out = parse_and_normalize(str(gtf), fmt="gtf")
        assert out["start"].tolist() == [99]
        assert out["end"].tolist() == [100]
        assert out["gene_id"].tolist() == ["ENSG001"]
        assert out["transcript_id"].tolist() == ["ENST001"]

    def test_gff_metadata_preserved_in_deterministic_order(self, tmp_path):
        gff = tmp_path / "t.gff"
        gff.write_text(
            GFF_HEADER
            + "chr1\tsrc\tgene\t50000\t150000\t.\t+\t.\tID=g1;Name=G1\n"
        )
        out = parse_and_normalize(str(gff), fmt="gff")
        # Core first, strand next, then metadata in source order.
        assert list(out.columns) == [
            "chr", "start", "end", "strand",
            "source", "feature", "score", "frame", "attributes",
            "ID", "Name", "gene_id", "gene_name", "transcript_id",
            "gene_type", "gene_biotype", "Parent",
        ]
        assert out["feature"].tolist() == ["gene"]
        assert out["ID"].tolist() == ["g1"]
        assert out["Name"].tolist() == ["G1"]

    def test_gff_strand_dot_becomes_canonical_missing(self, tmp_path):
        gff = tmp_path / "t.gff"
        gff.write_text(GFF_HEADER + "chr1\tsrc\tgene\t50000\t150000\t.\t.\t.\t.\n")
        out = parse_and_normalize(str(gff), fmt="gff")
        assert pd.isna(out["strand"].iloc[0])


# ---------------------------------------------------------------------------
# VCF boundaries (POS 1-based; span from REF length or INFO/END)
# ---------------------------------------------------------------------------


class TestVCFBoundaries:
    """
    VCF POS is 1-based. The occupied variant interval per the VCF
    specification is [POS, POS + max(1, len(REF)) - 1], or [POS, END]
    (both inclusive) when INFO/END is present.
    """

    def _write_vcf(self, tmp_path, body):
        vcf = tmp_path / "t.vcf"
        vcf.write_text(VCF_HEADER + body)
        return str(vcf)

    def test_single_base_variant_catches_off_by_one(self, tmp_path):
        # POS=101 (1-based) is base 101 -> canonical [100, 101).
        # The historical implementation that shifted twice would produce
        # [99, 100); the span-less 'end = POS' convention also produces
        # the wrong answer for anything other than a SNP.
        path = self._write_vcf(tmp_path, "chr1\t101\t.\tA\tG\t.\t.\t.\n")
        out = parse_and_normalize(path, fmt="vcf")
        assert out["chr"].tolist() == ["chr1"]
        assert out["start"].tolist() == [100]
        assert out["end"].tolist() == [101]

    def test_deletion_span_from_ref_length(self, tmp_path):
        # POS=200, REF=ACGT (4 bases) -> 1-based [200, 203] -> [199, 203)
        path = self._write_vcf(tmp_path, "chr2\t200\tdel1\tACGT\t-\t.\t.\t.\n")
        out = parse_and_normalize(path, fmt="vcf")
        assert out["start"].tolist() == [199]
        assert out["end"].tolist() == [203]

    def test_info_end_determines_span(self, tmp_path):
        # POS=300 with END=303 -> 1-based [300, 303] -> [299, 303)
        path = self._write_vcf(tmp_path, "chr2\t300\tsv1\tA\tT\t.\tPASS\tEND=303\n")
        out = parse_and_normalize(path, fmt="vcf")
        assert out["start"].tolist() == [299]
        assert out["end"].tolist() == [303]

    def test_vcf_metadata_preserved(self, tmp_path):
        path = self._write_vcf(tmp_path, "chr1\t101\tv1\tA\tG\t.\tPASS\t.\n")
        out = parse_and_normalize(path, fmt="vcf")
        assert list(out.columns) == [
            "chr", "start", "end", "id", "ref", "alt", "qual", "filter", "info",
        ]
        assert out["id"].tolist() == ["v1"]
        assert out["ref"].tolist() == ["A"]
        assert out["alt"].tolist() == ["G"]
        assert out["filter"].iloc[0] == "PASS"
        # INFO "." (no info) is canonical missing, not the string '.'.
        assert pd.isna(out["info"].iloc[0])

    def test_info_end_among_other_info_fields(self, tmp_path):
        # END is extracted from the raw INFO field regardless of other keys.
        path = self._write_vcf(
            tmp_path, "chr2\t300\tsv1\tA\tT\t.\tPASS\tDP=5;END=303;SV=DEL\n"
        )
        out = parse_and_normalize(path, fmt="vcf")
        assert out["start"].tolist() == [299]
        assert out["end"].tolist() == [303]

    def test_short_vcf_data_line_fails_explicitly(self, tmp_path):
        vcf = tmp_path / "t.vcf"
        vcf.write_text(VCF_HEADER + "chr1\t101\t.\n")
        # Header is 3 physical lines; the data line is line 4.
        with pytest.raises(MalformedFileError, match="line 4"):
            parse_and_normalize(str(vcf), fmt="vcf")


class TestVCFFilterSemantics:
    """
    FILTER must preserve the VCF specification's distinct meanings
    (VCF spec 1.6.1, field FILTER):

    - ``PASS``: filters were applied and the record passed them;
    - a semicolon-separated list of codes: filters that failed;
    - ``.`` (MISSING): filters were not applied — NOT equivalent to PASS.
    """

    def _write(self, tmp_path, filt):
        vcf = tmp_path / "t.vcf"
        vcf.write_text(VCF_HEADER + f"chr1\t101\t.\tA\tG\t.\t{filt}\t.\n")
        return str(vcf)

    def test_filter_pass_preserved(self, tmp_path):
        out = parse_and_normalize(self._write(tmp_path, "PASS"), fmt="vcf")
        assert out["filter"].iloc[0] == "PASS"

    def test_filter_missing_not_converted_to_pass(self, tmp_path):
        # "." means filters were not applied; it must remain canonical
        # missing, never become "PASS".
        out = parse_and_normalize(self._write(tmp_path, "."), fmt="vcf")
        assert pd.isna(out["filter"].iloc[0])

    def test_single_failed_filter_preserved(self, tmp_path):
        out = parse_and_normalize(self._write(tmp_path, "q10"), fmt="vcf")
        assert out["filter"].iloc[0] == "q10"

    def test_multiple_failed_filters_preserved(self, tmp_path):
        out = parse_and_normalize(self._write(tmp_path, "q10;LowQual"), fmt="vcf")
        assert out["filter"].iloc[0] == "q10;LowQual"


class TestVCFMetadataPreservation:
    """
    Arbitrary INFO content, FORMAT, and sample-level fields must survive
    parse + normalization with deterministic source column ordering.
    """

    def _write_raw(self, tmp_path, text):
        vcf = tmp_path / "t.vcf"
        vcf.write_text(text)
        return str(vcf)

    @staticmethod
    def _header_with_samples(*samples):
        cols = "CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT"
        if samples:
            cols += "\t" + "\t".join(samples)
        return VCF_HEADER.replace(
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n",
            "#" + cols + "\n",
        )

    def test_raw_info_field_preserved_and_span_still_extracted(self, tmp_path):
        path = self._write_raw(
            tmp_path,
            VCF_HEADER + "chr2\t300\tsv1\tA\tT\t.\tPASS\tDP=5;AF=0.3;END=303;SV=DEL\n",
        )
        out = parse_and_normalize(path, fmt="vcf")
        # Raw INFO survives verbatim as metadata...
        assert out["info"].iloc[0] == "DP=5;AF=0.3;END=303;SV=DEL"
        # ...while END is still extracted for the span calculation.
        assert out["start"].tolist() == [299]
        assert out["end"].tolist() == [303]

    def test_info_missing_normalized_without_changing_meaning(self, tmp_path):
        path = self._write_raw(tmp_path, VCF_HEADER + "chr1\t101\t.\tA\tG\t.\t.\t.\n")
        out = parse_and_normalize(path, fmt="vcf")
        assert pd.isna(out["info"].iloc[0])

    def test_format_and_sample_columns_preserved_in_source_order(self, tmp_path):
        header = self._header_with_samples("S1", "S2")
        path = self._write_raw(
            tmp_path,
            header + "chr1\t101\t.\tA\tG\t.\tPASS\tDP=5\tGT:DP\t0/1:5\t1/1:7\n",
        )
        out = parse_and_normalize(path, fmt="vcf")
        # format + sample columns follow the fixed fields, in source order.
        assert list(out.columns) == [
            "chr", "start", "end", "id", "ref", "alt", "qual", "filter",
            "info", "format", "S1", "S2",
        ]
        assert out["format"].iloc[0] == "GT:DP"
        assert out["S1"].iloc[0] == "0/1:5"
        assert out["S2"].iloc[0] == "1/1:7"

    def test_sample_values_preserved_and_missing_normalized(self, tmp_path):
        header = self._header_with_samples("S1", "S2")
        path = self._write_raw(
            tmp_path, header + "chr1\t101\t.\tA\tG\t.\t.\t.\tGT\t0/1\t.\n"
        )
        out = parse_and_normalize(path, fmt="vcf")
        assert out["S1"].iloc[0] == "0/1"
        # VCF sample "." is the missing value -> canonical missing.
        assert pd.isna(out["S2"].iloc[0])
        # Coordinates unaffected by the sample-level metadata.
        assert out["start"].tolist() == [100]
        assert out["end"].tolist() == [101]

    def test_sample_names_come_from_header_not_positions(self, tmp_path):
        header = self._header_with_samples("tumor", "normal")
        path = self._write_raw(
            tmp_path, header + "chr1\t101\t.\tA\tG\t.\t.\t.\tGT\t1/1\t0/0\n"
        )
        out = parse_and_normalize(path, fmt="vcf")
        assert "tumor" in out.columns and "normal" in out.columns
        assert out["tumor"].iloc[0] == "1/1"
        assert out["normal"].iloc[0] == "0/0"

    def test_sample_named_gt_kept_verbatim(self, tmp_path):
        # "GT" is a legitimate sample name in real files and is not a
        # parser/core column, so it is kept verbatim as a metadata column.
        header = self._header_with_samples("GT")
        path = self._write_raw(
            tmp_path, header + "chr1\t101\t.\tA\tG\t.\t.\t.\tGT\t0/1\n"
        )
        out = parse_and_normalize(path, fmt="vcf")
        assert "GT" in out.columns
        assert out["GT"].iloc[0] == "0/1"
        # Coordinates unaffected.
        assert out["start"].tolist() == [100]
        assert out["end"].tolist() == [101]

    def test_sample_name_colliding_with_core_column_renamed_deterministically(
        self, tmp_path
    ):
        # A sample literally named "start" would collide with the interval
        # columns; it must be renamed deterministically, not rejected.
        header = self._header_with_samples("start")
        path = self._write_raw(
            tmp_path, header + "chr1\t101\t.\tA\tG\t.\t.\t.\tGT\t0/1\n"
        )
        out = parse_and_normalize(path, fmt="vcf")
        assert "sample_start" in out.columns
        assert out["sample_start"].iloc[0] == "0/1"
        assert out["start"].tolist() == [100]

    def test_duplicate_sample_names_rejected(self, tmp_path):
        header = self._header_with_samples("S1", "S1")
        path = self._write_raw(
            tmp_path, header + "chr1\t101\t.\tA\tG\t.\t.\t.\tGT\t0/1\t1/1\n"
        )
        with pytest.raises(MalformedFileError, match="duplicate sample"):
            parse_and_normalize(path, fmt="vcf")

    def test_reserved_prefix_sample_name_rejected(self, tmp_path):
        header = self._header_with_samples("coord_x")
        path = self._write_raw(
            tmp_path, header + "chr1\t101\t.\tA\tG\t.\t.\t.\tGT\t0/1\n"
        )
        with pytest.raises(MalformedFileError, match="coord_/annot_"):
            parse_and_normalize(path, fmt="vcf")

    def test_record_with_fewer_sample_fields_rejected(self, tmp_path):
        header = self._header_with_samples("S1", "S2")
        path = self._write_raw(
            tmp_path, header + "chr1\t101\t.\tA\tG\t.\t.\t.\tGT\t0/1\n"
        )
        with pytest.raises(MalformedFileError, match="line 4"):
            parse_and_normalize(path, fmt="vcf")

    def test_record_with_extra_sample_fields_rejected(self, tmp_path):
        header = self._header_with_samples("S1")
        path = self._write_raw(
            tmp_path, header + "chr1\t101\t.\tA\tG\t.\t.\t.\tGT\t0/1\t1/1\n"
        )
        with pytest.raises(MalformedFileError, match="line 4"):
            parse_and_normalize(path, fmt="vcf")

    def test_sample_fields_without_chrom_header_rejected(self, tmp_path):
        # No #CHROM line -> sample columns cannot be named -> explicit error.
        path = self._write_raw(
            tmp_path,
            "##fileformat=VCFv4.2\nchr1\t101\t.\tA\tG\t.\t.\t.\tGT\t0/1\n",
        )
        with pytest.raises(MalformedFileError, match="no #CHROM"):
            parse_and_normalize(path, fmt="vcf")


# ---------------------------------------------------------------------------
# Metadata provenance
# ---------------------------------------------------------------------------


class TestMetadataProvenance:
    """Normalization must preserve source metadata deterministically."""

    def test_arbitrary_metadata_survives_normalization(self):
        df = pd.DataFrame(
            {
                "chr": ["chr1", "chr2"],
                "start": [10, 20],
                "end": [20, 30],
                "my_region": ["a", "b"],
                "notes": ["x", "y"],
            }
        )
        out = normalize_intervals(df, coordinate_system="0-based")
        assert out["my_region"].tolist() == ["a", "b"]
        assert out["notes"].tolist() == ["x", "y"]

    def test_coordinates_separated_from_metadata_in_column_order(self):
        df = pd.DataFrame(
            {
                "chr": ["chr1"],
                "start": [10],
                "end": [20],
                "b_meta": ["1"],
                "strand": ["+"],
                "a_meta": ["2"],
            }
        )
        out = normalize_intervals(df, coordinate_system="0-based")
        # Core columns first, strand next, then metadata in source order.
        assert list(out.columns) == ["chr", "start", "end", "strand", "b_meta", "a_meta"]

    def test_duplicate_rows_are_preserved(self):
        df = pd.DataFrame(
            {
                "chr": ["chr1", "chr1"],
                "start": [100, 100],
                "end": [200, 200],
                "name": ["r", "r"],
            }
        )
        out = normalize_intervals(df, coordinate_system="0-based")
        assert len(out) == 2
        assert out["name"].tolist() == ["r", "r"]

    def test_reserved_result_prefix_in_metadata_rejected(self):
        # A metadata column that already starts with coord_/annot_ would
        # make result provenance ambiguous; fail explicitly.
        df = pd.DataFrame(
            {"chr": ["chr1"], "start": [10], "end": [20], "coord_extra": ["z"]}
        )
        with pytest.raises(CanonicalSchemaError):
            normalize_intervals(df, coordinate_system="0-based")

    def test_input_frame_is_not_mutated(self):
        df = pd.DataFrame(
            {"chr": ["chr1"], "start": [100], "end": [200], "name": ["r"]}
        )
        before = df.copy(deep=True)
        normalize_intervals(df, coordinate_system="0-based")
        assert_frame_equal(df, before)

    def test_normalization_is_deterministic(self):
        df = pd.DataFrame(
            {"chr": ["chr1", "chr2"], "start": [100, 200], "end": [200, 300]}
        )
        first = normalize_intervals(df, coordinate_system="0-based")
        second = normalize_intervals(df, coordinate_system="0-based")
        assert_frame_equal(first, second)


# ---------------------------------------------------------------------------
# Parser / backend independence (central Task 2 acceptance test)
# ---------------------------------------------------------------------------


class TestEngineIndependence:
    """The same source input must normalize identically for any engine choice."""

    ENGINE_CHOICES = ["Bedtools (Standard)", "Polars-Bio (Fast, Experimental)"]

    def test_parser_apis_have_no_backend_selection_parameter(self):
        for parser_cls in (BEDParser, GFFParser, VCFParser):
            params = inspect.signature(parser_cls.parse).parameters
            offending = [
                p for p in params if any(
                    token in p.lower() for token in ("polars", "backend", "engine")
                )
            ]
            assert not offending, f"{parser_cls.__name__}.parse is backend-coupled: {offending}"

    @pytest.mark.parametrize("engine_choice", ENGINE_CHOICES)
    def test_same_gff_source_normalizes_identically_for_every_engine_choice(
        self, tmp_path, engine_choice
    ):
        # ``engine_choice`` is deliberately unused: backend selection no
        # longer participates in parsing or normalization at all.
        gff = tmp_path / "t.gff"
        gff.write_text(GFF_HEADER + "chr1\tsrc\tgene\t50000\t150000\t.\t+\t.\tID=g1\n")
        out = parse_and_normalize(str(gff), fmt="gff")
        assert out["start"].tolist() == [49999]
        assert out["end"].tolist() == [150000]

    @pytest.mark.parametrize("engine_choice", ENGINE_CHOICES)
    def test_same_bed_source_normalizes_identically_for_every_engine_choice(
        self, tmp_path, engine_choice
    ):
        bed = tmp_path / "t.bed"
        bed.write_text("chr1\t100\t200\tr1\n")
        out = parse_and_normalize(str(bed), fmt="bed")
        expected = pd.DataFrame(
            {"chr": ["chr1"], "start": [100], "end": [200], "name": ["r1"]}
        )
        # check_dtype=False: string-column dtype (object vs str) varies by
        # pandas version; coordinate dtypes are asserted explicitly.
        assert_frame_equal(out, expected, check_dtype=False)
        assert pd.api.types.is_integer_dtype(out["start"])
        assert pd.api.types.is_integer_dtype(out["end"])
        assert out["name"].iloc[0] == "r1"

    @pytest.mark.parametrize("engine_choice", ENGINE_CHOICES)
    def test_same_vcf_source_normalizes_identically_for_every_engine_choice(
        self, tmp_path, engine_choice
    ):
        vcf = tmp_path / "t.vcf"
        vcf.write_text(VCF_HEADER + "chr1\t101\t.\tA\tG\t.\t.\t.\n")
        out = parse_and_normalize(str(vcf), fmt="vcf")
        assert out["start"].tolist() == [100]
        assert out["end"].tolist() == [101]

    def test_parse_and_normalize_rejects_custom_before_column_mapping(self, tmp_path):
        # Custom tables have no declared coordinate columns yet; normalizing
        # them is only valid after explicit column mapping.
        custom = tmp_path / "t.tsv"
        custom.write_text("chromosome\tpos\tend\tx\n1\t5\t6\tfoo\n")
        with pytest.raises(ValueError, match="custom"):
            parse_and_normalize(str(custom), fmt="custom")


# ---------------------------------------------------------------------------
# Canonical annotation-result schema
# ---------------------------------------------------------------------------


class TestCanonicalResultSchema:
    """Reusable canonicalization machinery for backend outputs."""

    def _coord_df(self):
        return pd.DataFrame(
            {
                "chr": ["chr1", "chr1", "chr2"],
                "start": [100, 100, 250],
                "end": [200, 200, 300],
                "region": ["r1", "r1", "r2"],
            }
        )

    def _annot_df(self):
        return pd.DataFrame(
            {
                "chr": ["chr1", "chr2"],
                "start": [90, 240],
                "end": [150, 260],
                "feature": ["geneA", "geneB"],
                "gene_id": ["G1", "G2"],
            }
        )

    def test_expected_column_order(self):
        expected = canonical_result_columns(self._coord_df(), self._annot_df())
        assert expected == (
            "coord_chr", "coord_start", "coord_end", "coord_region",
            "annot_chr", "annot_start", "annot_end",
            "annot_feature", "annot_gene_id",
            "has_overlap",
        )

    def test_canonicalize_bedtools_like_left_join_output(self):
        # Simulated backend output in coord_*/annot_* naming, bedtools
        # left-join style: string fields, "." sentinels on unmatched rows.
        raw = pd.DataFrame(
            {
                "coord_chr": ["chr1", "chr1", "chr2"],
                "coord_start": ["100", "100", "250"],
                "coord_end": ["200", "200", "300"],
                "coord_region": ["r1", "r1", "r2"],
                "annot_chr": ["chr1", ".", "chr2"],
                "annot_start": ["90", ".", "240"],
                "annot_end": ["150", ".", "260"],
                "annot_feature": ["geneA", ".", "geneB"],
                "annot_gene_id": ["G1", ".", "G2"],
                "has_overlap": [True, False, True],
            }
        )
        out = canonicalize_annotation_result(raw, self._coord_df(), self._annot_df())

        expected_columns = canonical_result_columns(self._coord_df(), self._annot_df())
        assert list(out.columns) == list(expected_columns)

        # Matched rows keep values with canonical dtypes.
        assert out["coord_start"].dtype == "int64"
        assert out["coord_start"].tolist() == [100, 100, 250]
        assert out["annot_start"].dtype == "Int64"
        assert out["annot_start"].isna().tolist() == [False, True, False]
        assert out["annot_start"].iloc[0] == 90
        assert out["annot_start"].iloc[2] == 240
        assert out["annot_chr"].iloc[0] == "chr1"
        assert out["annot_chr"].iloc[2] == "chr2"
        assert out["annot_gene_id"].iloc[0] == "G1"
        assert out["annot_gene_id"].iloc[2] == "G2"

        # has_overlap is boolean.
        assert out["has_overlap"].dtype == "bool"
        assert out["has_overlap"].tolist() == [True, False, True]

        # Unmatched rows are canonical missing (never "." / "-1").
        unmatched = out.loc[~out["has_overlap"]]
        annot_cols = [c for c in out.columns if c.startswith("annot_")]
        assert unmatched[annot_cols].isna().all().all()

    def test_duplicate_query_rows_are_preserved(self):
        raw = pd.DataFrame(
            {
                "coord_chr": ["chr1", "chr1"],
                "coord_start": ["100", "100"],
                "coord_end": ["200", "200"],
                "coord_region": ["r1", "r1"],
                "annot_chr": ["chr1", "chr1"],
                "annot_start": ["90", "90"],
                "annot_end": ["150", "150"],
                "annot_feature": ["geneA", "geneA"],
                "annot_gene_id": ["G1", "G1"],
                "has_overlap": [True, True],
            }
        )
        out = canonicalize_annotation_result(raw, self._coord_df()[:2], self._annot_df())
        assert len(out) == 2

    def test_row_order_is_preserved(self):
        raw = pd.DataFrame(
            {
                "coord_chr": ["chr1", "chr2"],
                "coord_start": ["100", "250"],
                "coord_end": ["200", "300"],
                "coord_region": ["r1", "r2"],
                "annot_chr": ["chr1", "chr2"],
                "annot_start": ["90", "240"],
                "annot_end": ["150", "260"],
                "annot_feature": ["geneA", "geneB"],
                "annot_gene_id": ["G1", "G2"],
                "has_overlap": [True, True],
            }
        )
        out = canonicalize_annotation_result(raw, self._coord_df(), self._annot_df())
        assert out["coord_region"].tolist() == ["r1", "r2"]

    def test_backend_suffix_columns_are_rejected(self):
        # Polars-Bio style suffixes must never leak into the canonical
        # public contract.
        raw = pd.DataFrame(
            {
                "coord_chr": ["chr1"],
                "coord_start": ["100"],
                "coord_end": ["200"],
                "coord_region": ["r1"],
                "annot_chr": ["chr1"],
                "annot_start": ["90"],
                "annot_end": ["150"],
                "annot_feature": ["geneA"],
                "annot_gene_id": ["G1"],
                "annot_gene_id_2": ["extra"],
                "has_overlap": [True],
            }
        )
        with pytest.raises(CanonicalSchemaError, match="annot_gene_id_2"):
            canonicalize_annotation_result(raw, self._coord_df(), self._annot_df())

    def test_right_suffix_columns_are_rejected(self):
        raw = pd.DataFrame(
            {
                "coord_chr": ["chr1"],
                "coord_start": ["100"],
                "coord_end": ["200"],
                "coord_region": ["r1"],
                "annot_chr": ["chr1"],
                "annot_start": ["90"],
                "annot_end": ["150"],
                "annot_feature": ["geneA"],
                "annot_gene_id": ["G1"],
                "start_right": ["90"],
                "has_overlap": [True],
            }
        )
        with pytest.raises(CanonicalSchemaError, match="start_right"):
            canonicalize_annotation_result(raw, self._coord_df(), self._annot_df())

    def test_missing_expected_column_is_rejected(self):
        raw = pd.DataFrame(
            {
                "coord_chr": ["chr1"],
                "coord_start": ["100"],
                "coord_end": ["200"],
                "coord_region": ["r1"],
                "annot_chr": ["chr1"],
                "annot_start": ["90"],
                "annot_end": ["150"],
                "annot_feature": ["geneA"],
                # annot_gene_id intentionally missing
                "has_overlap": [True],
            }
        )
        with pytest.raises(CanonicalSchemaError, match="annot_gene_id"):
            canonicalize_annotation_result(raw, self._coord_df(), self._annot_df())

    def test_non_boolean_has_overlap_is_rejected(self):
        raw = pd.DataFrame(
            {
                "coord_chr": ["chr1"],
                "coord_start": ["100"],
                "coord_end": ["200"],
                "coord_region": ["r1"],
                "annot_chr": ["chr1"],
                "annot_start": ["90"],
                "annot_end": ["150"],
                "annot_feature": ["geneA"],
                "annot_gene_id": ["G1"],
                "has_overlap": ["yes"],
            }
        )
        with pytest.raises(CanonicalSchemaError):
            canonicalize_annotation_result(raw, self._coord_df(), self._annot_df())

    def test_empty_result_gets_canonical_schema(self):
        out = canonicalize_annotation_result(
            pd.DataFrame(), self._coord_df(), self._annot_df()
        )
        assert out.empty
        assert list(out.columns) == list(
            canonical_result_columns(self._coord_df(), self._annot_df())
        )
        assert out["has_overlap"].dtype == "bool"

    def test_extra_operation_columns_must_be_declared(self):
        # Operation-specific columns (e.g. closest distance) are allowed
        # only when explicitly declared; a declared-but-absent column and an
        # undeclared extra column are both rejected.
        raw = pd.DataFrame(
            {
                "coord_chr": ["chr1"],
                "coord_start": ["100"],
                "coord_end": ["200"],
                "coord_region": ["r1"],
                "annot_chr": ["chr1"],
                "annot_start": ["90"],
                "annot_end": ["150"],
                "annot_feature": ["geneA"],
                "annot_gene_id": ["G1"],
                "has_overlap": [True],
                "distance": ["5"],
            }
        )
        out = canonicalize_annotation_result(
            raw, self._coord_df(), self._annot_df(), extra_columns=("distance",)
        )
        assert "distance" in out.columns

        # Declared extra column missing from the backend output.
        raw2 = raw.drop(columns=["distance"])
        with pytest.raises(CanonicalSchemaError, match="distance"):
            canonicalize_annotation_result(
                raw2, self._coord_df(), self._annot_df(), extra_columns=("distance",)
            )




if __name__ == "__main__":
    pytest.main([__file__, "-v"])