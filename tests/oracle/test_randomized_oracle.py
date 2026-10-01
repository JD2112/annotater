"""
Deterministic randomized differential tests against the independent oracle.

For every fixed seed in ``SEEDS`` a tiny random fixture is generated
(``tests/oracle/harness.py::make_fixture``) and, for each operation
configuration, BOTH backends' canonical results are compared row by row
with the brute-force oracle AND with each other. Failures report the seed,
the configuration, the backend and the complete fixture so they can be
reproduced with ``make_fixture(seed)``.
"""

from __future__ import annotations

import pytest

from .harness import check_fixture, make_fixture
from .reference import reference_pairs

SEEDS = tuple(range(7000, 7010))

MODE_CONFIGS = (
    [("overlap", None)]
    + [("overlap", threshold) for threshold in (0.25, 0.5, 0.75, 1.0)]
    + [("contains", None), ("within", None), ("closest", None)]
)


def _id(param):
    mode, threshold = param
    return mode if threshold is None else f"{mode}-min{threshold}"


@pytest.mark.parametrize("use_strand", [False, True], ids=["strand-off", "strand-on"])
@pytest.mark.parametrize("how", ["inner", "left"])
@pytest.mark.parametrize("mode_cfg", MODE_CONFIGS, ids=_id)
def test_backends_match_oracle_on_seeded_fixtures(mode_cfg, how, use_strand):
    mode, threshold = mode_cfg
    config = {"mode": mode, "how": how, "use_strand": use_strand,
              "min_overlap": threshold}
    problems = []
    for seed in SEEDS:
        queries, annotations = make_fixture(seed)
        problems += check_fixture(queries, annotations, config, tag=f"seed={seed}")
    assert not problems, (
        f"{len(problems)} oracle/backend discrepancies "
        f"(reproduce with make_fixture(seed)):\n\n" + "\n\n".join(problems[:3])
    )


# --------------------------------------------------------------------------
# The random corpus must actually exercise the dangerous situations;
# otherwise agreement with the oracle would prove little.
# --------------------------------------------------------------------------

def _corpus_pairs(**kwargs):
    for seed in SEEDS:
        queries, annotations = make_fixture(seed)
        yield queries, annotations, reference_pairs(queries, annotations, **kwargs)


def test_corpus_exercises_matches_unmatched_and_duplicates():
    matched = unmatched = dup_queries = dup_annots = no_annot_chr = 0
    for queries, annotations, pairs in _corpus_pairs(how="left"):
        matched += sum(1 for _, ai, _ in pairs if ai is not None)
        unmatched += sum(1 for _, ai, _ in pairs if ai is None)
        key = lambda r: (r["chr"], r["start"], r["end"])
        dup_queries += len(queries) - len({key(r) for r in queries})
        dup_annots += len(annotations) - len({key(r) for r in annotations})
        annot_chrs = {r["chr"] for r in annotations}
        no_annot_chr += sum(1 for r in queries if r["chr"] not in annot_chrs)
    assert matched > 30 and unmatched > 10
    assert dup_queries > 0 and dup_annots > 0 and no_annot_chr > 0


def test_corpus_exercises_closest_ties_gaps_and_touching():
    ties = zero_touch = positive_gap = 0
    for queries, annotations, pairs in _corpus_pairs(how="inner", mode="closest"):
        per_query = {}
        for qi, ai, d in pairs:
            per_query.setdefault(qi, []).append((ai, d))
            if d is not None and d > 0:
                positive_gap += 1
            q, a = queries[qi], annotations[ai]
            if q["end"] == a["start"] or a["end"] == q["start"]:
                zero_touch += 1
        ties += sum(1 for rows in per_query.values() if len(rows) > 1)
    assert ties > 5 and zero_touch > 0 and positive_gap > 0


def test_corpus_exercises_strand_variants():
    values = set()
    for queries, annotations, _ in _corpus_pairs(how="inner"):
        for row in queries + annotations:
            values.add(row.get("strand", "<absent>"))
    assert {"+", "-", None, "<absent>"} <= values


def test_corpus_exercises_min_overlap_thresholds():
    """Different thresholds must produce different oracle answers somewhere."""
    seen = set()
    for threshold in (None, 0.25, 0.5, 0.75, 1.0):
        total = 0
        for queries, annotations, pairs in _corpus_pairs(
                how="inner", mode="overlap", min_overlap=threshold):
            total += len(pairs)
        seen.add(total)
    assert len(seen) >= 4


def test_fixtures_are_deterministic():
    assert make_fixture(SEEDS[0]) == make_fixture(SEEDS[0])
    assert make_fixture(SEEDS[0]) != make_fixture(SEEDS[1])
