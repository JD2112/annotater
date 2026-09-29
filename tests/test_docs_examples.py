"""
Documentation example pins (user manual, docs/examples/).

The five worked examples in the AnnotateR user manual (docs/examples/)
use the tiny fixtures in data/examples/. This test pins the *expected*
results stated in those pages against BOTH engines through the real
application path (parse_and_normalize -> annotation feature filter ->
engine.intersect), so a semantics or engine change that breaks the
documented examples fails CI before it ships.

Expected values were derived from the SPEC section 8 semantics and
verified by actual runs on both engines (see the manual's example
pages); they are not copied from backend output.
"""

from __future__ import annotations

import pandas as pd
import pytest

from streamlit_app.core import BedtoolsEngine, PolarsBioEngine
from streamlit_app.core.normalization import parse_and_normalize

EXAMPLES_DIR = "data/examples"

ENGINES = [BedtoolsEngine, PolarsBioEngine]
ENGINE_IDS = ["bedtools", "polars-bio"]


def _load(path: str, feature_types=None) -> pd.DataFrame:
    df = parse_and_normalize(path)
    if feature_types and "feature" in df.columns:
        df = df[df["feature"].isin(feature_types)].copy()
    return df


def _run(engine_cls, coord_path, annot_path, mode, how, *,
         feature_types=None, use_strand=False, min_overlap=None):
    # The feature filter applies to the annotation file only (GFF/GTF),
    # mirroring the application behavior.
    coord = _load(coord_path)
    annot = _load(annot_path, feature_types)
    engine = engine_cls(use_strand=use_strand, min_overlap=min_overlap,
                        mode=mode)
    return engine.intersect(coord, annot, how=how)


def _matched_pairs(df: pd.DataFrame, coord_key: str, annot_key: str):
    m = df[df["has_overlap"] == True]  # noqa: E712
    return list(zip(m[coord_key], m[annot_key]))


@pytest.mark.parametrize("engine_cls", ENGINES, ids=ENGINE_IDS)
class TestExampleOneBedVsGff3:
    def test_default_gene_filter_left(self, engine_cls):
        res = _run(
            engine_cls,
            f"{EXAMPLES_DIR}/example_coordinates.bed",
            f"{EXAMPLES_DIR}/example_annotations.gff3",
            "overlap", "left", feature_types=["gene"],
        )
        assert len(res) == 6
        assert int(res["has_overlap"].sum()) == 3
        assert sorted(_matched_pairs(res, "coord_name", "annot_ID")) == [
            ("region1", "gene:ENSG001"),
            ("region3", "gene:ENSG002"),
            ("regionX", "gene:ENSG003"),
        ]
        # Canonical 0-based normalization of the GFF3 1-based gene:
        # GENE1 "50000 150000" -> [49999, 150000).
        g1 = res[res["annot_ID"] == "gene:ENSG001"].iloc[0]
        assert (g1["annot_start"], g1["annot_end"]) == (49999, 150000)
        # Unmatched rows carry canonical missing annotation values.
        unmatched = res[res["has_overlap"] == False]  # noqa: E712
        assert set(unmatched["coord_name"]) == {"region2", "region4", "regionY"}
        assert unmatched["annot_chr"].isna().all()

    def test_gene_plus_exon_filter_left(self, engine_cls):
        res = _run(
            engine_cls,
            f"{EXAMPLES_DIR}/example_coordinates.bed",
            f"{EXAMPLES_DIR}/example_annotations.gff3",
            "overlap", "left", feature_types=["gene", "exon"],
        )
        assert len(res) == 9
        assert int(res["has_overlap"].sum()) == 6
        pairs = _matched_pairs(res, "coord_name", "annot_ID")
        for query, annot in [
            ("region1", "gene:ENSG001"), ("region1", "exon:ENSE001"),
            ("region3", "gene:ENSG002"), ("region3", "exon:ENSE003"),
            ("regionX", "gene:ENSG003"), ("regionX", "exon:ENSE005"),
        ]:
            assert (query, annot) in pairs
        # Non-overlapping exons do not appear.
        assert not res["annot_ID"].isin(["exon:ENSE002", "exon:ENSE004"]).any()


@pytest.mark.parametrize("engine_cls", ENGINES, ids=ENGINE_IDS)
class TestExampleTwoMinOverlap:
    def test_inner_join(self, engine_cls):
        res = _run(
            engine_cls,
            f"{EXAMPLES_DIR}/example_min_overlap_coordinates.bed",
            f"{EXAMPLES_DIR}/example_min_overlap_annotations.bed",
            "overlap", "inner", min_overlap=0.5,
        )
        assert sorted(_matched_pairs(res, "coord_name", "annot_name")) == [
            ("q_full", "a_full"),
            ("q_part60", "a_part60"),
        ]

    def test_left_join(self, engine_cls):
        res = _run(
            engine_cls,
            f"{EXAMPLES_DIR}/example_min_overlap_coordinates.bed",
            f"{EXAMPLES_DIR}/example_min_overlap_annotations.bed",
            "overlap", "left", min_overlap=0.5,
        )
        assert len(res) == 3
        assert int(res["has_overlap"].sum()) == 2
        unmatched = res[res["has_overlap"] == False]  # noqa: E712
        assert list(unmatched["coord_name"]) == ["q_part40"]

    def test_inclusive_threshold(self, engine_cls):
        # Exactly 0.4 coverage qualifies at threshold 0.4 (>=, inclusive).
        res = _run(
            engine_cls,
            f"{EXAMPLES_DIR}/example_min_overlap_coordinates.bed",
            f"{EXAMPLES_DIR}/example_min_overlap_annotations.bed",
            "overlap", "inner", min_overlap=0.4,
        )
        assert sorted(_matched_pairs(res, "coord_name", "annot_name")) == [
            ("q_full", "a_full"),
            ("q_part40", "a_part40"),
            ("q_part60", "a_part60"),
        ]


@pytest.mark.parametrize("engine_cls", ENGINES, ids=ENGINE_IDS)
class TestExampleThreeStrand:
    def test_strand_off(self, engine_cls):
        res = _run(
            engine_cls,
            f"{EXAMPLES_DIR}/example_strand_coordinates.bed",
            f"{EXAMPLES_DIR}/example_strand_annotations.gff3",
            "overlap", "left", feature_types=["gene"],
        )
        assert len(res) == 3
        assert int(res["has_overlap"].sum()) == 3

    def test_strand_on(self, engine_cls):
        res = _run(
            engine_cls,
            f"{EXAMPLES_DIR}/example_strand_coordinates.bed",
            f"{EXAMPLES_DIR}/example_strand_annotations.gff3",
            "overlap", "left", feature_types=["gene"], use_strand=True,
        )
        assert len(res) == 3
        assert int(res["has_overlap"].sum()) == 1
        # Only q_plus / gene_same survives: opposite strands (q_minus)
        # and missing annotation strand (q_plus2) never match.
        assert _matched_pairs(res, "coord_name", "annot_ID") == [
            ("q_plus", "gene_same"),
        ]


@pytest.mark.parametrize("engine_cls", ENGINES, ids=ENGINE_IDS)
class TestExampleFourContainsWithin:
    def test_contains_left(self, engine_cls):
        res = _run(
            engine_cls,
            f"{EXAMPLES_DIR}/example_contains_within.bed",
            f"{EXAMPLES_DIR}/example_contains_within.bed",
            "contains", "left",
        )
        assert len(res) == 4
        assert int(res["has_overlap"].sum()) == 4
        assert sorted(_matched_pairs(res, "coord_name", "annot_name")) == [
            ("A", "A"), ("A", "B"), ("B", "B"), ("C", "C"),
        ]

    def test_within_left(self, engine_cls):
        res = _run(
            engine_cls,
            f"{EXAMPLES_DIR}/example_contains_within.bed",
            f"{EXAMPLES_DIR}/example_contains_within.bed",
            "within", "left",
        )
        assert len(res) == 4
        assert int(res["has_overlap"].sum()) == 4
        assert sorted(_matched_pairs(res, "coord_name", "annot_name")) == [
            ("A", "A"), ("B", "A"), ("B", "B"), ("C", "C"),
        ]


@pytest.mark.parametrize("engine_cls", ENGINES, ids=ENGINE_IDS)
class TestExampleFiveClosest:
    def test_closest_left(self, engine_cls):
        res = _run(
            engine_cls,
            f"{EXAMPLES_DIR}/example_closest_variants.vcf",
            f"{EXAMPLES_DIR}/example_closest_annotations.gff3",
            "closest", "left", feature_types=["gene"],
        )
        assert len(res) == 5
        assert int(res["has_overlap"].sum()) == 4

        by_id = {
            vid: res[res["coord_id"] == vid] for vid in ("v1", "v2", "v3", "v4")
        }
        # v1 inside GENE_A -> distance 0 (overlap clamps to 0).
        v1 = by_id["v1"]
        assert len(v1) == 1 and v1["distance"].iloc[0] == 0
        assert v1["annot_gene_id"].iloc[0] == "GENE_A"
        # v2: 50-base gap to GENE_A (1550 - 1500).
        v2 = by_id["v2"]
        assert len(v2) == 1 and v2["distance"].iloc[0] == 50
        assert v2["annot_gene_id"].iloc[0] == "GENE_A"
        # v3: exact tie (250 bases either way) -> both rows, in
        # annotation input order (GENE_B before GENE_C).
        v3 = by_id["v3"]
        assert len(v3) == 2
        assert list(v3["distance"]) == [250, 250]
        assert list(v3["annot_gene_id"]) == ["GENE_B", "GENE_C"]
        # v4: no annotation on chr2 -> unmatched, missing distance.
        v4 = by_id["v4"]
        assert len(v4) == 1
        assert bool(v4["has_overlap"].iloc[0]) is False
        assert pd.isna(v4["distance"].iloc[0])

    def test_closest_strand_on_vcf_query(self, engine_cls):
        # VCF carries no strand: every query row has missing strand, so
        # with strand matching on, nothing can match.
        res = _run(
            engine_cls,
            f"{EXAMPLES_DIR}/example_closest_variants.vcf",
            f"{EXAMPLES_DIR}/example_closest_annotations.gff3",
            "closest", "left", feature_types=["gene"], use_strand=True,
        )
        assert len(res) == 4
        assert int(res["has_overlap"].sum()) == 0