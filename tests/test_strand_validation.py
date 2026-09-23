"""
Strand value validation (PLAN Task 6B) — SPEC 8.3.

The canonical strand contract admits exactly three states: ``"+"``,
``"-"``, and missing. ``validate_canonical_interval_table`` (invoked by
BOTH engines before any backend execution) rejects every other value.
These tests pin the engine-level behavior: malformed strand values are
explicit validation errors — they are never silently treated as
missing, never treated as a strand, and never forwarded to a backend.
"""

from __future__ import annotations

import pandas as pd
import polars_bio as pb
import pybedtools
import pytest

from streamlit_app.core import BedtoolsEngine, PolarsBioEngine
from streamlit_app.core.schema import InvalidIntervalError, validate_canonical_interval_table

ENGINES = [
    pytest.param(BedtoolsEngine, id="bedtools"),
    pytest.param(PolarsBioEngine, id="polars-bio"),
]

INVALID_STRANDS = [
    pytest.param("?", id="question_mark"),
    pytest.param("*", id="star"),
    pytest.param("plus", id="word_plus"),
    pytest.param("1", id="one"),
    pytest.param("", id="empty_string"),
]


def _query(strand_value):
    return pd.DataFrame(
        {
            "chr": ["chrA"],
            "start": [10],
            "end": [20],
            "strand": [strand_value],
            "gene": ["g1"],
        }
    )


def _annot():
    return pd.DataFrame(
        {
            "chr": ["chrA"],
            "start": [15],
            "end": [25],
            "strand": ["+"],
            "feature": ["f1"],
        }
    )


@pytest.mark.parametrize("engine_cls", ENGINES)
@pytest.mark.parametrize("value", INVALID_STRANDS)
def test_invalid_canonical_strand_rejected(engine_cls, value):
    """Malformed strand values raise before any backend execution."""
    engine = engine_cls(use_strand=True)
    with pytest.raises(InvalidIntervalError, match="strand"):
        engine.intersect(_query(value), _annot())


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_invalid_canonical_strand_does_not_invoke_backend(engine_cls, monkeypatch):
    """Validation happens BEFORE the backend call on both sides."""
    calls = []
    monkeypatch.setattr(
        pybedtools.BedTool,
        "intersect",
        lambda self, *args, **kwargs: calls.append("bedtools"),
    )
    monkeypatch.setattr(
        pybedtools.BedTool,
        "closest",
        lambda self, *args, **kwargs: calls.append("bedtools"),
    )
    monkeypatch.setattr(
        pb, "overlap", lambda *args, **kwargs: calls.append("polars-bio")
    )
    monkeypatch.setattr(
        pb, "nearest", lambda *args, **kwargs: calls.append("polars-bio")
    )
    for value in ("?", "*", "plus", "1", ""):
        with pytest.raises(InvalidIntervalError):
            engine_cls().intersect(_query(value), _annot())
    assert calls == []


def test_valid_canonical_strands_and_missing_accepted():
    """``"+"``, ``"-"``, and missing are the only accepted states."""
    for value in ("+", "-", None):
        validate_canonical_interval_table(_query(value))  # must not raise