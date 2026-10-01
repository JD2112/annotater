"""
Verify every declared fact in tests/fixtures/semantic_examples.json against
the independent oracle (tests/oracle/reference.py).

The docs renderer only *displays* these declared values; this module is
what makes them true. It imports nothing from ``streamlit_app``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from tests.oracle import reference as ref

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "semantic_examples.json"
EXAMPLES = json.loads(FIXTURE.read_text())["examples"]
BY_NAME = {ex["name"]: ex for ex in EXAMPLES}

REQUIRED_NAMES = {
    "true_overlap", "touching_intervals", "one_base_gap", "contains_example",
    "within_example", "min_overlap_on_threshold", "strand_match",
    "strand_missing", "closest_tie", "closest_overlapping", "one_base_overlap", "closest_large_gap",
}


def _pairs(ex, **kwargs):
    return ref.reference_pairs([ex["query"]], ex["annotations"], **kwargs)


def _single(ex):
    q, a = ex["query"], ex["annotations"][0]
    return q["start"], q["end"], a["start"], a["end"]


def test_fixture_covers_required_examples():
    assert REQUIRED_NAMES <= set(BY_NAME)


@pytest.mark.parametrize("ex", EXAMPLES, ids=lambda e: e["name"])
class TestDeclaredFacts:
    def test_overlap(self, ex):
        exp = ex["expected"]
        if "overlap" in exp:
            assert bool(_pairs(ex, mode="overlap")) is exp["overlap"]
        if "overlap_length" in exp:
            # The oracle returns a negative number for disjoint intervals;
            # the documented fact is the number of shared bases (>= 0).
            assert max(0, ref.overlap_length(*_single(ex))) == exp["overlap_length"]
        if "query_length" in exp:
            q = ex["query"]
            assert q["end"] - q["start"] == exp["query_length"]
        if "overlap_fraction" in exp:
            length = ref.overlap_length(*_single(ex))
            assert math.isclose(
                length / (ex["query"]["end"] - ex["query"]["start"]),
                exp["overlap_fraction"], rel_tol=0, abs_tol=0)

    def test_containment(self, ex):
        exp = ex["expected"]
        if "contains" in exp:
            assert bool(_pairs(ex, mode="contains")) is exp["contains"]
        if "within" in exp:
            assert bool(_pairs(ex, mode="within")) is exp["within"]

    def test_min_overlap(self, ex):
        if "min_overlap_pass" not in ex["expected"]:
            return
        rows = _pairs(ex, mode="overlap", min_overlap=ex["min_overlap"])
        assert bool(rows) is ex["expected"]["min_overlap_pass"]

    def test_strand(self, ex):
        if "stranded_match" not in ex["expected"]:
            return
        rows = _pairs(ex, mode="overlap", use_strand=ex["use_strand"])
        assert bool(rows) is ex["expected"]["stranded_match"]
        a = ex["annotations"][0]
        assert ref.strands_match(ex["query"].get("strand"),
                                 a.get("strand")) is ex["expected"]["stranded_match"]

    def test_closest(self, ex):
        exp = ex["expected"]
        if "closest_distance" not in exp:
            return
        rows = _pairs(ex, mode="closest")
        assert rows, "closest always returns same-chromosome candidates"
        assert {d for _, _, d in rows} == {exp["closest_distance"]}
        if "closest_ties" in exp:
            # all minimum-distance ties retained, in annotation input order
            ids = [ex["annotations"][ai]["id"] for _, ai, _ in rows]
            assert ids == exp["closest_ties"]
        else:
            assert len(rows) == 1


def test_touching_is_not_overlap_but_has_distance_zero():
    ex = BY_NAME["touching_intervals"]
    assert _pairs(ex, mode="overlap") == []
    assert _pairs(ex, mode="closest")[0][2] == 0


def test_contains_and_within_are_directional():
    assert _pairs(BY_NAME["contains_example"], mode="within") == []
    assert _pairs(BY_NAME["within_example"], mode="contains") == []


def test_min_overlap_threshold_is_inclusive_and_exact():
    ex = BY_NAME["min_overlap_on_threshold"]
    t = ex["min_overlap"]
    assert _pairs(ex, mode="overlap", min_overlap=t)
    assert _pairs(ex, mode="overlap", min_overlap=math.nextafter(t, 1)) == []


def test_missing_strand_is_not_a_wildcard():
    ex = BY_NAME["strand_missing"]
    assert _pairs(ex, mode="overlap")  # overlaps when strand is ignored
    assert _pairs(ex, mode="overlap", use_strand=True) == []
    assert ref.strands_match("+", None) is False
    assert ref.strands_match(None, None) is False


def test_closest_tie_excludes_farther_annotation():
    ex = BY_NAME["closest_tie"]
    rows = _pairs(ex, mode="closest")
    assert [ai for _, ai, _ in rows] == [0, 1]
    far = ref.gap_distance(ex["query"]["start"], ex["query"]["end"],
                           ex["annotations"][2]["start"],
                           ex["annotations"][2]["end"])
    assert far > ex["expected"]["closest_distance"]
