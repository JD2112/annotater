"""
Error / failure-behavior contract (PLAN Task 3) — SPEC 9.2.

A backend failure MUST propagate as an explicit error: "swallowing
backend exceptions and converting them into a scientifically plausible
empty result is forbidden". Equally important, a GENUINELY empty input
may produce a genuinely empty result (see the empty-input cases in
test_left_parity.py) — the distinction is between *valid empty input*
and *failure of the backend call*.

Deviations captured here:

- ``test_polars_overlap_backend_failure_propagates`` — PolarsBioEngine
  catches all ``pb.overlap`` exceptions and returns empty (xfail).
- ``test_polars_nearest_backend_failure_propagates`` — same for
  ``pb.nearest`` (xfail).
- ``test_bedtools_result_parsing_failure_propagates`` — DISCOVERED in
  Task 3: BedtoolsEngine._bedtools_to_df catches all ``to_dataframe``
  exceptions and returns an empty DataFrame (xfail).
"""

from __future__ import annotations

import pandas as pd
import pytest

from streamlit_app.core import BedtoolsEngine, PolarsBioEngine

from .comparator import interval_table

CHR = "chrA"


def _query():
    return interval_table([CHR], [10], [20], gene=["g1"])


def _annot():
    return interval_table([CHR], [15], [25], feature=["f1"])


@pytest.mark.parametrize(
    "engine_cls",
    [
        pytest.param(BedtoolsEngine, id="bedtools"),
        pytest.param(PolarsBioEngine, id="polars-bio"),
    ],
)
def test_unknown_mode_raises_explicit_error(engine_cls):
    """'mode' is a construction-time contract; unknown values must fail explicitly."""
    engine = engine_cls(mode="bogus-mode")
    with pytest.raises(ValueError):
        engine.intersect(_query(), _annot(), how="inner")


def test_bedtools_backend_failure_propagates(monkeypatch):
    """A pybedtools intersect failure must surface as an exception, not an empty frame."""
    import pybedtools

    def _boom(self, other, *args, **kwargs):
        raise RuntimeError("simulated bedtools backend failure")

    monkeypatch.setattr(pybedtools.BedTool, "intersect", _boom)
    with pytest.raises(RuntimeError, match="simulated bedtools backend failure"):
        BedtoolsEngine().intersect(_query(), _annot(), how="inner")


def test_malformed_input_raises_instead_of_empty():
    """Inputs missing required columns must fail explicitly for BOTH engines."""
    bad_query = pd.DataFrame({"start": [10], "end": [20]})  # no 'chr'
    for engine_cls in (BedtoolsEngine, PolarsBioEngine):
        with pytest.raises(Exception) as excinfo:
            engine_cls().intersect(bad_query, _annot(), how="inner")
        # The raise must come from engine input validation, not from a
        # test-internal assertion error leaking into raises().
        assert not isinstance(excinfo.value, AssertionError)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "PolarsBioEngine._join_overlap catches ALL pb.overlap exceptions and "
        "returns an empty frame (logger.error only), converting a backend "
        "failure into a scientifically plausible empty result — explicitly "
        "forbidden by SPEC 9.2. The engine must propagate the error. Task 4."
    ),
)
def test_polars_overlap_backend_failure_propagates(monkeypatch):
    import polars_bio

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated polars-bio backend failure")

    monkeypatch.setattr(polars_bio, "overlap", _boom)
    with pytest.raises(RuntimeError, match="simulated polars-bio backend failure"):
        PolarsBioEngine().intersect(_query(), _annot(), how="inner")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "PolarsBioEngine._find_nearest catches ALL pb.nearest exceptions and "
        "returns an empty frame, converting a backend failure into an empty "
        "result — explicitly forbidden by SPEC 9.2. Task 4."
    ),
)
def test_polars_nearest_backend_failure_propagates(monkeypatch):
    import polars_bio

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated polars-bio nearest backend failure")

    monkeypatch.setattr(polars_bio, "nearest", _boom)
    with pytest.raises(RuntimeError, match="simulated polars-bio nearest backend failure"):
        PolarsBioEngine(mode="closest").intersect(_query(), _annot())


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DISCOVERED in Task 3: BedtoolsEngine._bedtools_to_df catches ALL "
        "BedTool.to_dataframe exceptions and returns an empty DataFrame, "
        "converting a backend failure into a scientifically plausible empty "
        "result — explicitly forbidden by SPEC 9.2. Task 4/5."
    ),
)
def test_bedtools_result_parsing_failure_propagates(monkeypatch):
    import pybedtools

    def _boom(self, *args, **kwargs):
        raise RuntimeError("simulated bedtools result-parsing failure")

    monkeypatch.setattr(pybedtools.BedTool, "to_dataframe", _boom)
    with pytest.raises(RuntimeError, match="simulated bedtools result-parsing failure"):
        BedtoolsEngine().intersect(_query(), _annot(), how="inner")