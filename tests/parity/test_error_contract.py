"""
Error / failure-behavior contract (PLAN Task 3) — SPEC 9.2.

A backend failure MUST propagate as an explicit error: "swallowing
backend exceptions and converting them into a scientifically plausible
empty result is forbidden". Equally important, a GENUINELY empty input
may produce a genuinely empty result (see the empty-input cases in
test_left_parity.py) — the distinction is between *valid empty input*
and *failure of the backend call*.

Failure propagation now passes for BOTH engines (Task 4 for Polars-Bio,
Task 5 for Bedtools): neither engine swallows backend exceptions, and
``test_bedtools_result_parsing_failure_propagates`` (originally
DISCOVERED in Task 3: the old ``_bedtool_to_df`` caught all
``to_dataframe`` exceptions and returned an empty DataFrame) is a
positive test again.

Since Task 6E, ``mode="closest"`` makes no backend call at all (the
shared canonical selection replaces bedtools ``closest`` and
``pb.nearest``), so its failure contract is: malformed input raises
explicitly for both engines, and no native failure can be converted
into an unmatched row — pinned by
``test_polars_closest_never_invokes_backend_nearest`` and
``test_closest_malformed_input_raises_instead_of_empty``.
"""

from __future__ import annotations

import pandas as pd
import pytest

from streamlit_app.core import BedtoolsEngine, PolarsBioEngine
from streamlit_app.core.schema import CanonicalSchemaError

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


def test_polars_overlap_backend_failure_propagates(monkeypatch):
    import polars_bio

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated polars-bio backend failure")

    monkeypatch.setattr(polars_bio, "overlap", _boom)
    with pytest.raises(RuntimeError, match="simulated polars-bio backend failure"):
        PolarsBioEngine().intersect(_query(), _annot(), how="inner")


def test_polars_closest_never_invokes_backend_nearest(monkeypatch):
    """Task 6E / SPEC 8.6: closest is the shared canonical selection, so
    the engine never calls polars-bio's native ``nearest``. Neither its
    ``k=1`` tie-dropping neighbor selection nor its native ``distance``
    column can define (or fail) an AnnotateR result — and since no
    backend call happens, there is no native failure that could ever be
    converted into an unmatched or empty result (SPEC 9.2).

    (This replaces the pre-Task-6E placeholder test, which asserted
    that a *pb.nearest* failure propagated from the closest path; that
    path no longer exists.)
    """
    import polars_bio

    calls = []
    monkeypatch.setattr(
        polars_bio, "nearest", lambda *args, **kwargs: calls.append("nearest")
    )
    result = PolarsBioEngine(mode="closest").intersect(_query(), _annot())
    assert calls == []  # native nearest is never consulted
    assert len(result) == 1  # canonical result computed in AnnotateR


def test_closest_malformed_input_raises_instead_of_empty():
    """Closest's only failure mode is explicit input validation (SPEC
    9.2): malformed canonical input must raise the concrete
    ``CanonicalSchemaError`` for BOTH engines, never return an
    empty/unmatched result and never raise an accidental internal
    error type."""
    bad_query = pd.DataFrame({"start": [10], "end": [20]})  # no 'chr'
    for engine_cls in (BedtoolsEngine, PolarsBioEngine):
        with pytest.raises(CanonicalSchemaError, match="missing required column"):
            engine_cls(mode="closest").intersect(bad_query, _annot(), how="inner")


def test_bedtools_result_parsing_failure_propagates(monkeypatch):
    import pybedtools

    def _boom(self, *args, **kwargs):
        raise RuntimeError("simulated bedtools result-parsing failure")

    monkeypatch.setattr(pybedtools.BedTool, "to_dataframe", _boom)
    with pytest.raises(RuntimeError, match="simulated bedtools result-parsing failure"):
        BedtoolsEngine().intersect(_query(), _annot(), how="inner")