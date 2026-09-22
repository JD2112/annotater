"""
Streamlit application contract smoke test (PLAN Task 2.5)

Verifies with Streamlit's native ``AppTest`` (see docs/references.md,
"Application and testing") that the application entry point executes
headlessly from the repository root without raising, so backend selection
and rendering can be layered on top of a runnable app in later tasks.
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_ENTRYPOINT = (
    Path(__file__).resolve().parent.parent / "streamlit_app" / "streamlit_app.py"
)


def test_app_entrypoint_exists():
    assert APP_ENTRYPOINT.is_file(), (
        f"expected Streamlit entry point at {APP_ENTRYPOINT}"
    )


def test_app_runs_headless_without_exception():
    app_test = AppTest.from_file(APP_ENTRYPOINT, default_timeout=60)
    app_test.run()

    assert not app_test.exception, [
        str(exc.value if hasattr(exc, "value") else exc) for exc in app_test.exception
    ]
    # The landing page renders its informational blocks.
    assert len(app_test.markdown) > 0