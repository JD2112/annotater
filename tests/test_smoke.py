"""
Smoke tests for the repository baseline (PLAN Task 1)

Verify that:
- core AnnotateR modules can be imported from the repository root
  (i.e. without launching Python from inside ``streamlit_app/``);
- ``BedtoolsEngine`` can be imported and constructed without
  performing an interval operation (no bedtools binary required);
- ``PolarsBioEngine`` can be imported and constructed without
  performing an interval operation.

Run from the repository root with::

    pytest tests/test_smoke.py -v
"""

import streamlit_app
import streamlit_app.config
import streamlit_app.core
import streamlit_app.utils


def test_package_importable_from_repository_root():
    """Top-level package and all subpackages import without sys.path hacks."""
    assert streamlit_app.__version__
    for subpackage in ("core", "config", "utils"):
        assert hasattr(streamlit_app, subpackage)


def test_core_public_names_importable():
    """Every name advertised in ``streamlit_app.core.__all__`` resolves."""
    for name in streamlit_app.core.__all__:
        assert hasattr(streamlit_app.core, name), name


def test_utils_public_names_importable():
    """Every name advertised in ``streamlit_app.utils.__all__`` resolves."""
    for name in streamlit_app.utils.__all__:
        assert hasattr(streamlit_app.utils, name), name


def test_bedtools_engine_import_and_construct():
    """BedtoolsEngine constructs without touching the bedtools binary."""
    BedtoolsEngine = streamlit_app.core.BedtoolsEngine
    engine = BedtoolsEngine()
    assert engine.mode == "overlap"
    assert engine.use_strand is False
    assert engine.min_overlap is None


def test_polars_bio_engine_import_and_construct():
    """PolarsBioEngine constructs without performing an interval operation."""
    PolarsBioEngine = streamlit_app.core.PolarsBioEngine
    engine = PolarsBioEngine()
    assert engine.mode == "overlap"
    assert engine.use_strand is False
    assert engine.min_overlap is None