"""
Backend selection registry (Task 7).

Maps the user-facing annotation-engine choice to a concrete engine class
and nothing else. The engine choice MUST change execution only: parsing,
format detection, coordinate normalization, and result semantics are all
upstream of this module and never receive the engine choice.

Contract points (SPEC 11; docs/engine-contract.md):

- The mapping is explicit and deterministic: a UI option key maps to
  exactly one engine class. There is no substring matching and no
  hidden fallback: an unavailable or invalid backend raises
  ``EngineUnavailableError`` (or ``ValueError``) instead of silently
  switching to the other backend.
- The default backend is Bedtools, the historical default. It is
  preserved by product decision (Task 7 section 13), not because it is
  the only working backend.
- Availability checks are advisory at selection time; the UI displays
  them and blocks execution with an explicit, actionable error.
"""

from __future__ import annotations

import importlib.util
import shutil
from typing import Optional, Tuple

from .annotator import (
    AnnotationEngine,
    BedtoolsEngine,
    PolarsBioEngine,
    validate_min_overlap,
)


class EngineUnavailableError(RuntimeError):
    """The selected backend cannot be used in this environment.

    Carries a user-facing message naming the unavailable backend and the
    action to take. The app renders this message and does NOT fall back
    to another backend.
    """


#: User-facing engine options in UI display order: (key, label).
#: Internal class names are never shown to the user.
ENGINE_OPTIONS: Tuple[Tuple[str, str], ...] = (
    ("bedtools", "Bedtools"),
    ("polars-bio", "Polars-Bio"),
)

ENGINE_LABELS = dict(ENGINE_OPTIONS)

#: Short user-facing descriptions. The two engines produce contractually
#: equivalent results (SPEC 13); the copy must not imply differing
#: biological results, and no performance claim is made without
#: benchmark evidence.
ENGINE_DESCRIPTIONS = {
    "bedtools": "Reference implementation",
    "polars-bio": "In-process implementation",
}

#: Historical default backend, preserved (Task 7 section 13).
DEFAULT_ENGINE = "bedtools"

ENGINE_CLASSES = {
    "bedtools": BedtoolsEngine,
    "polars-bio": PolarsBioEngine,
}


def engine_label(key: str) -> str:
    """User-facing label for an engine key; raises ValueError if unknown."""
    try:
        return ENGINE_LABELS[key]
    except KeyError:
        raise ValueError(
            f"Unknown engine key: {key!r}; expected one of "
            f"{sorted(ENGINE_LABELS)}"
        ) from None


def bedtools_available() -> bool:
    """True when the ``bedtools`` binary can be resolved on PATH.

    pybedtools is a pure-Python wrapper that resolves the external
    ``bedtools`` executable at call time (see docs/implementation-notes.md,
    Task 2.5); the binary itself is the availability gate.
    """
    return shutil.which("bedtools") is not None


def polars_bio_available() -> bool:
    """True when the ``polars_bio`` Python package is importable."""
    return importlib.util.find_spec("polars_bio") is not None


def engine_available(key: str) -> bool:
    """Availability of a backend by key (raises ValueError if unknown)."""
    engine_label(key)  # validate key
    if key == "bedtools":
        return bedtools_available()
    return polars_bio_available()


def unavailable_message(key: str) -> str:
    """Actionable user-facing message for an unavailable backend."""
    label = engine_label(key)
    alternative = engine_label(
        "bedtools" if key == "polars-bio" else "polars-bio"
    )
    return (
        f"{label} is unavailable in this environment. "
        f"Choose {alternative} or contact the deployment administrator."
    )


def build_engine(
    key: str,
    *,
    mode: str,
    use_strand: bool = False,
    min_overlap: Optional[float] = None,
) -> AnnotationEngine:
    """
    Build the engine for a UI option key with validated options.

    Raises:
        ValueError: unknown engine key or invalid ``min_overlap``
            (shared validation, SPEC 8.2).
        EngineUnavailableError: the selected backend cannot be used in
            this environment. No fallback to another backend occurs.
    """
    label = engine_label(key)
    cls = ENGINE_CLASSES[key]

    if not engine_available(key):
        raise EngineUnavailableError(unavailable_message(key))

    # Shared, backend-independent option validation BEFORE construction,
    # so an invalid option never reaches a backend (SPEC 8.2 / 9.2).
    validated_min_overlap = validate_min_overlap(min_overlap)

    try:
        engine = cls(
            use_strand=use_strand,
            min_overlap=validated_min_overlap,
            mode=mode,
        )
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise EngineUnavailableError(
            f"{label} could not be initialized: {exc}. "
            f"{unavailable_message(key)}"
        ) from exc
    return engine