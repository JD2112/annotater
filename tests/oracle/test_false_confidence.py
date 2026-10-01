"""
False-confidence guard (Task F, section 12).

Shows that the oracle comparison can actually FAIL when semantics are
wrong. Production code is never mutated: a deliberately wrong formula is
swapped into the TEST-ONLY oracle module (restored automatically by
``monkeypatch``) and the same comparison used by the real tests is run
against the real, correct backends. Each wrong formula must be caught by
the hand-computed edge cases AND by the seeded random corpus.
"""

from __future__ import annotations

import pytest

from . import reference
from .harness import ENGINES, check_fixture, make_fixture
from .test_hand_computed_edge_cases import CASES
from .test_randomized_oracle import SEEDS


def _mutant_touching_counts_as_overlap(monkeypatch):
    monkeypatch.setattr(
        reference, "overlaps",
        lambda q_start, q_end, a_start, a_end:
            reference.overlap_length(q_start, q_end, a_start, a_end) >= 0)


def _mutant_one_base_gap_is_distance_zero(monkeypatch):
    monkeypatch.setattr(
        reference, "gap_distance",
        lambda q_start, q_end, a_start, a_end:
            max(0, a_start - q_end - 1, q_start - a_end - 1))


def _mutant_min_overlap_uses_annotation_length(monkeypatch):
    def wrong(q_start, q_end, a_start, a_end, threshold):
        length = reference.overlap_length(q_start, q_end, a_start, a_end)
        return length > 0 and length / (a_end - a_start) >= threshold
    monkeypatch.setattr(reference, "meets_min_overlap", wrong)


def _mutant_missing_strand_is_wildcard(monkeypatch):
    def wrong(q_strand, a_strand):
        if q_strand not in ("+", "-") or a_strand not in ("+", "-"):
            return True
        return q_strand == a_strand
    monkeypatch.setattr(reference, "strands_match", wrong)


def _mutant_contains_direction_swapped(monkeypatch):
    monkeypatch.setattr(
        reference, "query_contains_annotation",
        lambda q_start, q_end, a_start, a_end:
            a_start <= q_start and a_end >= q_end)


def _mutant_contains_requires_strict_inequality(monkeypatch):
    monkeypatch.setattr(
        reference, "query_contains_annotation",
        lambda q_start, q_end, a_start, a_end:
            q_start < a_start and q_end > a_end)


MUTANTS = [
    _mutant_touching_counts_as_overlap,
    _mutant_one_base_gap_is_distance_zero,
    _mutant_min_overlap_uses_annotation_length,
    _mutant_missing_strand_is_wildcard,
    _mutant_contains_direction_swapped,
    _mutant_contains_requires_strict_inequality,
]

# One correct backend is enough to show the comparison can fail (and keeps
# this guard fast); the real tests above compare both backends.
GUARD_ENGINES = {"polars-bio": ENGINES["polars-bio"]}

RANDOM_CONFIGS = [
    {"mode": "overlap", "how": "left", "use_strand": False, "min_overlap": None},
    {"mode": "overlap", "how": "inner", "use_strand": True, "min_overlap": 0.5},
    {"mode": "contains", "how": "inner", "use_strand": False, "min_overlap": None},
    {"mode": "closest", "how": "left", "use_strand": False, "min_overlap": None},
]


@pytest.mark.parametrize("mutant", MUTANTS, ids=lambda m: m.__name__[len("_mutant_"):])
def test_wrong_semantics_is_caught_by_hand_cases(mutant, monkeypatch):
    mutant(monkeypatch)
    caught = []
    for param in CASES:
        queries, annotations, config, _expected = param.values
        caught += check_fixture(queries, annotations, config, tag=param.id,
                                engines=GUARD_ENGINES)
        if caught:
            break
    assert caught, f"{mutant.__name__} went undetected by the hand-computed cases"


@pytest.mark.parametrize("mutant", MUTANTS, ids=lambda m: m.__name__[len("_mutant_"):])
def test_wrong_semantics_is_caught_by_random_corpus(mutant, monkeypatch):
    mutant(monkeypatch)
    caught = []
    for config in RANDOM_CONFIGS:
        for seed in SEEDS:
            queries, annotations = make_fixture(seed)
            caught += check_fixture(queries, annotations, config,
                                    tag=f"seed={seed}", engines=GUARD_ENGINES)
            if caught:
                break
        if caught:
            break
    assert caught, f"{mutant.__name__} went undetected by the random corpus"
