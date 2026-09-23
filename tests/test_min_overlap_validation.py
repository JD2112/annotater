"""
min_overlap parameter validation (PLAN Task 6A) — SPEC 8.2.

The threshold is a construction-time contract of the shared
``AnnotationEngine`` base, so BOTH backends validate identically and
invalid values are rejected before ANY backend execution (never clamped,
never forwarded to a backend-native option).

Documented choices (Task 6A):

- ``None`` means "no fractional threshold" (ordinary positive overlap);
- ``0`` (int) is a valid no-op threshold, equivalent to ``0.0``;
- integer ``0``/``1`` are acceptable numeric equivalents of the float
  values in ``[0, 1]`` (normalized to ``float``);
- booleans are NOT silently accepted as numeric fractions;
- non-numeric types, NaN, infinities, and out-of-range values raise
  ``ValueError`` (the same exception type the engine public API already
  uses for invalid parameters, e.g. an unknown ``mode``).
"""

from __future__ import annotations

import polars_bio as pb
import pybedtools
import pytest

from streamlit_app.core import BedtoolsEngine, PolarsBioEngine

ENGINES = [
    pytest.param(BedtoolsEngine, id="bedtools"),
    pytest.param(PolarsBioEngine, id="polars-bio"),
]

# Raw value lists (pytest.param ids are display-only sugar over these).
_RAW_INVALID = [
    -0.01, -1, 1.01, 2, float("nan"), float("inf"), float("-inf"),
    True, False, "0.5",
]
_RAW_VALID = [None, 0, 0.0, 0.5, 1, 1.0]

INVALID_VALUES = [
    pytest.param(-0.01, id="negative"),
    pytest.param(-1, id="int_negative"),
    pytest.param(1.01, id="above_one"),
    pytest.param(2, id="int_above_one"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="plus_inf"),
    pytest.param(float("-inf"), id="minus_inf"),
    pytest.param(True, id="bool_true"),
    pytest.param(False, id="bool_false"),
    pytest.param("0.5", id="string"),
]

VALID_VALUES = [
    pytest.param(None, id="none"),
    pytest.param(0, id="int_0"),
    pytest.param(0.0, id="float_0"),
    pytest.param(0.5, id="float_0_5"),
    pytest.param(1, id="int_1"),
    pytest.param(1.0, id="float_1"),
]


@pytest.mark.parametrize("engine_cls", ENGINES)
@pytest.mark.parametrize("value", INVALID_VALUES)
def test_invalid_min_overlap_raises_value_error(engine_cls, value):
    """Out-of-domain / non-numeric / boolean thresholds fail explicitly."""
    with pytest.raises(ValueError, match="min_overlap"):
        engine_cls(min_overlap=value)


@pytest.mark.parametrize("engine_cls", ENGINES)
@pytest.mark.parametrize("value", VALID_VALUES)
def test_valid_min_overlap_accepted(engine_cls, value):
    """``None`` and every numeric value in [0, 1] (int or float) are valid."""
    engine = engine_cls(min_overlap=value)
    if value is None:
        assert engine.min_overlap is None
    else:
        # numeric values are normalized to float (int 0/1 included)
        assert engine.min_overlap == pytest.approx(float(value))
        assert isinstance(engine.min_overlap, float)


@pytest.mark.parametrize("engine_cls", ENGINES)
def test_invalid_min_overlap_does_not_invoke_backend(engine_cls, monkeypatch):
    """Invalid thresholds are rejected before either backend can run."""
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
    for value in (-0.01, 1.01, float("nan"), float("inf"), float("-inf"), True, False):
        with pytest.raises(ValueError, match="min_overlap"):
            engine_cls(min_overlap=value)
    assert calls == []


def test_validation_is_shared_between_engines():
    """Both engines accept and reject exactly the same values (one contract)."""
    for value in _RAW_INVALID + _RAW_VALID:
        bedtools_ok = True
        polars_ok = True
        try:
            BedtoolsEngine(min_overlap=value)
        except ValueError:
            bedtools_ok = False
        try:
            PolarsBioEngine(min_overlap=value)
        except ValueError:
            polars_ok = False
        assert bedtools_ok == polars_ok, f"engines disagree on {value!r}"