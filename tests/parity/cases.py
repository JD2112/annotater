"""
Parity case lists (PLAN Task 3).

Each case carries explicit expected rows derived from genomic interval
semantics (see fixtures.py module doc). Coordinates are canonical:
0-based half-open ``[start, end)`` on a single chromosome ``chrA``
unless stated otherwise.

Expected row tuples: ``(query_row, annot_row_or_None)`` in canonical row
order. Overlap predicate: ``max(starts) < min(ends)``.

xfail marking is EXPLICIT per case and per engine (an empty reason means
"expected to pass for that engine today"). Deliberately, the default is
"no xfail": a newly added case whose engine does not yet conform FAILS
the suite instead of silently xfailing, and a case whose deviation has
been fixed XPASSes (strict) until its stale marker is removed.

Current per-engine status as of Task 5:

- Polars-Bio: conforms to the canonical result contract on the covered
  parity surface (canonical schema with explicit provenance, 0-based
  half-open coordinate semantics, deterministic ordering, left-mode
  reconstruction, backend error propagation).
- Bedtools: conforms to the canonical result contract on the covered
  parity surface (Task 5 rewrite: identity-only serialization,
  structural sentinel handling, canonical missing, empty-input
  handling, error propagation). No per-case xfail reasons remain.
"""

from __future__ import annotations

from .comparator import interval_table
from .fixtures import (
    CHR,
    ParityCase,
)

# ---------------------------------------------------------------------------
# Overlap semantics (inner)
# ---------------------------------------------------------------------------

OVERLAP_CASES = [
    ParityCase(
        "exact_interval_match",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        ((0, 0),),
    ),
    ParityCase(
        "partial_overlap_left",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [5], [15], feature=["f1"]),
        ((0, 0),),
    ),
    ParityCase(
        "partial_overlap_right",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [15], [25], feature=["f1"]),
        ((0, 0),),
    ),
    ParityCase(
        "annotation_inside_query",
        interval_table([CHR], [10], [30], gene=["g1"]),
        interval_table([CHR], [15], [20], feature=["f1"]),
        ((0, 0),),
    ),
    ParityCase(
        "query_inside_annotation",
        interval_table([CHR], [15], [20], gene=["g1"]),
        interval_table([CHR], [10], [30], feature=["f1"]),
        ((0, 0),),
    ),
    ParityCase(
        "different_chromosomes_no_overlap",
        interval_table(["chrA"], [10], [20], gene=["g1"]),
        interval_table(["chrB"], [10], [20], feature=["f1"]),
        (),
        # polars-bio passes today ONLY because the result is empty (nothing
        # to canonicalize); the schema deviation is still pinned by every
        # non-empty case and by test_backend_raw_diagnostics.
    ),
    ParityCase(
        "gap_of_one_base_no_overlap",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [21], [30], feature=["f1"]),
        (),
    ),
    ParityCase(
        "touching_boundaries_no_overlap",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [20], [25], feature=["f1"]),
        (),
    ),
    ParityCase(
        "one_base_intervals_exact",
        interval_table([CHR], [10], [11], gene=["g1"]),
        interval_table([CHR], [10], [11], feature=["f1"]),
        ((0, 0),),
    ),
    ParityCase(
        "adjacent_one_base_no_overlap",
        interval_table([CHR], [10], [11], gene=["g1"]),
        interval_table([CHR], [11], [12], feature=["f1"]),
        (),
    ),
    ParityCase(
        "one_base_overlap",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [19], [20], feature=["f1"]),
        ((0, 0),),
    ),
    ParityCase(
        "one_query_two_annotations",
        interval_table([CHR], [10], [30], gene=["g1"]),
        interval_table([CHR, CHR], [5, 25], [15, 35], feature=["f1", "f2"]),
        ((0, 0), (0, 1)),
    ),
    ParityCase(
        "one_annotation_two_queries",
        interval_table([CHR, CHR], [10, 20], [15, 25], gene=["g1", "g2"]),
        interval_table([CHR], [5], [30], feature=["f1"]),
        ((0, 0), (1, 0)),
    ),
    ParityCase(
        # q0[10,20): a0[18,22) yes, a1[24,30) no, a2[10,15) yes
        # q1[15,25): a0[18,22) yes, a1[24,30) yes (24<25), a2[10,15) touching at 15 no
        "many_to_many",
        interval_table([CHR, CHR], [10, 15], [20, 25], gene=["q0", "q1"]),
        interval_table([CHR] * 3, [18, 24, 10], [22, 30, 15], feature=["a0", "a1", "a2"]),
        ((0, 0), (0, 2), (1, 0), (1, 1)),
    ),
    ParityCase(
        "duplicate_queries_preserved",
        interval_table([CHR, CHR], [10, 10], [20, 20], gene=["g1", "g2"]),
        interval_table([CHR], [15], [25], feature=["f1"]),
        ((0, 0), (1, 0)),
    ),
    ParityCase(
        "duplicate_annotations_preserved",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR, CHR], [15, 15], [25, 25], feature=["f1", "f2"]),
        ((0, 0), (0, 1)),
    ),
    ParityCase(
        # two identical queries x two identical annotations -> 4 rows, multiplicity
        "duplicate_query_and_annotation",
        interval_table([CHR, CHR], [10, 10], [20, 20], gene=["g1", "g2"]),
        interval_table([CHR, CHR], [15, 15], [25, 25], feature=["f1", "f2"]),
        ((0, 0), (0, 1), (1, 0), (1, 1)),
    ),
]

# ---------------------------------------------------------------------------
# Boundary semantics (off-by-one matrix, incl. zero-based coordinates)
# ---------------------------------------------------------------------------

BOUNDARY_CASES = [
    ParityCase(
        # [0,1) vs [0,1): overlap at base 0
        "zero_start_exact_overlap",
        interval_table([CHR], [0], [1], gene=["g1"]),
        interval_table([CHR], [0], [1], feature=["f1"]),
        ((0, 0),),
    ),
    ParityCase(
        # [0,1) vs [1,2): touch at 1 -> no overlap (the 1-based-closed trap)
        "zero_start_touching_no_overlap",
        interval_table([CHR], [0], [1], gene=["g1"]),
        interval_table([CHR], [1], [2], feature=["f1"]),
        (),
    ),
    ParityCase(
        # [9,10) vs [10,11): touch at 10 -> no overlap
        "single_base_touching_no_overlap",
        interval_table([CHR], [9], [10], gene=["g1"]),
        interval_table([CHR], [10], [11], feature=["f1"]),
        (),
    ),
    ParityCase(
        # [9,11) vs [10,11): contains base 10 -> overlap
        "single_base_contained_overlap",
        interval_table([CHR], [9], [11], gene=["g1"]),
        interval_table([CHR], [10], [11], feature=["f1"]),
        ((0, 0),),
    ),
    ParityCase(
        # [0,5) vs [0,10): zero-based containment
        "zero_start_inside_annotation",
        interval_table([CHR], [0], [5], gene=["g1"]),
        interval_table([CHR], [0], [10], feature=["f1"]),
        ((0, 0),),
    ),
    ParityCase(
        # [0,5) vs [0,1): one-base annotation at the zero start
        "zero_start_one_base_annotation",
        interval_table([CHR], [0], [5], gene=["g1"]),
        interval_table([CHR], [0], [1], feature=["f1"]),
        ((0, 0),),
    ),
    ParityCase(
        # [0,10) vs [10,20): wide intervals touching at 10 -> no overlap
        "wide_touching_at_zero_region",
        interval_table([CHR], [0], [10], gene=["g1"]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        (),
    ),
    ParityCase(
        # 'chr0' and 'chr10' are distinct chromosome identifiers even though
        # their coordinates are identical (lexical-ordering trap).
        "distinct_chromosome_names_chr0_chr10",
        interval_table(["chr0"], [0], [10], gene=["g1"]),
        interval_table(["chr10"], [0], [10], feature=["f1"]),
        (),
    ),
]

# ---------------------------------------------------------------------------
# Left-join semantics
# ---------------------------------------------------------------------------

LEFT_CASES = [
    ParityCase(
        "left_matched_only",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [15], [25], feature=["f1"]),
        ((0, 0),),
        how="left",
    ),
    ParityCase(
        "left_unmatched_only",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [100], [200], feature=["f1"]),
        ((0, None),),
        how="left",
    ),
    ParityCase(
        "left_mixed_matched_unmatched",
        interval_table([CHR, CHR], [10, 100], [20, 200], gene=["g1", "g2"]),
        interval_table([CHR], [15], [25], feature=["f1"]),
        ((0, 0), (1, None)),
        how="left",
    ),
    ParityCase(
        "left_one_query_multiple_hits",
        interval_table([CHR], [10], [30], gene=["g1"]),
        interval_table([CHR, CHR], [5, 25], [15, 35], feature=["f1", "f2"]),
        ((0, 0), (0, 1)),
        how="left",
    ),
    ParityCase(
        "left_duplicate_unmatched_queries",
        interval_table([CHR, CHR], [100, 100], [200, 200], gene=["g1", "g2"]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        ((0, None), (1, None)),
        how="left",
    ),
    ParityCase(
        "left_all_queries_unmatched",
        interval_table([CHR, CHR], [10, 30], [20, 40], gene=["g1", "g2"]),
        interval_table([CHR], [100], [200], feature=["f1"]),
        ((0, None), (1, None)),
        how="left",
    ),
    ParityCase(
        # SPEC 7.2: left mode preserves every query row even when the
        # annotation table is empty.
        "left_empty_annotation_table",
        interval_table([CHR, CHR], [10, 100], [20, 200], gene=["g1", "g2"]),
        interval_table([], [], [], feature=[]),
        ((0, None), (1, None)),
        how="left",
    ),
    ParityCase(
        # no query rows -> no result rows (a valid empty result, not a failure)
        "left_empty_query_table",
        interval_table([], [], [], gene=[]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        (),
        how="left",
    ),
    ParityCase(
        # inner mode with an empty annotation table is a valid zero-hit
        # result; nothing to canonicalize, so no xfail marker
        "inner_empty_annotation_table",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([], [], [], feature=[]),
        (),
    ),
    ParityCase(
        "inner_empty_query_table",
        interval_table([], [], [], gene=[]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        (),
    ),
]

# ---------------------------------------------------------------------------
# Metadata provenance
# ---------------------------------------------------------------------------

METADATA_CASES = [
    ParityCase(
        # colliding metadata names on both sides must come out with explicit
        # coord_/annot_ provenance prefixes
        "metadata_colliding_names",
        interval_table([CHR], [10], [30], feature=["geneA"], score=["high"], id=["q-1"]),
        interval_table([CHR, CHR], [5, 25], [15, 35], feature=["exonA", "exonB"], score=["low1", "low2"], id=["a-1", "a-2"]),
        ((0, 0), (0, 1)),
    ),
    ParityCase(
        "metadata_arbitrary_strings",
        interval_table([CHR], [10], [20], name=["region #1 (frag)"]),
        interval_table([CHR], [15], [25], name=["TfAP2: site~A"]),
        ((0, 0),),
    ),
    ParityCase(
        # numeric metadata without missing values: bedtools round-trips the
        # inferred numeric type; expected values stay numeric
        "metadata_numeric_values",
        interval_table([CHR], [10], [20], score=[0.5], id=[7]),
        interval_table([CHR], [15], [25], feature=["f1"]),
        ((0, 0),),
    ),
    ParityCase(
        # boolean metadata without missing values
        "metadata_boolean_values",
        interval_table([CHR], [10], [20], flag=[True]),
        interval_table([CHR], [15], [25], flag=[False]),
        ((0, 0),),
    ),
    ParityCase(
        # missing metadata on MATCHED rows must be canonical missing (pd.NA),
        # never a backend sentinel
        "metadata_missing_values_matched_rows",
        interval_table([CHR, CHR], [10, 100], [20, 200], score=[None, 0.5]),
        interval_table([CHR, CHR], [15, 105], [25, 115], feature=["f1", "f2"]),
        ((0, 0), (1, 1)),
    ),
    ParityCase(
        # string metadata with numeric-looking values must keep its string type
        "metadata_string_numeric_looks",
        interval_table([CHR, CHR], [10, 100], [20, 200], label=["3.5", "4.5"]),
        interval_table([CHR, CHR], [15, 105], [25, 115], feature=["f1", "f2"]),
        ((0, 0), (1, 1)),
    ),
    ParityCase(
        # metadata columns must keep their input order in the result
        "metadata_column_order",
        interval_table([CHR], [10], [20], zeta=["z1"], alpha=["a1"]),
        interval_table([CHR], [15], [25], bb=["b1"], aa=["a2"]),
        ((0, 0),),
    ),
    ParityCase(
        # strand values round-trip as metadata (matching itself is tested in
        # the strand-aware cases; here only provenance/values are checked)
        "metadata_strand_values",
        interval_table([CHR], [10], [20], strand=["+"]),
        interval_table([CHR], [15], [25], strand=["-"]),
        ((0, 0),),
    ),
]

# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------

ORDERING_CASES = [
    ParityCase(
        # query input order is NOT coordinate order; result must follow input
        "query_input_order_not_coordinate_order",
        interval_table([CHR, CHR], [2000, 10], [2100, 20], gene=["qA", "qB"]),
        interval_table([CHR, CHR], [1900, 5], [2050, 15], feature=["aW", "aY"]),
        ((0, 0), (1, 1)),
    ),
    ParityCase(
        # annotation rows are listed out of coordinate order; per-query hit
        # order must follow annotation input order
        "annotation_order_within_query",
        interval_table([CHR], [0], [200], gene=["q"]),
        interval_table([CHR] * 3, [100, 5, 50], [150, 10, 60], feature=["aX", "aY", "aZ"]),
        ((0, 0), (0, 1), (0, 2)),
    ),
    ParityCase(
        # identical query rows: ordering between the two input rows must come
        # from input identity, not from coordinate values (multiplicity 4)
        "duplicate_rows_deterministic_order",
        interval_table([CHR, CHR], [10, 10], [20, 20], gene=["g1", "g2"]),
        interval_table([CHR, CHR], [15, 12], [25, 18], feature=["f1", "f2"]),
        ((0, 0), (0, 1), (1, 0), (1, 1)),
    ),
    ParityCase(
        # left mode: unmatched query row sits at its own query position,
        # after qA's hits, before any later query
        "left_matched_then_unmatched_positions",
        interval_table([CHR, CHR], [10, 500], [30, 600], gene=["qA", "qB"]),
        interval_table([CHR, CHR], [5, 25], [15, 35], feature=["f1", "f2"]),
        ((0, 0), (0, 1), (1, None)),
        how="left",
    ),
]

# ---------------------------------------------------------------------------
# min_overlap (PLAN Task 6A) — the query-fraction contract (SPEC 8.2).
#
# A matched pair qualifies iff overlap_length > 0 AND
# overlap_length / query_length >= min_overlap, where query_length is
# the length of the QUERY interval (query-relative, non-reciprocal, no
# aggregation across annotation rows). Expected pairs below are derived
# from that definition, never from backend output.
# ---------------------------------------------------------------------------

MIN_OVERLAP_CASES = [
    # 1. Exact full overlap: fraction 1.0 passes 0.0 / 0.5 / 1.0.
    ParityCase(
        "min_overlap_full_threshold_0",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"min_overlap": 0.0},
    ),
    ParityCase(
        "min_overlap_full_threshold_0_5",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"min_overlap": 0.5},
    ),
    ParityCase(
        "min_overlap_full_threshold_1",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"min_overlap": 1.0},
    ),
    # 2. Exactly half overlap: fraction 0.5. The 0.50 case pins `>=`,
    # not `>`.
    ParityCase(
        "min_overlap_half_threshold_below",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [15], [25], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"min_overlap": 0.49},
    ),
    ParityCase(
        "min_overlap_half_threshold_equal",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [15], [25], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"min_overlap": 0.5},
    ),
    ParityCase(
        "min_overlap_half_threshold_above",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [15], [25], feature=["f1"]),
        (),
        engine_kwargs={"min_overlap": 0.51},
    ),
    # 3. One-base overlap: fraction 0.1.
    ParityCase(
        "min_overlap_one_base_threshold_equal",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [19], [30], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"min_overlap": 0.1},
    ),
    ParityCase(
        "min_overlap_one_base_threshold_above",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [19], [30], feature=["f1"]),
        (),
        engine_kwargs={"min_overlap": 0.11},
    ),
    # 4. Touching intervals: overlap 0, never a match even at min_overlap=0
    # (ordinary positive overlap remains required).
    ParityCase(
        "min_overlap_zero_touching_no_match",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [20], [30], feature=["f1"]),
        (),
        engine_kwargs={"min_overlap": 0.0},
    ),
    # 5. Annotation larger than query: fraction of the QUERY is 1.0 even
    # though only 10% of the annotation is covered (query-relative).
    ParityCase(
        "min_overlap_annotation_larger_threshold_1",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [0], [100], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"min_overlap": 1.0},
    ),
    # 6. Query larger than annotation: fraction of the query is 0.1.
    ParityCase(
        "min_overlap_query_larger_threshold_equal",
        interval_table([CHR], [0], [100], gene=["g1"]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"min_overlap": 0.1},
    ),
    ParityCase(
        "min_overlap_query_larger_threshold_above",
        interval_table([CHR], [0], [100], gene=["g1"]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        (),
        engine_kwargs={"min_overlap": 0.11},
    ),
    # 7. Reciprocal distinction: annotation coverage (10/100 = 0.1) is
    # irrelevant; only the query fraction (1.0) counts. A reciprocal
    # requirement (bedtools -r) would wrongly reject this pair at 1.0.
    ParityCase(
        "min_overlap_not_reciprocal",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [10], [110], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"min_overlap": 1.0},
    ),
    # 8. Coverage from multiple annotation rows is NOT aggregated: two
    # 0.30 annotations do not satisfy a 0.5 threshold.
    ParityCase(
        "min_overlap_no_aggregation_inner",
        interval_table([CHR], [0], [100], gene=["g1"]),
        interval_table([CHR, CHR], [0, 30], [30, 60], feature=["f1", "f2"]),
        (),
        engine_kwargs={"min_overlap": 0.5},
    ),
    ParityCase(
        "min_overlap_no_aggregation_left",
        interval_table([CHR], [0], [100], gene=["g1"]),
        interval_table([CHR, CHR], [0, 30], [30, 60], feature=["f1", "f2"]),
        ((0, None),),
        how="left",
        engine_kwargs={"min_overlap": 0.5},
    ),
    # 9. One qualifying (0.75) and one failing (0.25) annotation: only the
    # qualifying pair is emitted; no unmatched row accompanies it.
    ParityCase(
        "min_overlap_one_pass_one_fail",
        interval_table([CHR], [0], [100], gene=["g1"]),
        interval_table([CHR, CHR], [0, 25], [25, 100], feature=["f1", "f2"]),
        ((0, 1),),
        engine_kwargs={"min_overlap": 0.5},
    ),
    # 10. Multiple qualifying annotations: both remain, in annotation
    # input order (the 0.1 row is filtered, not reordered around).
    ParityCase(
        "min_overlap_multiple_qualifying_order",
        interval_table([CHR], [0], [100], gene=["g1"]),
        interval_table([CHR] * 3, [0, 40, 50], [60, 100, 60], feature=["f1", "f2", "f3"]),
        ((0, 0), (0, 1)),
        engine_kwargs={"min_overlap": 0.5},
    ),
    # 11. Duplicate query rows with distinct identity are filtered
    # independently (the 0.25 row fails for both queries).
    ParityCase(
        "min_overlap_duplicate_queries",
        interval_table([CHR, CHR], [0, 0], [100, 100], gene=["g1", "g2"]),
        interval_table([CHR, CHR], [0, 0], [25, 60], feature=["f1", "f2"]),
        ((0, 1), (1, 1)),
        engine_kwargs={"min_overlap": 0.5},
    ),
    ParityCase(
        "min_overlap_duplicate_queries_left",
        interval_table([CHR, CHR], [0, 0], [100, 100], gene=["g1", "g2"]),
        interval_table([CHR, CHR], [0, 0], [25, 60], feature=["f1", "f2"]),
        ((0, 1), (1, 1)),
        how="left",
        engine_kwargs={"min_overlap": 0.5},
    ),
    # 11b. Duplicate query rows whose only matches all fail the threshold:
    # both queries appear exactly once, unmatched (left reconstruction).
    ParityCase(
        "min_overlap_duplicate_queries_left_failing",
        interval_table([CHR, CHR], [0, 0], [100, 100], gene=["g1", "g2"]),
        interval_table([CHR], [0], [25], feature=["f1"]),
        ((0, None), (1, None)),
        how="left",
        engine_kwargs={"min_overlap": 0.5},
    ),
    # 12. Duplicate qualifying annotations: no deduplication; multiplicity
    # follows input rows.
    ParityCase(
        "min_overlap_duplicate_annotations",
        interval_table([CHR], [0], [100], gene=["g1"]),
        interval_table([CHR, CHR], [0, 0], [60, 60], feature=["f1", "f2"]),
        ((0, 0), (0, 1)),
        engine_kwargs={"min_overlap": 0.5},
    ),
    # 13. Metadata survives threshold filtering unchanged, including
    # missing values on the surviving matched row.
    ParityCase(
        "min_overlap_metadata_preserved",
        interval_table([CHR], [0], [100], gene=["g1"], score=[0.5]),
        interval_table([CHR, CHR], [0, 0], [25, 75], feature=["f1", "f2"], label=["3.5", None]),
        ((0, 1),),
        engine_kwargs={"min_overlap": 0.5},
    ),
    # Left mode after filtering: query 0 has a qualifying match, query 1's
    # only match fails the threshold (=> unmatched, not a failed match
    # row), query 2 has no match at all.
    ParityCase(
        "min_overlap_left_mixed_qualifying",
        interval_table([CHR] * 3, [0, 200, 500], [100, 300, 600], gene=["g1", "g2", "g3"]),
        interval_table([CHR, CHR], [0, 200], [75, 225], feature=["f1", "f2"]),
        ((0, 0), (1, None), (2, None)),
        how="left",
        engine_kwargs={"min_overlap": 0.5},
    ),
    # 14. Precision pinning (Task 6A review): 1-base overlap on a
    # length-3 query, threshold 1/3. 1/3 == 1/3.0 in IEEE-754 doubles,
    # so the inclusive >= comparison passes exactly.
    ParityCase(
        "min_overlap_ones_third_boundary",
        interval_table([CHR], [0], [3], gene=["g1"]),
        interval_table([CHR], [2], [10], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"min_overlap": 1 / 3},
    ),
    # 15. Scope pinning (Task 6A review; updated by Task 6D): SPEC 8.2 is
    # defined for the overlap method, so the min_overlap post-filter is
    # NOT applied in within mode (SPEC 8.5). The pair is a PARTIAL
    # overlap with query fraction 0.5, which would satisfy
    # ``min_overlap=0.5`` (the pre-Task-6D within placeholder was plain
    # overlap for polars-bio, so this pair qualified); the normative
    # ``within`` predicate rejects it because the annotation does not
    # contain the query. Note the exemption itself is not observable for
    # a genuine within pair: full query coverage means the query fraction
    # is exactly 1.0, so any valid threshold is satisfied anyway.
    ParityCase(
        "min_overlap_within_mode_not_applied",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [5], [15], feature=["f1"]),
        (),
        engine_kwargs={"min_overlap": 0.5, "mode": "within"},
    ),
]

# ---------------------------------------------------------------------------
# Strand (PLAN Task 6B) — the same-strand contract (SPEC 8.3).
#
# use_strand=False: strand does not participate in match qualification;
# matching is by the interval predicate alone (pre-Task-6B behavior).
#
# use_strand=True: a pair qualifies only if BOTH rows carry an explicit
# canonical strand ("+" or "-") AND the strands are equal AND the
# interval predicate also qualifies. Missing/unknown strand (pd.NA,
# absent strand column) is NOT a wildcard and NOT a strand: unknown vs
# unknown does not match. Strand composes with min_overlap by logical
# AND (no precedence). In left mode a query whose geometrical overlaps
# all fail the strand predicate is unmatched exactly once.
#
# Expected rows below are derived from that definition, never from
# backend output.
# ---------------------------------------------------------------------------

STRAND_CASES = [
    # Pre-Task-6B anchor (SPEC 8.3): when use_strand=False, strand MUST
    # NOT affect matching. Cross-strand pairs still overlap.
    ParityCase(
        "use_strand_false_ignores_strand",
        interval_table([CHR, CHR], [10, 2000], [20, 2100], gene=["g1", "g2"], strand=["+", "-"]),
        interval_table([CHR, CHR], [15, 1900], [25, 2050], feature=["f1", "f2"], strand=["-", "+"]),
        ((0, 0), (1, 1)),
    ),
    # 1. Same positive strand: matches with and without strand filtering.
    ParityCase(
        "strand_same_positive_matches_unstranded",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR], [15], [25], feature=["f1"], strand=["+"]),
        ((0, 0),),
    ),
    ParityCase(
        "strand_same_positive_matches_stranded",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR], [15], [25], feature=["f1"], strand=["+"]),
        ((0, 0),),
        engine_kwargs={"use_strand": True},
    ),
    # 2. Same negative strand: matches in stranded mode.
    ParityCase(
        "strand_same_negative_matches_stranded",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["-"]),
        interval_table([CHR], [15], [25], feature=["f1"], strand=["-"]),
        ((0, 0),),
        engine_kwargs={"use_strand": True},
    ),
    # 3. Opposite strands: match unstranded, fail stranded (both directions).
    ParityCase(
        "strand_opposite_plus_minus_matches_unstranded",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR], [15], [25], feature=["f1"], strand=["-"]),
        ((0, 0),),
    ),
    ParityCase(
        "strand_opposite_plus_minus_fails_stranded",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR], [15], [25], feature=["f1"], strand=["-"]),
        (),
        engine_kwargs={"use_strand": True},
    ),
    ParityCase(
        "strand_opposite_minus_plus_fails_stranded",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["-"]),
        interval_table([CHR], [15], [25], feature=["f1"], strand=["+"]),
        (),
        engine_kwargs={"use_strand": True},
    ),
    # 4. Query strand missing: match unstranded, fail stranded (missing is
    # NOT a wildcard).
    ParityCase(
        "strand_query_missing_matches_unstranded",
        interval_table([CHR], [10], [20], gene=["g1"], strand=[None]),
        interval_table([CHR], [15], [25], feature=["f1"], strand=["+"]),
        ((0, 0),),
    ),
    ParityCase(
        "strand_query_missing_fails_stranded",
        interval_table([CHR], [10], [20], gene=["g1"], strand=[None]),
        interval_table([CHR], [15], [25], feature=["f1"], strand=["+"]),
        (),
        engine_kwargs={"use_strand": True},
    ),
    # 5. Annotation strand missing: symmetric expectation.
    ParityCase(
        "strand_annot_missing_matches_unstranded",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR], [15], [25], feature=["f1"], strand=[None]),
        ((0, 0),),
    ),
    ParityCase(
        "strand_annot_missing_fails_stranded",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR], [15], [25], feature=["f1"], strand=[None]),
        (),
        engine_kwargs={"use_strand": True},
    ),
    # 6. Both strands missing: unknown vs unknown is NOT a stranded match.
    ParityCase(
        "strand_both_missing_matches_unstranded",
        interval_table([CHR], [10], [20], gene=["g1"], strand=[None]),
        interval_table([CHR], [15], [25], feature=["f1"], strand=[None]),
        ((0, 0),),
    ),
    ParityCase(
        "strand_both_missing_fails_stranded",
        interval_table([CHR], [10], [20], gene=["g1"], strand=[None]),
        interval_table([CHR], [15], [25], feature=["f1"], strand=[None]),
        (),
        engine_kwargs={"use_strand": True},
    ),
    # 7 ("." source values). At the canonical layer "." is normalized to
    # missing BEFORE the engine sees it (pinned in
    # test_strand_dot_source_value_not_wildcard); a canonical missing
    # strand from that normalization path is exactly the missing-strand
    # semantics of cases 4-6 above.
    # 8. One query, two annotation strands: stranded mode keeps only the
    # same-strand annotation; unstranded keeps both (annotation input
    # order).
    ParityCase(
        "strand_one_query_two_annotation_strands_unstranded",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR, CHR], [15, 15], [25, 25], feature=["f1", "f2"], strand=["+", "-"]),
        ((0, 0), (0, 1)),
    ),
    ParityCase(
        "strand_one_query_two_annotation_strands_stranded",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR, CHR], [15, 15], [25, 25], feature=["f1", "f2"], strand=["+", "-"]),
        ((0, 0),),
        engine_kwargs={"use_strand": True},
    ),
    # 9. Duplicate same-strand annotations: no deduplication.
    ParityCase(
        "strand_duplicate_annotations_preserved",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR, CHR], [15, 15], [25, 25], feature=["f1", "f2"], strand=["+", "+"]),
        ((0, 0), (0, 1)),
        engine_kwargs={"use_strand": True},
    ),
    # 10. Duplicate same-strand queries: distinct identity preserved.
    ParityCase(
        "strand_duplicate_queries_preserved",
        interval_table([CHR, CHR], [10, 10], [20, 20], gene=["g1", "g2"], strand=["+", "+"]),
        interval_table([CHR], [15], [25], feature=["f1"], strand=["+"]),
        ((0, 0), (1, 0)),
        engine_kwargs={"use_strand": True},
    ),
    # 11. Left mismatch only: geometrical overlap with the wrong strand is
    # NOT a match; exactly one unmatched query row.
    ParityCase(
        "strand_left_mismatch_only_unmatched",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR], [15], [25], feature=["f1"], strand=["-"]),
        ((0, None),),
        how="left",
        engine_kwargs={"use_strand": True},
    ),
    # 12. Left mixed: only the qualifying match is emitted; NO unmatched
    # query row accompanies it.
    ParityCase(
        "strand_left_mixed_only_qualifying_emitted",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR, CHR], [15, 15], [25, 25], feature=["f1", "f2"], strand=["-", "+"]),
        ((0, 1),),
        how="left",
        engine_kwargs={"use_strand": True},
    ),
    # 13. Different chromosomes: strand must not create a match where the
    # chromosome predicate fails.
    ParityCase(
        "strand_different_chromosomes_no_match_stranded",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table(["chrB"], [10], [20], feature=["f1"], strand=["+"]),
        (),
        engine_kwargs={"use_strand": True},
    ),
    # 14. Touching intervals: half-open semantics stay authoritative —
    # no match even on the same strand.
    ParityCase(
        "strand_touching_same_strand_no_match_unstranded",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR], [20], [30], feature=["f1"], strand=["+"]),
        (),
    ),
    ParityCase(
        "strand_touching_same_strand_no_match_stranded",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR], [20], [30], feature=["f1"], strand=["+"]),
        (),
        engine_kwargs={"use_strand": True},
    ),
    # 15. Strand AND min_overlap both pass (0.5 >= 0.5): match.
    ParityCase(
        "strand_and_min_overlap_both_pass",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR], [15], [25], feature=["f1"], strand=["+"]),
        ((0, 0),),
        engine_kwargs={"use_strand": True, "min_overlap": 0.5},
    ),
    # 16. min_overlap passes (0.5) but strand fails: no match (no
    # precedence: neither predicate bypasses the other).
    ParityCase(
        "strand_fail_min_overlap_pass_no_match",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR], [15], [25], feature=["f1"], strand=["-"]),
        (),
        engine_kwargs={"use_strand": True, "min_overlap": 0.5},
    ),
    # 17. Strand passes but min_overlap fails (0.5 < 0.51): no match.
    ParityCase(
        "strand_pass_min_overlap_fail_no_match",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR], [15], [25], feature=["f1"], strand=["+"]),
        (),
        engine_kwargs={"use_strand": True, "min_overlap": 0.51},
    ),
    # 18. Left reconstruction with both predicates: the query has two
    # geometrical overlaps — one fails strand ("-"), one fails the
    # threshold (2/10 = 0.2 < 0.5 on the "+" annotation [19,21)).
    # Result: exactly one unmatched query row.
    ParityCase(
        "strand_min_overlap_left_reconstruction",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR, CHR], [15, 19], [25, 21], feature=["f1", "f2"], strand=["-", "+"]),
        ((0, None),),
        how="left",
        engine_kwargs={"use_strand": True, "min_overlap": 0.5},
    ),
    # Missing strand COLUMN: treated as canonical unknown strand (no
    # stranded matches, no crash, no silent fall-back to unstranded
    # mode); identical for both engines.
    ParityCase(
        "strand_missing_column_query_no_match",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [15], [25], feature=["f1"], strand=["+"]),
        (),
        engine_kwargs={"use_strand": True},
    ),
    ParityCase(
        "strand_missing_column_annot_no_match",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR], [15], [25], feature=["f1"]),
        (),
        engine_kwargs={"use_strand": True},
    ),
    ParityCase(
        "strand_missing_column_left_all_unmatched",
        interval_table([CHR, CHR], [10, 100], [20, 200], gene=["g1", "g2"]),
        interval_table([CHR, CHR], [15, 105], [25, 215], feature=["f1", "f2"], strand=["+", "+"]),
        ((0, None), (1, None)),
        how="left",
        engine_kwargs={"use_strand": True},
    ),
]

# ---------------------------------------------------------------------------
# Contains (PLAN Task 6C) — SPEC 8.4.
#
# contains(Q, A) means the QUERY interval fully contains the ANNOTATION
# interval:
#
#     q_start <= a_start AND q_end >= a_end
#
# Boundary equality counts: identical intervals and shared left/right
# boundaries all qualify. Annotation-contains-query is the ``within``
# direction and does NOT qualify; partial overlaps and touching
# intervals do not qualify. contains is deliberately NOT
# ``min_overlap == 1.0`` (SPEC 8.2 measures query coverage and is
# defined for overlap mode only), and ``min_overlap`` is not applied in
# contains mode. Strand composes by logical AND (SPEC 8.3). In left mode
# a query with zero qualifying annotations is emitted exactly once as
# unmatched.
#
# Expected rows below are derived from that definition, never from
# backend output.
# ---------------------------------------------------------------------------

CONTAINS_CASES = [
    # 1. Strict containment: query strictly larger on both sides.
    ParityCase(
        "contains_strict",
        interval_table([CHR], [10], [30], gene=["g1"]),
        interval_table([CHR], [15], [20], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"mode": "contains"},
    ),
    # 2. Exact equality: equality satisfies containment.
    ParityCase(
        "contains_exact_equality",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"mode": "contains"},
    ),
    # 3. Shared left boundary, query extends farther right.
    ParityCase(
        "contains_shared_left_boundary",
        interval_table([CHR], [10], [30], gene=["g1"]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"mode": "contains"},
    ),
    # 4. Shared right boundary, query starts earlier.
    ParityCase(
        "contains_shared_right_boundary",
        interval_table([CHR], [5], [20], gene=["g1"]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"mode": "contains"},
    ),
    # 5. Annotation contains query: the ``within`` direction, not contains.
    ParityCase(
        "contains_annotation_contains_query_no_match",
        interval_table([CHR], [15], [20], gene=["g1"]),
        interval_table([CHR], [10], [30], feature=["f1"]),
        (),
        engine_kwargs={"mode": "contains"},
    ),
    # 6. Partial right overlap: overlaps, but the annotation is not contained.
    ParityCase(
        "contains_partial_right_overlap_no_match",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [15], [25], feature=["f1"]),
        (),
        engine_kwargs={"mode": "contains"},
    ),
    # 7. Partial left overlap.
    ParityCase(
        "contains_partial_left_overlap_no_match",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [5], [15], feature=["f1"]),
        (),
        engine_kwargs={"mode": "contains"},
    ),
    # 8. Touching right: no positive overlap, so no containment.
    ParityCase(
        "contains_touching_right_no_match",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [20], [25], feature=["f1"]),
        (),
        engine_kwargs={"mode": "contains"},
    ),
    # 9. Touching left.
    ParityCase(
        "contains_touching_left_no_match",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [5], [10], feature=["f1"]),
        (),
        engine_kwargs={"mode": "contains"},
    ),
    # 10. Different chromosome: never a match.
    ParityCase(
        "contains_different_chromosomes_no_match",
        interval_table([CHR], [10], [30], gene=["g1"]),
        interval_table(["chrB"], [15], [20], feature=["f1"]),
        (),
        engine_kwargs={"mode": "contains"},
    ),
    # 11. Multiple contained annotations: all three qualify, in annotation
    # input order (including the shared right boundary [90,100)).
    ParityCase(
        "contains_multiple_contained",
        interval_table([CHR], [0], [100], gene=["g1"]),
        interval_table([CHR] * 3, [10, 30, 90], [20, 40, 100], feature=["a1", "a2", "a3"]),
        ((0, 0), (0, 1), (0, 2)),
        engine_kwargs={"mode": "contains"},
    ),
    # 11b. Annotation LIST order, not coordinate order, defines hit order.
    ParityCase(
        "contains_multiple_contained_input_order_not_coordinate",
        interval_table([CHR], [0], [100], gene=["g1"]),
        interval_table([CHR] * 3, [30, 90, 10], [40, 100, 20], feature=["a1", "a2", "a3"]),
        ((0, 0), (0, 1), (0, 2)),
        engine_kwargs={"mode": "contains"},
    ),
    # 12. Mixed contained and non-contained: only the genuinely contained
    # annotation qualifies (annotation-contains-query and partial overlap
    # both fail).
    ParityCase(
        "contains_mixed_contained_partial_and_container",
        interval_table([CHR], [10], [30], gene=["g1"]),
        interval_table([CHR] * 3, [0, 15, 20], [100, 20, 40], feature=["a1", "a2", "a3"]),
        ((0, 1),),
        engine_kwargs={"mode": "contains"},
    ),
    # 13. Duplicate queries: query identity and multiplicity preserved.
    ParityCase(
        "contains_duplicate_queries_preserved",
        interval_table([CHR, CHR], [10, 10], [30, 30], gene=["q1", "q2"]),
        interval_table([CHR], [15], [20], feature=["f1"]),
        ((0, 0), (1, 0)),
        engine_kwargs={"mode": "contains"},
    ),
    # 14. Duplicate annotations: no deduplication.
    ParityCase(
        "contains_duplicate_annotations_preserved",
        interval_table([CHR], [10], [30], gene=["g1"]),
        interval_table([CHR, CHR], [15, 15], [20, 20], feature=["f1", "f2"]),
        ((0, 0), (0, 1)),
        engine_kwargs={"mode": "contains"},
    ),
    # 15. Left mode, no qualifying matches: overlapping annotations exist
    # but none is fully contained => exactly one unmatched query row.
    ParityCase(
        "contains_left_no_qualifying_match",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [15], [25], feature=["f1"]),
        ((0, None),),
        how="left",
        engine_kwargs={"mode": "contains"},
    ),
    # 16. Left mode, mixed: emit only the contained match, NO unmatched row.
    ParityCase(
        "contains_left_mixed_only_contained",
        interval_table([CHR], [10], [30], gene=["g1"]),
        interval_table([CHR, CHR], [15, 20], [20, 40], feature=["f1", "f2"]),
        ((0, 0),),
        how="left",
        engine_kwargs={"mode": "contains"},
    ),
    # Left mode across several queries: contained / no-qualifying /
    # annotation-contains-query, in query input order.
    ParityCase(
        "contains_left_mixed_queries",
        interval_table([CHR] * 3, [10, 200, 500], [30, 300, 520], gene=["q1", "q2", "q3"]),
        interval_table([CHR] * 3, [15, 250, 0], [20, 400, 1000], feature=["a1", "a2", "a3"]),
        ((0, 0), (1, None), (2, None)),
        how="left",
        engine_kwargs={"mode": "contains"},
    ),
    # 17. contains-vs-min_overlap asymmetry A: Q[10,20), A[0,100).
    # overlap + min_overlap=1.0 qualifies (the whole query is covered) but
    # contains fails (the query does not contain the annotation). The
    # overlap counterpart is MIN_OVERLAP_CASES["min_overlap_annotation_larger_threshold_1"]
    # and both directions are asserted together in test_contains_parity.
    ParityCase(
        "contains_annotation_larger_no_match",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [0], [100], feature=["f1"]),
        (),
        engine_kwargs={"mode": "contains"},
    ),
    # 18. contains-vs-min_overlap asymmetry B: Q[0,100), A[10,20).
    # contains qualifies but overlap + min_overlap=1.0 fails (query
    # fraction 0.1). The overlap counterpart is
    # MIN_OVERLAP_CASES["min_overlap_query_larger_threshold_above"].
    ParityCase(
        "contains_query_larger_match",
        interval_table([CHR], [0], [100], gene=["g1"]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"mode": "contains"},
    ),
    # min_overlap is NOT applied in contains mode (SPEC 8.2 is scoped to
    # the overlap method). The pair IS contained (fraction 0.1 < 0.9); a
    # wrongly applied threshold would drop it. Inner and left.
    ParityCase(
        "contains_min_overlap_not_applied",
        interval_table([CHR], [0], [100], gene=["g1"]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"mode": "contains", "min_overlap": 0.9},
    ),
    ParityCase(
        "contains_min_overlap_not_applied_left",
        interval_table([CHR], [0], [100], gene=["g1"]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        ((0, 0),),
        how="left",
        engine_kwargs={"mode": "contains", "min_overlap": 0.9},
    ),
    # 19-22. Strand composes with contains by logical AND (SPEC 8.3).
    ParityCase(
        "contains_strand_same_matches",
        interval_table([CHR], [10], [30], gene=["g1"], strand=["+"]),
        interval_table([CHR], [15], [20], feature=["f1"], strand=["+"]),
        ((0, 0),),
        engine_kwargs={"mode": "contains", "use_strand": True},
    ),
    ParityCase(
        "contains_strand_same_negative_matches",
        interval_table([CHR], [10], [30], gene=["g1"], strand=["-"]),
        interval_table([CHR], [15], [20], feature=["f1"], strand=["-"]),
        ((0, 0),),
        engine_kwargs={"mode": "contains", "use_strand": True},
    ),
    ParityCase(
        "contains_strand_opposite_no_match",
        interval_table([CHR], [10], [30], gene=["g1"], strand=["+"]),
        interval_table([CHR], [15], [20], feature=["f1"], strand=["-"]),
        (),
        engine_kwargs={"mode": "contains", "use_strand": True},
    ),
    ParityCase(
        "contains_strand_missing_no_match",
        interval_table([CHR], [10], [30], gene=["g1"], strand=[None]),
        interval_table([CHR], [15], [20], feature=["f1"], strand=[None]),
        (),
        engine_kwargs={"mode": "contains", "use_strand": True},
    ),
    ParityCase(
        "contains_strand_missing_column_no_match",
        interval_table([CHR], [10], [30], gene=["g1"]),
        interval_table([CHR], [15], [20], feature=["f1"]),
        (),
        engine_kwargs={"mode": "contains", "use_strand": True},
    ),
    ParityCase(
        "contains_strand_false_ignores_strand",
        interval_table([CHR], [10], [30], gene=["g1"], strand=["+"]),
        interval_table([CHR], [15], [20], feature=["f1"], strand=["-"]),
        ((0, 0),),
        engine_kwargs={"mode": "contains"},
    ),
    # 22. Metadata preserved exactly on contained matches.
    ParityCase(
        "contains_metadata_preserved",
        interval_table([CHR], [10], [30], gene=["g1"], score=[0.5]),
        interval_table([CHR], [15], [20], feature=["f1"], label=["3.5"], note=[None]),
        ((0, 0),),
        engine_kwargs={"mode": "contains"},
    ),
    # Empty inputs (SPEC 7.2 / engine-contract section 6).
    ParityCase(
        "contains_inner_empty_query",
        interval_table([], [], [], gene=[]),
        interval_table([CHR], [15], [20], feature=["f1"]),
        (),
        engine_kwargs={"mode": "contains"},
    ),
    ParityCase(
        "contains_inner_empty_annot",
        interval_table([CHR], [10], [30], gene=["g1"]),
        interval_table([], [], [], feature=[]),
        (),
        engine_kwargs={"mode": "contains"},
    ),
    ParityCase(
        "contains_left_empty_query",
        interval_table([], [], [], gene=[]),
        interval_table([CHR], [15], [20], feature=["f1"]),
        (),
        how="left",
        engine_kwargs={"mode": "contains"},
    ),
    ParityCase(
        "contains_left_empty_annot",
        interval_table([CHR, CHR], [10, 100], [30, 200], gene=["g1", "g2"]),
        interval_table([], [], [], feature=[]),
        ((0, None), (1, None)),
        how="left",
        engine_kwargs={"mode": "contains"},
    ),
    ParityCase(
        "contains_both_empty",
        interval_table([], [], [], gene=[]),
        interval_table([], [], [], feature=[]),
        (),
        engine_kwargs={"mode": "contains"},
    ),
]

# ---------------------------------------------------------------------------
# Within (PLAN Task 6D) — SPEC 8.5.
#
# within(Q, A) means the QUERY interval is fully contained within the
# ANNOTATION interval:
#
#     a_start <= q_start AND a_end >= q_end
#
# Boundary equality counts: identical intervals and shared left/right
# boundaries all qualify. Query-contains-annotation is the ``contains``
# direction (SPEC 8.4) and does NOT qualify; partial overlaps and
# touching intervals do not qualify. within is the directional inverse
# of contains with respect to the query/annotation roles, and equality
# satisfies BOTH relations. within is deliberately NOT ``min_overlap``
# (SPEC 8.2 measures query coverage and is defined for overlap mode
# only): a query-fraction threshold can pass while within fails, and
# ``min_overlap`` is not applied in within mode. Strand composes by
# logical AND (SPEC 8.3): missing/unknown strand is not a wildcard. In
# left mode a query with zero containing annotations is emitted exactly
# once as unmatched.
#
# Expected rows below are derived from that definition, never from
# backend output.
# ---------------------------------------------------------------------------

WITHIN_CASES = [
    # 1. Strict within: annotation strictly larger on both sides.
    ParityCase(
        "within_strict",
        interval_table([CHR], [15], [20], gene=["g1"]),
        interval_table([CHR], [10], [30], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"mode": "within"},
    ),
    # 2. Exact equality: equality satisfies within.
    ParityCase(
        "within_exact_equality",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"mode": "within"},
    ),
    # 3. Shared left boundary, annotation extends farther right.
    ParityCase(
        "within_shared_left_boundary",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [10], [30], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"mode": "within"},
    ),
    # 4. Shared right boundary, annotation starts earlier.
    ParityCase(
        "within_shared_right_boundary",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [5], [20], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"mode": "within"},
    ),
    # 5. Query contains annotation: the ``contains`` direction, not within.
    ParityCase(
        "within_query_contains_annotation_no_match",
        interval_table([CHR], [10], [30], gene=["g1"]),
        interval_table([CHR], [15], [20], feature=["f1"]),
        (),
        engine_kwargs={"mode": "within"},
    ),
    # 6. Partial right overlap: overlaps, but the annotation does not
    # contain the query.
    ParityCase(
        "within_partial_right_overlap_no_match",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [15], [25], feature=["f1"]),
        (),
        engine_kwargs={"mode": "within"},
    ),
    # 7. Partial left overlap.
    ParityCase(
        "within_partial_left_overlap_no_match",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [5], [15], feature=["f1"]),
        (),
        engine_kwargs={"mode": "within"},
    ),
    # 8. Touching right: no positive overlap, so no containment.
    ParityCase(
        "within_touching_right_no_match",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [20], [30], feature=["f1"]),
        (),
        engine_kwargs={"mode": "within"},
    ),
    # 9. Touching left.
    ParityCase(
        "within_touching_left_no_match",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [0], [10], feature=["f1"]),
        (),
        engine_kwargs={"mode": "within"},
    ),
    # 10. Different chromosome: never a match.
    ParityCase(
        "within_different_chromosomes_no_match",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table(["chrB"], [0], [100], feature=["f1"]),
        (),
        engine_kwargs={"mode": "within"},
    ),
    # 11. Multiple containing annotations: all three qualify
    # (including the exact-equality one), in annotation input order.
    ParityCase(
        "within_multiple_containing",
        interval_table([CHR], [20], [30], gene=["g1"]),
        interval_table([CHR] * 3, [0, 10, 20], [100, 40, 30], feature=["a1", "a2", "a3"]),
        ((0, 0), (0, 1), (0, 2)),
        engine_kwargs={"mode": "within"},
    ),
    # 11b. Annotation LIST order, not coordinate order, defines hit order.
    ParityCase(
        "within_multiple_containing_input_order_not_coordinate",
        interval_table([CHR], [20], [30], gene=["g1"]),
        interval_table([CHR] * 3, [10, 0, 20], [40, 100, 30], feature=["a1", "a2", "a3"]),
        ((0, 0), (0, 1), (0, 2)),
        engine_kwargs={"mode": "within"},
    ),
    # 12. Mixed containing and partial/contained annotations: only the
    # genuinely containing annotation qualifies (annotation-inside-query
    # and partial overlap both fail).
    ParityCase(
        "within_mixed_containing_partial_and_contained",
        interval_table([CHR], [10], [30], gene=["g1"]),
        interval_table([CHR] * 3, [0, 15, 20], [100, 20, 40], feature=["a1", "a2", "a3"]),
        ((0, 0),),
        engine_kwargs={"mode": "within"},
    ),
    # 13. Duplicate queries: query identity and multiplicity preserved.
    ParityCase(
        "within_duplicate_queries_preserved",
        interval_table([CHR, CHR], [15, 15], [20, 20], gene=["q1", "q2"]),
        interval_table([CHR], [10], [30], feature=["f1"]),
        ((0, 0), (1, 0)),
        engine_kwargs={"mode": "within"},
    ),
    # 14. Duplicate annotations: no deduplication.
    ParityCase(
        "within_duplicate_annotations_preserved",
        interval_table([CHR], [15], [20], gene=["g1"]),
        interval_table([CHR, CHR], [10, 10], [30, 30], feature=["f1", "f2"]),
        ((0, 0), (0, 1)),
        engine_kwargs={"mode": "within"},
    ),
    # 14b. Duplicate queries x duplicate annotations: multiplicity 4.
    ParityCase(
        "within_duplicate_query_and_annotation",
        interval_table([CHR, CHR], [15, 15], [20, 20], gene=["q1", "q2"]),
        interval_table([CHR, CHR], [10, 10], [30, 30], feature=["a1", "a2"]),
        ((0, 0), (0, 1), (1, 0), (1, 1)),
        engine_kwargs={"mode": "within"},
    ),
    # 15. Left mode, no qualifying match: an ordinary overlap exists but
    # the annotation does not contain the query => exactly one unmatched
    # query row.
    ParityCase(
        "within_left_no_qualifying_match",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [5], [15], feature=["f1"]),
        ((0, None),),
        how="left",
        engine_kwargs={"mode": "within"},
    ),
    # 16. Left mode, mixed: emit only the containing match, NO unmatched
    # row (the annotation inside the query is a candidate but not a
    # within match).
    ParityCase(
        "within_left_mixed_only_containing",
        interval_table([CHR], [10], [30], gene=["g1"]),
        interval_table([CHR, CHR], [15, 0], [20, 100], feature=["f1", "f2"]),
        ((0, 1),),
        how="left",
        engine_kwargs={"mode": "within"},
    ),
    # Left mode across several queries: within / query-contains (the
    # annotation is inside the query) / within, in query input order.
    ParityCase(
        "within_left_mixed_queries",
        interval_table([CHR] * 3, [0, 20, 500], [5, 40, 520], gene=["q1", "q2", "q3"]),
        interval_table([CHR] * 3, [0, 25, 400], [10, 30, 600], feature=["a1", "a2", "a3"]),
        ((0, 0), (1, None), (2, 2)),
        how="left",
        engine_kwargs={"mode": "within"},
    ),
    # 17. within vs contains direction A: Q[10,20), A[0,100).
    # within qualifies; contains (the pair is the reverse direction) does
    # not. Both directions are asserted together in test_within_parity.
    ParityCase(
        "within_annotation_larger_match",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [0], [100], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"mode": "within"},
    ),
    # 18. within vs contains direction B: Q[0,100), A[10,20).
    # contains qualifies (SPEC 8.4) but within does not.
    ParityCase(
        "within_query_larger_no_match",
        interval_table([CHR], [0], [100], gene=["g1"]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        (),
        engine_kwargs={"mode": "within"},
    ),
    # 19. Equality satisfies BOTH relations (SPEC 8.4 + 8.5).
    ParityCase(
        "within_equality_satisfies_both",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [10], [20], feature=["f1"]),
        ((0, 0),),
        engine_kwargs={"mode": "within"},
    ),
    # 20. within is NOT min_overlap: Q[10,20), A[5,15) has query fraction
    # 0.5 (so min_overlap=0.5 qualifies) but the annotation does not
    # contain the query => no match. within is a positional containment
    # predicate, not a coverage threshold.
    ParityCase(
        "within_not_min_overlap_partial",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [5], [15], feature=["f1"]),
        (),
        engine_kwargs={"mode": "within", "min_overlap": 0.5},
    ),
    # 20b. Left counterpart of the same distinction: the query's only
    # candidate passes a 0.5 query-fraction threshold but is not a within
    # match => exactly one unmatched row. If within were implemented as
    # plain overlap + min_overlap (the pre-Task-6D polars-bio
    # placeholder), this query would wrongly appear matched.
    ParityCase(
        "within_not_min_overlap_partial_left",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR], [5], [15], feature=["f1"]),
        ((0, None),),
        how="left",
        engine_kwargs={"mode": "within", "min_overlap": 0.5},
    ),
    # 20c. min_overlap is NOT applied in within mode: the containing
    # annotation qualifies and the partial candidate (query fraction 0.5,
    # which would satisfy a wrongly applied 0.5 threshold) does not.
    ParityCase(
        "within_min_overlap_not_applied",
        interval_table([CHR], [10], [20], gene=["g1"]),
        interval_table([CHR, CHR], [0, 5], [100, 15], feature=["a1", "a2"]),
        ((0, 0),),
        engine_kwargs={"mode": "within", "min_overlap": 0.5},
    ),
    # 21-23. Strand composes with within by logical AND (SPEC 8.3).
    ParityCase(
        "within_strand_same_matches",
        interval_table([CHR], [15], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR], [10], [30], feature=["f1"], strand=["+"]),
        ((0, 0),),
        engine_kwargs={"mode": "within", "use_strand": True},
    ),
    ParityCase(
        "within_strand_same_negative_matches",
        interval_table([CHR], [15], [20], gene=["g1"], strand=["-"]),
        interval_table([CHR], [10], [30], feature=["f1"], strand=["-"]),
        ((0, 0),),
        engine_kwargs={"mode": "within", "use_strand": True},
    ),
    ParityCase(
        "within_strand_opposite_no_match",
        interval_table([CHR], [15], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR], [10], [30], feature=["f1"], strand=["-"]),
        (),
        engine_kwargs={"mode": "within", "use_strand": True},
    ),
    ParityCase(
        "within_strand_missing_no_match",
        interval_table([CHR], [15], [20], gene=["g1"], strand=[None]),
        interval_table([CHR], [10], [30], feature=["f1"], strand=["+"]),
        (),
        engine_kwargs={"mode": "within", "use_strand": True},
    ),
    ParityCase(
        "within_strand_both_missing_no_match",
        interval_table([CHR], [15], [20], gene=["g1"], strand=[None]),
        interval_table([CHR], [10], [30], feature=["f1"], strand=[None]),
        (),
        engine_kwargs={"mode": "within", "use_strand": True},
    ),
    ParityCase(
        "within_strand_missing_column_no_match",
        interval_table([CHR], [15], [20], gene=["g1"]),
        interval_table([CHR], [10], [30], feature=["f1"]),
        (),
        engine_kwargs={"mode": "within", "use_strand": True},
    ),
    ParityCase(
        "within_strand_false_ignores_strand",
        interval_table([CHR], [15], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR], [10], [30], feature=["f1"], strand=["-"]),
        ((0, 0),),
        engine_kwargs={"mode": "within"},
    ),
    # 21b. One query, two annotation strands: stranded within keeps only
    # the same-strand (containing) annotation.
    ParityCase(
        "within_strand_one_query_two_annotation_strands",
        interval_table([CHR], [15], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR, CHR], [10, 0], [30, 100], feature=["f1", "f2"], strand=["+", "-"]),
        ((0, 0),),
        engine_kwargs={"mode": "within", "use_strand": True},
    ),
    # 21c. Stranded left reconstruction: the geometric within candidate
    # fails the strand predicate => exactly one unmatched query row.
    ParityCase(
        "within_strand_left_unmatched",
        interval_table([CHR], [15], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR], [10], [30], feature=["f1"], strand=["-"]),
        ((0, None),),
        how="left",
        engine_kwargs={"mode": "within", "use_strand": True},
    ),
    # 21d. Touching + same strand: half-open semantics stay authoritative.
    ParityCase(
        "within_strand_touching_no_match",
        interval_table([CHR], [10], [20], gene=["g1"], strand=["+"]),
        interval_table([CHR], [20], [30], feature=["f1"], strand=["+"]),
        (),
        engine_kwargs={"mode": "within", "use_strand": True},
    ),
    # 24. Empty inputs (SPEC 7.2 / engine-contract section 6).
    ParityCase(
        "within_inner_empty_query",
        interval_table([], [], [], gene=[]),
        interval_table([CHR], [10], [30], feature=["f1"]),
        (),
        engine_kwargs={"mode": "within"},
    ),
    ParityCase(
        "within_inner_empty_annot",
        interval_table([CHR], [15], [20], gene=["g1"]),
        interval_table([], [], [], feature=[]),
        (),
        engine_kwargs={"mode": "within"},
    ),
    ParityCase(
        "within_left_empty_query",
        interval_table([], [], [], gene=[]),
        interval_table([CHR], [10], [30], feature=["f1"]),
        (),
        how="left",
        engine_kwargs={"mode": "within"},
    ),
    ParityCase(
        "within_left_empty_annot",
        interval_table([CHR, CHR], [15, 100], [20, 200], gene=["g1", "g2"]),
        interval_table([], [], [], feature=[]),
        ((0, None), (1, None)),
        how="left",
        engine_kwargs={"mode": "within"},
    ),
    ParityCase(
        "within_both_empty",
        interval_table([], [], [], gene=[]),
        interval_table([], [], [], feature=[]),
        (),
        engine_kwargs={"mode": "within"},
    ),
    # 26. Metadata preserved exactly on within matches, including missing
    # metadata values.
    ParityCase(
        "within_metadata_preserved",
        interval_table([CHR], [15], [20], gene=["g1"], score=[0.5], note=[None]),
        interval_table([CHR], [10], [30], feature=["f1"], label=["3.5"], flag=[True]),
        ((0, 0),),
        engine_kwargs={"mode": "within"},
    ),
]

# ---------------------------------------------------------------------------
# Differential (Bedtools vs Polars-Bio) cases — a deliberately small set of
# representative fixtures spanning the semantic surface.
# ---------------------------------------------------------------------------

DIFFERENTIAL_CASES = [
    OVERLAP_CASES[0],  # exact_interval_match
    OVERLAP_CASES[7],  # touching_boundaries_no_overlap
    OVERLAP_CASES[10],  # one_base_overlap
    OVERLAP_CASES[11],  # one_query_two_annotations
    OVERLAP_CASES[13],  # many_to_many
    OVERLAP_CASES[16],  # duplicate_query_and_annotation
    LEFT_CASES[2],  # left_mixed_matched_unmatched
    METADATA_CASES[0],  # metadata_colliding_names
]

# Task 6A: representative min_overlap fixtures for the direct
# engine-vs-engine layer (equal thresholds, asymmetry, filtering order,
# left reconstruction after filtering).
_MIN_OVERLAP_DIFFERENTIAL_NAMES = {
    "min_overlap_half_threshold_equal",
    "min_overlap_zero_touching_no_match",
    "min_overlap_annotation_larger_threshold_1",
    "min_overlap_not_reciprocal",
    "min_overlap_one_pass_one_fail",
    "min_overlap_multiple_qualifying_order",
    "min_overlap_no_aggregation_left",
    "min_overlap_left_mixed_qualifying",
}
DIFFERENTIAL_CASES += [
    c for c in MIN_OVERLAP_CASES if c.name in _MIN_OVERLAP_DIFFERENTIAL_NAMES
]

# Task 6B: representative strand fixtures for the direct
# engine-vs-engine layer (same/opposite/missing strands, mixed left
# reconstruction, multiplicity, missing strand column, and the
# strand + min_overlap composition).
_STRAND_DIFFERENTIAL_NAMES = {
    "strand_same_positive_matches_stranded",
    "strand_opposite_plus_minus_fails_stranded",
    "strand_opposite_minus_plus_fails_stranded",
    "strand_query_missing_fails_stranded",
    "strand_both_missing_fails_stranded",
    "strand_one_query_two_annotation_strands_stranded",
    "strand_duplicate_annotations_preserved",
    "strand_left_mismatch_only_unmatched",
    "strand_left_mixed_only_qualifying_emitted",
    "strand_touching_same_strand_no_match_stranded",
    "strand_and_min_overlap_both_pass",
    "strand_fail_min_overlap_pass_no_match",
    "strand_pass_min_overlap_fail_no_match",
    "strand_min_overlap_left_reconstruction",
    "strand_missing_column_query_no_match",
}
DIFFERENTIAL_CASES += [
    c for c in STRAND_CASES if c.name in _STRAND_DIFFERENTIAL_NAMES
]

# Task 6C: representative contains fixtures for the direct
# engine-vs-engine layer (directionality both ways, shared/equal
# boundaries, partial and touching non-matches, multiplicity/order,
# left reconstruction, the min_overlap exemption, strand composition,
# and empty inputs).
_CONTAINS_DIFFERENTIAL_NAMES = {
    "contains_strict",
    "contains_exact_equality",
    "contains_shared_left_boundary",
    "contains_shared_right_boundary",
    "contains_annotation_contains_query_no_match",
    "contains_partial_right_overlap_no_match",
    "contains_touching_right_no_match",
    "contains_multiple_contained_input_order_not_coordinate",
    "contains_mixed_contained_partial_and_container",
    "contains_duplicate_queries_preserved",
    "contains_duplicate_annotations_preserved",
    "contains_left_no_qualifying_match",
    "contains_left_mixed_only_contained",
    "contains_min_overlap_not_applied",
    "contains_annotation_larger_no_match",
    "contains_query_larger_match",
    "contains_strand_same_matches",
    "contains_strand_opposite_no_match",
    "contains_strand_missing_no_match",
    "contains_inner_empty_annot",
    "contains_left_empty_annot",
}
DIFFERENTIAL_CASES += [
    c for c in CONTAINS_CASES if c.name in _CONTAINS_DIFFERENTIAL_NAMES
]

# Task 6D: representative within fixtures for the direct engine-vs-engine
# layer (directionality both ways, shared/equal boundaries, partial and
# touching non-matches, multiplicity/order, left reconstruction, the
# min_overlap distinction, strand composition, and empty inputs).
_WITHIN_DIFFERENTIAL_NAMES = {
    "within_strict",
    "within_exact_equality",
    "within_shared_left_boundary",
    "within_shared_right_boundary",
    "within_query_contains_annotation_no_match",
    "within_partial_right_overlap_no_match",
    "within_touching_right_no_match",
    "within_multiple_containing_input_order_not_coordinate",
    "within_mixed_containing_partial_and_contained",
    "within_duplicate_queries_preserved",
    "within_duplicate_query_and_annotation",
    "within_left_no_qualifying_match",
    "within_left_mixed_only_containing",
    "within_left_mixed_queries",
    "within_annotation_larger_match",
    "within_query_larger_no_match",
    "within_not_min_overlap_partial",
    "within_min_overlap_not_applied",
    "within_strand_same_matches",
    "within_strand_opposite_no_match",
    "within_strand_missing_no_match",
    "within_inner_empty_annot",
    "within_left_empty_annot",
}
DIFFERENTIAL_CASES += [
    c for c in WITHIN_CASES if c.name in _WITHIN_DIFFERENTIAL_NAMES
]