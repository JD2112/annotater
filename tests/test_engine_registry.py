"""
Backend selection registry tests (Task 7)

The engine choice must map deterministically to exactly one engine class
and change execution only: no substring matching, no hidden fallback,
explicit option validation before any backend is constructed.
"""

from __future__ import annotations

import pytest

from streamlit_app.core.annotator import BedtoolsEngine, PolarsBioEngine
from streamlit_app.core.engine_registry import (
    DEFAULT_ENGINE,
    ENGINE_LABELS,
    ENGINE_OPTIONS,
    EngineUnavailableError,
    bedtools_available,
    build_engine,
    engine_available,
    engine_label,
    polars_bio_available,
    unavailable_message,
)


class TestUserFacingOptions:
    def test_exposes_bedtools_and_polars_bio(self):
        assert [label for _, label in ENGINE_OPTIONS] == [
            "Bedtools",
            "Polars-Bio",
        ]

    def test_no_internal_class_names_in_labels(self):
        for label in ENGINE_LABELS.values():
            assert "Engine" not in label
            assert label in ("Bedtools", "Polars-Bio")

    def test_default_backend_is_the_historical_bedtools_default(self):
        # Task 7 section 13: the historical default is preserved; the
        # choice is a documented product decision, not engine novelty.
        assert DEFAULT_ENGINE == "bedtools"
        assert engine_label(DEFAULT_ENGINE) == "Bedtools"


class TestDeterministicMapping:
    @pytest.mark.parametrize(
        ("key", "cls"),
        [("bedtools", BedtoolsEngine), ("polars-bio", PolarsBioEngine)],
    )
    def test_key_maps_to_exactly_one_engine_class(self, key, cls):
        assert isinstance(build_engine(key, mode="overlap"), cls)

    def test_selected_options_reach_the_engine(self):
        engine = build_engine(
            "polars-bio", mode="closest", use_strand=True
        )
        assert engine.mode == "closest"
        assert engine.use_strand is True
        assert engine.min_overlap is None

    def test_min_overlap_zero_is_a_valid_noop(self):
        # SPEC 8.2: 0 is a valid numeric threshold equivalent to ordinary
        # positive overlap; the UI maps slider 0 -> None, and the registry
        # accepts the explicit 0 either way.
        assert build_engine("bedtools", mode="overlap", min_overlap=0).min_overlap == 0.0

    @pytest.mark.parametrize(
        "bad",
        [-0.1, 1.5, float("nan"), float("inf"), True, "0.5", [0.5]],
    )
    def test_invalid_min_overlap_rejected_before_any_backend(self, bad):
        # Shared validation (SPEC 8.2): invalid values are rejected, never
        # clamped, and never forwarded to a backend.
        with pytest.raises(ValueError):
            build_engine("bedtools", mode="overlap", min_overlap=bad)

    def test_unknown_engine_key_rejected(self):
        with pytest.raises(ValueError):
            build_engine("polars", mode="overlap")


class TestAvailability:
    def test_availability_is_boolean_for_both_backends(self):
        for key, _ in ENGINE_OPTIONS:
            assert isinstance(engine_available(key), bool)

    def test_local_environment_reports_both_backends(self):
        # The repository test environment pins both backends (Task 2.5
        # audit); a deployment without one is covered by the fallback-free
        # behavior tests below.
        assert bedtools_available()
        assert polars_bio_available()

    def test_unavailable_engine_raises_without_fallback(self, monkeypatch):
        monkeypatch.setattr(
            "streamlit_app.core.engine_registry.bedtools_available",
            lambda: False,
        )
        with pytest.raises(EngineUnavailableError) as excinfo:
            build_engine("bedtools", mode="overlap")
        message = str(excinfo.value)
        assert "Bedtools" in message
        assert "Polars-Bio" in message  # names the alternative
        assert "deployment administrator" in message

    def test_unavailable_message_is_actionable(self):
        assert "unavailable in this environment" in unavailable_message("bedtools")
        assert "unavailable in this environment" in unavailable_message("polars-bio")