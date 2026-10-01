"""
Parser -> normalization -> engine -> canonical result -> oracle
(Task F, section 8).

Each scenario starts from real file text written to disk, goes through the
production parser and normalization, runs BOTH backends, and compares the
canonical results with the independent oracle over the parsed canonical
tables. Two further hand-computed layers guard the places where the
oracle cannot help (it starts after parsing):

- the parsed canonical coordinates are asserted against values converted
  BY HAND from the file text (1-based inclusive GFF/GTF/VCF -> 0-based
  half-open; VCF INFO/END; custom declared systems);
- the principal overlap/closest outcomes are asserted against hand-written
  expected pairs, and the oracle must reproduce them too.
"""

from __future__ import annotations

import pandas as pd
import pytest

from streamlit_app.core import CustomParser, normalize_intervals, parse_and_normalize

from .harness import check_fixture, frame_rows
from .reference import reference_pairs

BASE_CONFIGS = [
    {"mode": "overlap", "how": "inner", "use_strand": False, "min_overlap": None},
    {"mode": "overlap", "how": "left", "use_strand": False, "min_overlap": None},
    {"mode": "overlap", "how": "inner", "use_strand": False, "min_overlap": 0.5},
    {"mode": "contains", "how": "inner", "use_strand": False, "min_overlap": None},
    {"mode": "within", "how": "left", "use_strand": False, "min_overlap": None},
    {"mode": "closest", "how": "inner", "use_strand": False, "min_overlap": None},
    {"mode": "closest", "how": "left", "use_strand": False, "min_overlap": None},
]
STRAND_CONFIGS = [
    {"mode": "overlap", "how": "inner", "use_strand": True, "min_overlap": None},
    {"mode": "overlap", "how": "left", "use_strand": True, "min_overlap": None},
    {"mode": "closest", "how": "left", "use_strand": True, "min_overlap": None},
]


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def _spans(df):
    return df[["chr", "start", "end"]].values.tolist()


def _oracle_pairs(coord_df, annot_df, **config):
    return reference_pairs(
        frame_rows(coord_df), frame_rows(annot_df), how=config.get("how", "inner"),
        mode=config.get("mode", "overlap"), use_strand=config.get("use_strand", False),
        min_overlap=config.get("min_overlap"))


def _assert_backends_and_oracle_agree(coord_df, annot_df, configs, label):
    queries, annotations = frame_rows(coord_df), frame_rows(annot_df)
    problems = []
    for config in configs:
        problems += check_fixture(
            queries, annotations, config, tag=f"{label} {config}",
            frames=(coord_df, annot_df))
    assert not problems, "\n\n".join(problems[:3])


# --------------------------------------------------------------------------
# BED query + GFF3 annotation (all-numeric chromosome identifiers)
# --------------------------------------------------------------------------

BED_QUERY = (
    "1\t100\t200\tq_overlap\n"
    "1\t300\t400\tq_touch\n"
    "1\t1000\t1100\tq_far\n"
)
GFF3_ANNOT = (
    "##gff-version 3\n"
    "1\tsrc\tgene\t151\t250\t.\t+\t.\tID=g_overlap\n"
    "1\tsrc\tgene\t401\t500\t.\t-\t.\tID=g_touch\n"
    "1\tsrc\tgene\t1201\t1300\t.\t+\t.\tID=g_far\n"
)


@pytest.fixture
def bed_gff3(tmp_path):
    return (
        parse_and_normalize(_write(tmp_path, "q.bed", BED_QUERY)),
        parse_and_normalize(_write(tmp_path, "a.gff3", GFF3_ANNOT)),
    )


def test_bed_gff3_parsed_canonical_coordinates(bed_gff3):
    coord_df, annot_df = bed_gff3
    assert _spans(coord_df) == [["1", 100, 200], ["1", 300, 400], ["1", 1000, 1100]]
    # GFF3 1-based inclusive 151-250 -> [150, 250); 401-500 -> [400, 500);
    # 1201-1300 -> [1200, 1300)
    assert _spans(annot_df) == [["1", 150, 250], ["1", 400, 500], ["1", 1200, 1300]]


def test_bed_gff3_hand_computed_outcomes(bed_gff3):
    coord_df, annot_df = bed_gff3
    # q_overlap [100,200) x g_overlap [150,250): 50 bp overlap -> match
    # q_touch   [300,400) x g_touch   [400,500): touching only -> no match
    # q_far     [1000,1100): nothing within overlap range
    assert _oracle_pairs(coord_df, annot_df) == [(0, 0, None)]
    # closest: q_overlap -> g_overlap (0); q_touch -> g_touch (touching, 0);
    # q_far -> g_far (1200-1100 = 100)
    assert _oracle_pairs(coord_df, annot_df, mode="closest") == [
        (0, 0, 0), (1, 1, 0), (2, 2, 100)]


def test_bed_gff3_engines_match_oracle(bed_gff3):
    coord_df, annot_df = bed_gff3
    _assert_backends_and_oracle_agree(
        coord_df, annot_df, BASE_CONFIGS, "bed+gff3")


def test_bed_gff3_ucsc_numeric_chromosomes_are_not_altered(bed_gff3):
    coord_df, annot_df = bed_gff3
    assert set(coord_df["chr"]) == {"1"} and set(annot_df["chr"]) == {"1"}


# --------------------------------------------------------------------------
# BED query + GTF annotation
# --------------------------------------------------------------------------

BED_QUERY_2 = "chr2\t10\t20\tq1\nchr2\t100\t110\tq2\n"
GTF_ANNOT = (
    'chr2\tsrc\texon\t16\t30\t.\t+\t.\tgene_id "G1"; transcript_id "T1";\n'
    'chr2\tsrc\texon\t111\t120\t.\t-\t.\tgene_id "G2"; transcript_id "T2";\n'
)


def test_bed_gtf_end_to_end(tmp_path):
    coord_df = parse_and_normalize(_write(tmp_path, "q.bed", BED_QUERY_2))
    annot_df = parse_and_normalize(_write(tmp_path, "a.gtf", GTF_ANNOT))
    # GTF 1-based inclusive 16-30 -> [15, 30); 111-120 -> [110, 120)
    assert _spans(annot_df) == [["chr2", 15, 30], ["chr2", 110, 120]]
    # hand-computed: q1 [10,20) x [15,30) overlap 5 bp; q2 [100,110) x
    # [110,120) touching -> no overlap, but closest distance 0
    assert _oracle_pairs(coord_df, annot_df) == [(0, 0, None)]
    assert _oracle_pairs(coord_df, annot_df, mode="closest") == [(0, 0, 0), (1, 1, 0)]
    _assert_backends_and_oracle_agree(coord_df, annot_df, BASE_CONFIGS, "bed+gtf")


# --------------------------------------------------------------------------
# VCF query + GFF3 annotation
# --------------------------------------------------------------------------

VCF_QUERY = (
    "##fileformat=VCFv4.2\n"
    "##contig=<ID=1>\n"
    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    "1\t150\tsnv1\tA\tG\t50\tPASS\t.\n"
    "1\t1000\tsv1\tN\t<DEL>\t.\t.\tSVTYPE=DEL;END=1050\n"
    "1\t5000\tsnv2\tC\tT\t.\t.\t.\n"
)
GFF3_FOR_VCF = (
    "##gff-version 3\n"
    "1\tsrc\tgene\t100\t150\t.\t+\t.\tID=g1\n"
    "1\tsrc\tgene\t1050\t1100\t.\t+\t.\tID=g2\n"
    "1\tsrc\tgene\t5001\t5100\t.\t+\t.\tID=g3\n"
)


@pytest.fixture
def vcf_gff3(tmp_path):
    return (
        parse_and_normalize(_write(tmp_path, "q.vcf", VCF_QUERY)),
        parse_and_normalize(_write(tmp_path, "a.gff3", GFF3_FOR_VCF)),
    )


def test_vcf_gff3_parsed_canonical_coordinates(vcf_gff3):
    coord_df, annot_df = vcf_gff3
    # SNV POS=150 (1-based) -> [149, 150)
    # symbolic <DEL> POS=1000, INFO/END=1050 -> occupies 1-based 1000..1050
    #   inclusive -> [999, 1050)
    # SNV POS=5000 -> [4999, 5000)
    assert _spans(coord_df) == [["1", 149, 150], ["1", 999, 1050], ["1", 4999, 5000]]
    # GFF3 100-150 -> [99, 150); 1050-1100 -> [1049, 1100); 5001-5100 -> [5000, 5100)
    assert _spans(annot_df) == [["1", 99, 150], ["1", 1049, 1100], ["1", 5000, 5100]]


def test_vcf_gff3_hand_computed_outcomes(vcf_gff3):
    coord_df, annot_df = vcf_gff3
    # snv1 [149,150) is the LAST base of g1 [99,150): overlap (needs POS
    #   converted to 0-based, GFF end kept inclusive);
    # sv1 [999,1050) shares exactly one base [1049,1050) with g2 (needs
    #   INFO/END honored);
    # snv2 [4999,5000) merely touches g3 [5000,5100): no overlap.
    assert _oracle_pairs(coord_df, annot_df) == [(0, 0, None), (1, 1, None)]
    assert _oracle_pairs(coord_df, annot_df, mode="closest") == [
        (0, 0, 0), (1, 1, 0), (2, 2, 0)]
    # snv1 is contained in g1 (within), g1 does not lie inside snv1 (contains)
    assert _oracle_pairs(coord_df, annot_df, mode="within") == [(0, 0, None)]
    assert _oracle_pairs(coord_df, annot_df, mode="contains") == []


def test_vcf_gff3_engines_match_oracle(vcf_gff3):
    coord_df, annot_df = vcf_gff3
    _assert_backends_and_oracle_agree(
        coord_df, annot_df, BASE_CONFIGS, "vcf+gff3")


# --------------------------------------------------------------------------
# Custom query + custom annotation
# --------------------------------------------------------------------------

CUSTOM_QUERY = "chrom\tpos\tname\tstrand\nchr1\t100\tsnp1\t+\nchr1\t500\tsnp2\t-\n"
CUSTOM_ANNOT = (
    "chr\tstart\tend\tgene\tstrand\n"
    "chr1\t95\t105\tG_plus\t+\n"
    "chr1\t100\t110\tG_minus\t-\n"
    "chr1\t101\t110\tG_after\t+\n"
)


@pytest.fixture
def custom_tables(tmp_path):
    q_raw = CustomParser.parse(_write(tmp_path, "q.tsv", CUSTOM_QUERY))
    q_mapped = CustomParser.map_columns(
        q_raw, "chrom", "pos", None, ["name", "strand"])
    # Single-position mapping, exactly as streamlit_app.py "Apply column
    # mapping" does it for a declared 1-based system: end = start, so the
    # normalized interval is the one base [P-1, P).
    q_mapped["end"] = pd.to_numeric(q_mapped["start"])
    coord_df = normalize_intervals(q_mapped, coordinate_system="1-based")
    a_raw = CustomParser.parse(_write(tmp_path, "a.tsv", CUSTOM_ANNOT))
    annot_df = normalize_intervals(a_raw, coordinate_system="1-based")
    return coord_df, annot_df


def test_custom_parsed_canonical_coordinates_and_strand(custom_tables):
    coord_df, annot_df = custom_tables
    # single 1-based positions 100 / 500 -> exactly one base: [99,100), [499,500)
    assert _spans(coord_df) == [["chr1", 99, 100], ["chr1", 499, 500]]
    # explicit 1-based inclusive 95-105 -> [94,105); 100-110 -> [99,110);
    # 101-110 -> [100,110)
    assert _spans(annot_df) == [["chr1", 94, 105], ["chr1", 99, 110], ["chr1", 100, 110]]
    assert coord_df["strand"].tolist() == ["+", "-"]
    assert annot_df["strand"].tolist() == ["+", "-", "+"]


def test_custom_hand_computed_outcomes(custom_tables):
    coord_df, annot_df = custom_tables
    # snp1 [99,100): overlaps G_plus [94,105) and G_minus [99,110); only
    # touches G_after [100,110). snp2 [499,500) is on no annotation's span.
    assert _oracle_pairs(coord_df, annot_df) == [(0, 0, None), (0, 1, None)]
    # stranded: snp1 '+' keeps only G_plus
    assert _oracle_pairs(coord_df, annot_df, use_strand=True) == [(0, 0, None)]
    # closest: snp1 -> three-way tie at distance 0 (G_plus and G_minus
    # overlap, G_after touches), annotation input order; snp2 [499,500) ->
    # G_minus [99,110) gap 389, G_after [100,110) gap 389 (tie), G_plus
    # [94,105) gap 394
    assert _oracle_pairs(coord_df, annot_df, mode="closest") == [
        (0, 0, 0), (0, 1, 0), (0, 2, 0), (1, 1, 389), (1, 2, 389)]
    # stranded closest: snp2 '-' only sees G_minus [99,110): 499-110 = 389
    assert _oracle_pairs(coord_df, annot_df, mode="closest", use_strand=True) == [
        (0, 0, 0), (0, 2, 0), (1, 1, 389)]


def test_custom_engines_match_oracle(custom_tables):
    coord_df, annot_df = custom_tables
    _assert_backends_and_oracle_agree(
        coord_df, annot_df, BASE_CONFIGS + STRAND_CONFIGS, "custom+custom")
