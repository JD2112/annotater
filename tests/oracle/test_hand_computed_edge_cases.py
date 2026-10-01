"""
Hand-computed dangerous-boundary cases (Task F, section 9).

Every expected row below was computed BY HAND from the contract formulas
(shown in each case's comment) — not from the oracle and not from any
backend. Each case is asserted three ways:

1. the independent oracle reproduces the hand-computed rows;
2. Bedtools reproduces them (full canonical rows);
3. Polars-Bio reproduces them (full canonical rows).

Expected rows are ``(query_index, annotation_index_or_None, distance)``;
``distance`` is ``None`` outside closest mode / for unmatched rows.
Intervals are canonical 0-based half-open; ``name``/``feature`` metadata
identify rows. All rows are on ``chr1`` unless stated otherwise.
"""

from __future__ import annotations

import pytest

from .harness import ENGINES, diff_rows, oracle_rows_for, result_rows, run_canonical
from .reference import reference_pairs, reference_rows


def Q(*spans, chroms=None, strands=None):
    rows = []
    for i, (s, e) in enumerate(spans):
        row = {"chr": (chroms or ["chr1"] * len(spans))[i], "start": s, "end": e}
        if strands is not None:
            row["strand"] = strands[i]
        row["name"] = f"q{i}"
        rows.append(row)
    return rows


def A(*spans, chroms=None, strands=None):
    rows = []
    for i, (s, e) in enumerate(spans):
        row = {"chr": (chroms or ["chr1"] * len(spans))[i], "start": s, "end": e}
        if strands is not None:
            row["strand"] = strands[i]
        row["feature"] = f"a{i}"
        rows.append(row)
    return rows


def case(name, queries, annotations, expected, *, how="inner", mode="overlap",
         use_strand=False, min_overlap=None):
    config = {"mode": mode, "how": how, "use_strand": use_strand,
              "min_overlap": min_overlap}
    return pytest.param(queries, annotations, config, expected, id=name)


CASES = [
    # 1. identical intervals: max(10,10)=10 < min(20,20)=20 -> overlap
    case("identical_intervals", Q((10, 20)), A((10, 20)), [(0, 0, None)]),
    # 2. touching: max(10,20)=20 < min(20,30)=20 is false -> none
    case("touching_is_not_overlap", Q((10, 20)), A((20, 30)), []),
    case("touching_left_side_is_not_overlap", Q((20, 30)), A((10, 20)), []),
    # 3. one-base gap: [10,20) vs [21,30) -> max=21 < min=20 false
    case("one_base_gap_is_not_overlap", Q((10, 20)), A((21, 30)), []),
    # 4. one-base query inside / adjacent: [10,11) vs [10,20): 10<11 overlap
    case("one_base_query_overlaps", Q((10, 11)), A((10, 20)), [(0, 0, None)]),
    case("one_base_query_adjacent_misses", Q((10, 11)), A((11, 20)), []),
    # 5. query contains annotation exactly at both boundaries / shared ends
    case("contains_exact_boundaries", Q((10, 20)), A((10, 20), (10, 15), (15, 20), (9, 15), (15, 21)),
         [(0, 0, None), (0, 1, None), (0, 2, None)], mode="contains"),
    # 6. annotation contains query exactly at boundaries (within)
    case("within_exact_boundaries", Q((10, 20)), A((10, 20), (5, 20), (10, 25), (11, 25), (5, 19)),
         [(0, 0, None), (0, 1, None), (0, 2, None)], mode="within"),
    # contains/within are directional: q[10,30) vs a[15,20): contains yes, within no
    case("contains_is_directional", Q((10, 30)), A((15, 20)), [(0, 0, None)], mode="contains"),
    case("within_rejects_contains_direction", Q((10, 30)), A((15, 20)), [], mode="within"),
    case("contains_rejects_within_direction", Q((15, 20)), A((10, 30)), [], mode="contains"),
    # 7. duplicate annotation rows: each produces its own row, input order
    case("duplicate_annotations", Q((10, 20)), A((12, 15), (12, 15)),
         [(0, 0, None), (0, 1, None)]),
    # 8. duplicate query rows keep their own identity
    case("duplicate_queries", Q((10, 20), (10, 20)), A((12, 15)),
         [(0, 0, None), (1, 0, None)]),
    # query order, then annotation order (not genomic order)
    case("row_order_is_input_order", Q((50, 60), (0, 10)), A((55, 58), (5, 8), (52, 54)),
         [(0, 0, None), (0, 2, None), (1, 1, None)]),
    # 9. two closest ties: q[10,20); a0[25,30) gap 5; a1[0,5) gap 5 -> both, input order
    case("closest_two_ties", Q((10, 20)), A((25, 30), (0, 5)),
         [(0, 0, 5), (0, 1, 5)], mode="closest"),
    # 10. three closest ties incl. a duplicate-valued annotation:
    #     gaps: a0[22,30)=2, a1[0,8)=2, a2[22,30)=2, a3[40,50)=20
    case("closest_three_ties", Q((10, 20)), A((22, 30), (0, 8), (22, 30), (40, 50)),
         [(0, 0, 2), (0, 1, 2), (0, 2, 2)], mode="closest"),
    # closest distances: overlap 0, touching 0, one-base gap 1
    case("closest_overlap_is_zero", Q((10, 20)), A((15, 25), (30, 40)),
         [(0, 0, 0)], mode="closest"),
    case("closest_touching_is_zero", Q((10, 20)), A((20, 25)),
         [(0, 0, 0)], mode="closest"),
    case("closest_one_base_gap_is_one", Q((10, 20)), A((21, 25)),
         [(0, 0, 1)], mode="closest"),
    case("closest_gap_before_query", Q((100, 110)), A((90, 95)),
         [(0, 0, 5)], mode="closest"),
    # closest: overlap (0) beats nearer-by-start but separated annotation
    case("closest_prefers_overlap_over_gap", Q((10, 20)), A((25, 30), (19, 21)),
         [(0, 1, 0)], mode="closest"),
    # closest ignores min_overlap / contains / within predicates
    case("closest_ignores_min_overlap", Q((10, 20)), A((19, 40)),
         [(0, 0, 0)], mode="closest", min_overlap=1.0),
    # 11. missing strand is never a wildcard (including unknown vs unknown)
    case("strand_missing_query_blocks_match", Q((10, 20), strands=[None]), A((12, 15), strands=["+"]),
         [], use_strand=True),
    case("strand_missing_annotation_blocks_match", Q((10, 20), strands=["+"]), A((12, 15), strands=[None]),
         [], use_strand=True),
    case("strand_unknown_vs_unknown_blocks_match", Q((10, 20), strands=[None]), A((12, 15), strands=[None]),
         [], use_strand=True),
    case("strand_ignored_when_off", Q((10, 20), strands=[None]), A((12, 15), strands=["+"]),
         [(0, 0, None)], use_strand=False),
    # 12. opposite strand blocks; same strand passes
    case("strand_opposite_blocks", Q((10, 20), strands=["+"]), A((12, 15), strands=["-"]),
         [], use_strand=True),
    case("strand_same_passes", Q((10, 20), strands=["-"]), A((12, 15), strands=["-"]),
         [(0, 0, None)], use_strand=True),
    # strand applies BEFORE nearest: nearer opposite-strand annotation must not suppress the farther eligible one
    case("closest_strand_before_nearest", Q((10, 20), strands=["+"]),
         A((21, 25), (40, 50), strands=["-", "+"]),
         [(0, 1, 20)], mode="closest", use_strand=True),
    case("closest_strand_none_eligible_inner", Q((10, 20), strands=["+"]),
         A((21, 25), strands=["-"]), [], mode="closest", use_strand=True),
    # 13. exact min_overlap threshold: q[10,20) len 10; a[10,15) overlap 5 -> 0.5 >= 0.5
    case("min_overlap_exact_threshold", Q((10, 20)), A((10, 15)),
         [(0, 0, None)], min_overlap=0.5),
    # 14. just below: a[10,14) overlap 4 -> 0.4 < 0.5
    case("min_overlap_just_below_threshold", Q((10, 20)), A((10, 14)),
         [], min_overlap=0.5),
    # denominator is QUERY length: q[10,20) vs big a[0,100): overlap 10 -> 1.0 (annotation-relative would be 0.1)
    case("min_overlap_is_query_relative", Q((10, 20)), A((0, 100)),
         [(0, 0, None)], min_overlap=1.0),
    # q[0,100) vs a[10,20): overlap 10/100 = 0.1 < 0.5 (annotation-relative would be 1.0)
    case("min_overlap_not_annotation_relative", Q((0, 100)), A((10, 20)),
         [], min_overlap=0.5),
    # no aggregation: q[0,10) vs a0[0,3) + a1[5,8): each 0.3 < 0.5 although total 0.6
    case("min_overlap_not_aggregated", Q((0, 10)), A((0, 3), (5, 8)),
         [], min_overlap=0.5),
    # threshold 0 still needs positive overlap (touching stays unmatched)
    case("min_overlap_zero_still_needs_overlap", Q((10, 20)), A((20, 30), (19, 30)),
         [(0, 1, None)], min_overlap=0.0),
    # min_overlap only applies to overlap mode (contains ignores it)
    case("contains_ignores_min_overlap", Q((10, 20)), A((12, 13)),
         [(0, 0, None)], mode="contains", min_overlap=1.0),
    # 15. chromosome with no eligible annotation
    case("no_annotation_on_chromosome_inner", Q((10, 20), chroms=["chr3"]), A((10, 20)), []),
    case("no_annotation_on_chromosome_left", Q((10, 20), chroms=["chr3"]), A((10, 20)),
         [(0, None, None)], how="left"),
    case("closest_never_crosses_chromosomes_inner", Q((10, 20), chroms=["chr3"]), A((10, 20)),
         [], mode="closest"),
    case("closest_never_crosses_chromosomes_left", Q((10, 20), chroms=["chr3"]), A((10, 20)),
         [(0, None, None)], mode="closest", how="left"),
    # left mode: unmatched appears once at its own position; matches follow inner multiplicity
    case("left_mixed_matched_and_unmatched", Q((10, 20), (100, 110), (12, 14)), A((11, 13), (12, 30)),
         [(0, 0, None), (0, 1, None), (1, None, None), (2, 0, None), (2, 1, None)], how="left"),
    case("left_all_predicates_fail_gives_one_unmatched_row", Q((10, 20)), A((12, 13), (18, 30)),
         [(0, None, None)], how="left", min_overlap=0.5),
    case("left_strand_fail_gives_one_unmatched_row", Q((10, 20), strands=["+"]),
         A((12, 15), (13, 16), strands=["-", "-"]),
         [(0, None, None)], how="left", use_strand=True),
    case("left_closest_mixed", Q((10, 20), (500, 510)), A((25, 30), strands=None),
         [(0, 0, 5), (1, 0, 470)], how="left", mode="closest"),
    case("left_closest_unmatched_has_null_distance", Q((10, 20), strands=["+"]),
         A((25, 30), strands=["-"]), [(0, None, None)], how="left", mode="closest",
         use_strand=True),
]


@pytest.mark.parametrize("queries,annotations,config,expected", CASES)
def test_oracle_reproduces_hand_computed_rows(queries, annotations, config, expected):
    pairs = reference_pairs(
        queries, annotations, how=config["how"], mode=config["mode"],
        use_strand=config["use_strand"], min_overlap=config["min_overlap"])
    assert pairs == expected


@pytest.mark.parametrize("backend", sorted(ENGINES))
@pytest.mark.parametrize("queries,annotations,config,expected", CASES)
def test_backend_reproduces_hand_computed_rows(
        backend, queries, annotations, config, expected):
    wanted = reference_rows(queries, annotations, expected,
                            closest=config["mode"] == "closest")
    actual = result_rows(run_canonical(ENGINES[backend], queries, annotations, config))
    difference = diff_rows(wanted, actual)
    assert difference is None, (
        f"{backend}: {difference}\n  queries={queries}\n  annotations={annotations}"
        f"\n  config={config}")
