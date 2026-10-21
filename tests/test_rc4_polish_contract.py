"""M2.5 RC4 pre-release polish: the user-facing upload limit, the bundled
sample catalog and the chromosome-source wording must not drift.

These are contract tests for *user-facing* facts that are easy to let
drift: the upload limit the server enforces, the manual pages that state
it, the frontend hints that render it, the bundled sample catalog the
frontend reads, and the wording of the chromosome-source selector.

They deliberately do not touch scientific semantics: the upload limit is a
transport property, the sample catalog is served by the API, and the
selector wording is user interface.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from streamlit_app import api_server
from streamlit_app.api_server import app
from streamlit_app.api_sessions import SessionStore
from streamlit_app.config import Settings

ROOT = Path(__file__).resolve().parents[1]
APP_JSX = ROOT / "frontend" / "src" / "App.jsx"
APP_SOURCE = APP_JSX.read_text("utf-8")

#: The manual pages that state the upload limit a user of the current
#: React/FastAPI application actually meets.
LIMIT_PAGES = (
    "docs/limitations.md",
    "docs/faq.md",
    "docs/using/uploading-files.md",
    "docs/troubleshooting.md",
    "docs/preparing-your-data/chromosome-identifiers.md",
)

#: The deployment guide states both generations' limits separately.
DEPLOYMENT_PAGE = "docs/deployment.md"


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    monkeypatch.setattr(api_server, "store", SessionStore())


def _meta(client):
    response = client.get("/api/meta")
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# The server publishes the limit it enforces
# ---------------------------------------------------------------------------

def test_meta_publishes_the_enforced_upload_limit():
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        body = _meta(client)
    assert body["max_file_size_mb"] == Settings.get_max_file_size_bytes() // (1024 * 1024)
    assert body["max_file_size_mb"] == Settings.MAX_FILE_SIZE_MB


def test_meta_publishes_a_changed_limit(monkeypatch):
    """The published limit follows the configured limit, not a constant."""
    from fastapi.testclient import TestClient

    monkeypatch.setattr(Settings, "MAX_FILE_SIZE_MB", 7)
    with TestClient(app) as client:
        body = _meta(client)
    assert body["max_file_size_mb"] == 7


def test_the_upload_limit_is_not_silently_changed():
    """The enforced default is the documented one; the limit stays a
    configuration, not a hard-coded constant in the endpoint."""
    assert Settings.get_max_file_size_bytes() == Settings.MAX_FILE_SIZE_MB * 1024 * 1024
    # The endpoint reads the setting rather than repeating a number.
    source = (ROOT / "streamlit_app" / "api_server.py").read_text("utf-8")
    assert "Settings.get_max_file_size_bytes()" in source


# ---------------------------------------------------------------------------
# The manual pages state the authoritative limit
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("relative", LIMIT_PAGES)
def test_manual_pages_state_the_authoritative_limit(relative):
    text = (ROOT / relative).read_text("utf-8")
    assert "MAX_FILE_SIZE_MB" in text, (
        f"{relative} must name the setting that decides the upload limit"
    )
    assert f"{Settings.MAX_FILE_SIZE_MB} MB" in text, (
        f"{relative} must state the default limit of {Settings.MAX_FILE_SIZE_MB} MB"
    )
    # The stale claim -- that Streamlit's 200 MB default is the limit the
    # user meets -- must not come back.
    assert "200 MB per file" not in text, (
        f"{relative} still presents Streamlit's 200 MB default as the limit "
        "of the served application"
    )
    assert "file > 200 MB" not in text, f"{relative} still states a 200 MB limit"


def test_deployment_page_keeps_both_generations_separate():
    text = (ROOT / DEPLOYMENT_PAGE).read_text("utf-8")
    # The React/FastAPI generation's own limit ...
    assert "MAX_FILE_SIZE_MB" in text
    assert f"{Settings.MAX_FILE_SIZE_MB} MB" in text
    # ... and the Streamlit generation's separate limit stay documented.
    assert "STREAMLIT_SERVER_MAX_UPLOAD_SIZE" in text
    assert "200 MB" in text


# ---------------------------------------------------------------------------
# The frontend never repeats a number of its own
# ---------------------------------------------------------------------------

def test_frontend_renders_the_published_upload_limit():
    assert "max_file_size_mb" in APP_SOURCE
    # No hard-coded size in the upload hints.
    assert not re.search(r"\b\d+\s?MB per file", APP_SOURCE), (
        "the React upload hint must not hard-code a size; it renders the "
        "limit published in /api/meta"
    )


def test_frontend_reads_the_sample_catalog_instead_of_naming_a_sample():
    assert "/api/sample-datasets" in APP_SOURCE
    # No bundled sample id is hard-coded in the frontend: the ids, names and
    # declared operations come from the catalog the API serves.
    for sample_id in ("gene_overlap", "closest_variants", "stranded_features"):
        assert f"'{sample_id}'" not in APP_SOURCE, sample_id
        assert f'"{sample_id}"' not in APP_SOURCE, sample_id


def test_frontend_does_not_claim_to_detect_an_assembly():
    assert "Select genome assembly (Auto-detect)" not in APP_SOURCE
    assert "No assembly (keep chromosome names as provided)" in APP_SOURCE


def test_frontend_states_the_results_preview():
    """The results panel says the table is a preview of the first rows."""
    assert "RESULT_PREVIEW_ROWS" in APP_SOURCE
    assert "complete result" in APP_SOURCE
