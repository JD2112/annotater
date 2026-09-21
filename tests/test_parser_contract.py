"""
Parser/normalization contract tests (PLAN Task 2.5)

Locks down the four required source formats through the shared
backend-independent entry point ``streamlit_app.core.parse_and_normalize``
(plus ``normalize_intervals`` for mapped custom tables):

- BED (already 0-based half-open) passes through unchanged;
- GFF3 (1-based inclusive) is converted to canonical 0-based half-open;
- VCF (1-based POS, per-spec variant span) is converted to canonical
  0-based half-open, with INFO/END honored;
- custom CSV uses the user's explicitly declared coordinate system;
- known formats are never silently re-interpreted by a ``declared_system``
  override — the same source file always means the same coordinates.

All fixtures are minimal synthetic files written into ``tmp_path``.
"""

from __future__ import annotations

import pandas as pd
import pytest

from streamlit_app.core import (
    CustomParser,
    normalize_intervals,
    parse_and_normalize,
)
from streamlit_app.core.schema import (
    INTERVAL_COLUMNS,
    validate_canonical_interval_table,
)


def test_bed_is_already_canonical_half_open(tmp_path):
    bed = tmp_path / "fixture.bed"
    bed.write_text(
        "chrA\t10\t20\tgene1\t500\t+\n"
        "chrA\t30\t40\tgene2\t100\t-\n"
    )

    result = parse_and_normalize(str(bed))

    # BED is 0-based half-open: coordinates must pass through unchanged.
    assert result[["chr", "start", "end"]].values.tolist() == [
        ["chrA", 10, 20],
        ["chrA", 30, 40],
    ]
    # Canonical column order: chr, start, end first, then strand/metadata.
    assert list(result.columns[:3]) == list(INTERVAL_COLUMNS)
    assert result[["start", "end"]].dtypes.tolist() == ["int64", "int64"]
    # Metadata is preserved, including per-row strand.
    assert "name" in result.columns
    assert result["name"].tolist() == ["gene1", "gene2"]
    assert result["strand"].tolist() == ["+", "-"]
    validate_canonical_interval_table(result)


def test_gff3_one_based_inclusive_converts_to_half_open(tmp_path):
    gff = tmp_path / "fixture.gff3"
    gff.write_text(
        "##gff-version 3\n"
        "chrA\tref\tgene\t5\t15\t.\t+\t.\tID=g1;Name=GENE1\n"
        "chrA\tref\texon\t100\t150\t.\t-\t.\tID=e1\n"
    )

    result = parse_and_normalize(str(gff))

    # GFF3 is 1-based inclusive [S, E] -> canonical 0-based half-open
    # [S-1, E]: (5,15) -> (4,15); (100,150) -> (99,150).
    assert result[["chr", "start", "end"]].values.tolist() == [
        ["chrA", 4, 15],
        ["chrA", 99, 150],
    ]
    assert result[["start", "end"]].dtypes.tolist() == ["int64", "int64"]
    # Feature type and attributes survive as metadata.
    assert result["feature"].tolist() == ["gene", "exon"]
    assert result["strand"].tolist() == ["+", "-"]
    assert result["ID"].tolist() == ["g1", "e1"]
    validate_canonical_interval_table(result)


def test_vcf_pos_to_canonical_half_open(tmp_path):
    vcf = tmp_path / "fixture.vcf"
    vcf.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chrA\t5\t.\tA\tG\t.\tPASS\t.\n"
        "chrA\t100\tv2\tAC\tA,C\t30\tPASS\tEND=102\n"
    )

    result = parse_and_normalize(str(vcf))

    # VCF POS is 1-based. A pos-only variant occupies one base:
    # POS=5 -> [4, 5). With INFO/END=102 the span is [100, 102] 1-based
    # inclusive -> [99, 102) canonical.
    assert result[["chr", "start", "end"]].values.tolist() == [
        ["chrA", 4, 5],
        ["chrA", 99, 102],
    ]
    assert result[["start", "end"]].dtypes.tolist() == ["int64", "int64"]
    # Source metadata is retained (id, ref, alt, filter, info).
    assert result["ref"].tolist() == ["A", "AC"]
    assert result["alt"].tolist() == ["G", "A,C"]
    assert result["info"].tolist()[1] == "END=102"
    validate_canonical_interval_table(result)


def test_custom_csv_uses_declared_coordinate_system(tmp_path):
    csv = tmp_path / "fixture.csv"
    csv.write_text("chrom,pos,end,gene_id\nchrA,10,20,g1\nchrA,30,40,g2\n")

    def mapped() -> pd.DataFrame:
        raw = CustomParser.parse(str(csv))
        return CustomParser.map_columns(raw, "chrom", "pos", "end", ["gene_id"])

    one_based = normalize_intervals(mapped(), coordinate_system="1-based")
    # 1-based inclusive (10,20) -> (9,20); (30,40) -> (29,40).
    assert one_based[["chr", "start", "end"]].values.tolist() == [
        ["chrA", 9, 20],
        ["chrA", 29, 40],
    ]
    assert one_based["gene_id"].tolist() == ["g1", "g2"]
    validate_canonical_interval_table(one_based)

    zero_based = normalize_intervals(mapped(), coordinate_system="0-based")
    # 0-based half-open passes through unchanged.
    assert zero_based[["chr", "start", "end"]].values.tolist() == [
        ["chrA", 10, 20],
        ["chrA", 30, 40],
    ]


def test_known_format_is_not_reinterpreted_by_declared_system(tmp_path):
    """The same known source must not be silently re-interpreted by a
    different coordinate-system declaration: known formats have fixed,
    specification-defined semantics."""
    gff = tmp_path / "fixture.gff3"
    gff.write_text(
        "##gff-version 3\n"
        "chrA\tref\tgene\t5\t15\t.\t+\t.\tID=g1\n"
    )

    default = parse_and_normalize(str(gff))
    overridden = parse_and_normalize(str(gff), declared_system="0-based")

    # The override must not change the canonical interpretation of a known
    # format; a GFF3 start of 5 is 1-based inclusive either way.
    assert overridden[["chr", "start", "end"]].values.tolist() == [
        ["chrA", 4, 15]
    ]
    assert overridden[["chr", "start", "end"]].values.tolist() == default[
        ["chr", "start", "end"]
    ].values.tolist()


def test_custom_file_requires_explicit_mapping(tmp_path):
    """A custom file has no fixed coordinate columns; parse_and_normalize
    must raise rather than guess column semantics."""
    csv = tmp_path / "fixture.csv"
    csv.write_text("col_a,col_b,col_c\nx,10,20\n")

    with pytest.raises(ValueError):
        parse_and_normalize(str(csv))