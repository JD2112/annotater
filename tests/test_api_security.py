"""Endpoint-boundary security tests for the FastAPI backend.

These tests exercise the two Task 14.1 objectives at the HTTP boundary:

* uploaded files are stored under server-generated names (no path traversal);
* request state is isolated per session (no cross-user read or overwrite).
"""

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from streamlit_app import api_server
from streamlit_app.api_server import app
from streamlit_app.api_sessions import (
    SESSION_COOKIE_NAME,
    SessionStore,
    safe_extension,
)
from streamlit_app.utils import get_example_data_path


def _example_bytes(name: str) -> bytes:
    return Path(get_example_data_path(name)).read_bytes()


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    """Give every test its own session store (no state bleed between tests)."""
    monkeypatch.setattr(api_server, "store", SessionStore())


@pytest.fixture()
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Session cookie generation / transmission
# ---------------------------------------------------------------------------


def test_session_cookie_is_httponly_samesite_lax_over_http(client):
    response = client.get("/api/results/data")
    assert response.status_code == 404

    raw = response.headers.get("set-cookie")
    assert raw is not None
    assert f"{SESSION_COOKIE_NAME}=" in raw
    lowered = raw.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "secure" not in lowered


def test_session_cookie_is_secure_behind_tls_proxy(client):
    response = client.get(
        "/api/results/data", headers={"x-forwarded-proto": "https"}
    )
    assert "secure" in response.headers["set-cookie"].lower()


def test_session_token_is_unpredictable_and_not_reused(client):
    client.get("/api/results/data")
    first = client.cookies.get(SESSION_COOKIE_NAME)
    other = TestClient(app)
    other.cookies.pop(SESSION_COOKIE_NAME, None)
    other.get("/api/results/data")
    second = other.cookies.get(SESSION_COOKIE_NAME)
    assert first and second
    assert first != second
    assert len(first) >= 32


# ---------------------------------------------------------------------------
# Session state isolation
# ---------------------------------------------------------------------------


def test_state_persists_across_requests_for_one_client(client):
    assert (
        client.post("/api/load-sample", data={"sample_id": "gene_overlap"}).status_code
        == 200
    )
    execute = client.post("/api/execute", json={})
    assert execute.status_code == 200
    assert execute.json()["stats"]["query_count"] > 0
    assert client.get("/api/results/data").status_code == 200


def test_two_clients_do_not_share_state():
    a = TestClient(app)
    b = TestClient(app)

    assert a.post("/api/load-sample", data={"sample_id": "gene_overlap"}).status_code == 200

    # b never loaded anything and must not see a's datasets.
    assert b.post("/api/execute", json={}).status_code == 400
    assert b.get("/api/results/data").status_code == 404
    assert b.get("/api/export/csv").status_code == 404

    token_a = a.cookies.get(SESSION_COOKIE_NAME)
    token_b = b.cookies.get(SESSION_COOKIE_NAME)
    assert token_a and token_b and token_a != token_b

    assert a.post("/api/execute", json={}).status_code == 200
    rows_before = a.get("/api/results/data").json()["total_rows"]

    # b's own work must not affect a's stored results.
    assert (
        b.post("/api/load-sample", data={"sample_id": "closest_variants"}).status_code
        == 200
    )
    assert b.post("/api/execute", json={"mode": "closest"}).status_code == 200

    assert a.get("/api/results/data").json()["total_rows"] == rows_before


def test_unknown_cookie_token_is_ignored_and_replaced(client):
    client.cookies.set(SESSION_COOKIE_NAME, "forged-token-value")
    response = client.get("/api/results/data")
    assert response.status_code == 404

    issued = response.headers.get("set-cookie")
    assert issued is not None
    assert "forged-token-value" not in issued


def test_sessions_loaded_for_different_samples_stay_distinct():
    a = TestClient(app)
    b = TestClient(app)
    a.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    b.post("/api/load-sample", data={"sample_id": "stranded_features"})

    stats_a = a.post("/api/execute", json={}).json()["stats"]
    stats_b = b.post("/api/execute", json={}).json()["stats"]

    assert stats_a["query_count"] > 0
    assert stats_b["query_count"] > 0
    assert stats_a["result_count"] == stats_a["result_count"]
    assert stats_a != stats_b


# ---------------------------------------------------------------------------
# Upload path safety
# ---------------------------------------------------------------------------


def test_upload_absolute_filename_cannot_write_outside_storage(tmp_path, client):
    target = tmp_path / "pwned.bed"
    target.write_bytes(b"SENTINEL")

    response = client.post(
        "/api/upload",
        files={"file": (str(target), _example_bytes("example_coordinates.bed"))},
        data={"role": "query"},
    )

    assert response.status_code == 200, response.text
    # The server received the absolute path verbatim, so the old
    # `Path(temp_dir) / filename` join would have written to `target`.
    assert response.json()["filename"] == str(target)
    assert target.read_bytes() == b"SENTINEL"


def test_upload_dotdot_filename_cannot_escape_storage(tmp_path, monkeypatch, client):
    monkeypatch.chdir(tmp_path)
    response = client.post(
        "/api/upload",
        files={"file": ("../../../pwned.bed", _example_bytes("example_coordinates.bed"))},
        data={"role": "query"},
    )
    assert response.status_code == 200, response.text
    assert not (tmp_path / "pwned.bed").exists()
    assert not (tmp_path.parent / "pwned.bed").exists()


def test_upload_preserves_valid_extension_and_parses(client):
    response = client.post(
        "/api/upload",
        files={"file": ("strange name.gff3", _example_bytes("example_annotations.gff3"))},
        data={"role": "annot"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["format"] == "gff"
    assert body["needs_mapping"] is False
    assert body["filename"] == "strange name.gff3"


def test_upload_without_extension_parses_by_content(client):
    response = client.post(
        "/api/upload",
        files={"file": ("coords", _example_bytes("example_coordinates.bed"))},
        data={"role": "query"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["format"] == "bed"


def test_upload_rejects_invalid_role(client):
    response = client.post(
        "/api/upload",
        files={"file": ("q.bed", _example_bytes("example_coordinates.bed"))},
        data={"role": "admin"},
    )
    assert response.status_code == 400


def test_upload_rejects_oversized_file(client, monkeypatch):
    monkeypatch.setattr(
        api_server.Settings, "get_max_file_size_bytes", classmethod(lambda cls: 8)
    )
    response = client.post(
        "/api/upload",
        files={"file": ("q.bed", _example_bytes("example_coordinates.bed"))},
        data={"role": "query"},
    )
    assert response.status_code == 413


def test_upload_error_does_not_leak_server_paths(client):
    response = client.post(
        "/api/upload",
        files={"file": ("broken.bed", b"\x00\x01not a genomic file\x02")},
        data={"role": "query"},
    )
    assert response.status_code in (400, 422)
    detail = response.json().get("detail", "")
    assert "annotater-upload-" not in detail
    assert "/tmp/" not in detail


def test_uploaded_state_is_session_scoped():
    a = TestClient(app)
    b = TestClient(app)
    assert (
        a.post(
            "/api/upload",
            files={"file": ("q.bed", _example_bytes("example_coordinates.bed"))},
            data={"role": "query"},
        ).status_code
        == 200
    )
    assert (
        a.post(
            "/api/upload",
            files={"file": ("a.gff3", _example_bytes("example_annotations.gff3"))},
            data={"role": "annot"},
        ).status_code
        == 200
    )
    assert a.post("/api/execute", json={}).status_code == 200

    # b uploaded nothing; a's uploaded state must be invisible to b.
    assert b.post("/api/execute", json={}).status_code == 400
    assert b.get("/api/results/data").status_code == 404


# ---------------------------------------------------------------------------
# SessionStore unit behaviour
# ---------------------------------------------------------------------------


def test_safe_extension_accepts_only_safe_suffixes():
    assert safe_extension("regions.bed") == ".bed"
    assert safe_extension("features.gff3") == ".gff3"
    assert safe_extension("path/to/features.vcf") == ".vcf"
    assert safe_extension("windows\\path\\x.bed") == ".bed"
    assert safe_extension("noext") == ""
    assert safe_extension(None) == ""
    assert safe_extension("evil...") == ""
    assert safe_extension("evil.b/e/d") == ""
    assert safe_extension("spaces in name.bed") == ".bed"


def test_safe_extension_rejects_path_components_and_overlong():
    assert safe_extension("x.tar.gz") == ".gz"
    assert safe_extension("x.verylongextension") == ""
    assert safe_extension("x.bed/../etc") == ""


def test_store_expires_idle_sessions():
    store = SessionStore(ttl_seconds=10)
    session = store.create(now=100)
    assert store.get(session.token, now=105) is session
    assert store.get(session.token, now=200) is None
    assert len(store) == 0


def test_store_drop_only_affects_target_session():
    store = SessionStore()
    first = store.create()
    second = store.create()
    store.drop(first.token)
    assert store.get(first.token) is None
    assert store.get(second.token) is second


def test_store_is_bounded_and_evicts_oldest():
    store = SessionStore(max_sessions=3)
    sessions = [store.create(now=float(i)) for i in range(3)]
    store.get(sessions[0].token, now=3.0)
    newest = store.create(now=4.0)

    assert len(store) == 3
    assert store.get(sessions[1].token, now=5.0) is None
    assert store.get(sessions[0].token, now=5.0) is not None
    assert store.get(newest.token, now=5.0) is not None


def test_store_handles_concurrent_access():
    store = SessionStore(max_sessions=10_000)
    created = []
    lock = threading.Lock()

    def worker():
        for _ in range(50):
            session = store.create()
            session.data["x"] = 1
            with lock:
                created.append(session.token)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(created) == len(set(created)) == 400
    assert len(store) == 400
