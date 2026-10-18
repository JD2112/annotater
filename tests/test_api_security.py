"""Endpoint-boundary security tests for the FastAPI backend.

These tests exercise the two Task 14.1 objectives at the HTTP boundary:

* uploaded files are stored under server-generated names (no path traversal);
* request state is isolated per session (no cross-user read or overwrite).
"""

import threading
from pathlib import Path

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient
from tests.revision_client import RevisionClient

from streamlit_app import api_server
from streamlit_app.api_server import app
from streamlit_app.api_sessions import (
    SECURE_SESSION_COOKIE_NAME,
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
    return RevisionClient(app)


@pytest.fixture()
def https_client():
    """A client speaking TLS end-to-end (cookie jar honours Secure)."""
    return RevisionClient(app, base_url="https://testserver")


# ---------------------------------------------------------------------------
# Session cookie generation / transmission
# ---------------------------------------------------------------------------


def test_session_cookie_is_httponly_samesite_lax_over_http(client):
    # A state-changing request creates the session (stateless reads do not,
    # review finding F7).
    response = client.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    assert response.status_code == 200

    raw = response.headers.get("set-cookie")
    assert raw is not None
    assert f"{SESSION_COOKIE_NAME}=" in raw
    lowered = raw.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "secure" not in lowered


def test_session_cookie_is_secure_behind_tls_proxy(client):
    response = client.post(
        "/api/load-sample",
        data={"sample_id": "gene_overlap"},
        headers={"x-forwarded-proto": "https"},
    )
    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()


def test_session_token_is_unpredictable_and_not_reused(client):
    client.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    first = client.cookies.get(SESSION_COOKIE_NAME)
    other = RevisionClient(app)
    other.cookies.pop(SESSION_COOKIE_NAME, None)
    other.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    second = other.cookies.get(SESSION_COOKIE_NAME)
    assert first and second
    assert first != second
    assert len(first) >= 32


# ---------------------------------------------------------------------------
# __Host- session cookie over HTTPS (review finding N1)
# ---------------------------------------------------------------------------


def test_https_issues_host_prefixed_secure_cookie(https_client):
    response = https_client.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    assert response.status_code == 200

    raw = response.headers["set-cookie"]
    # Exactly one cookie is issued, under the __Host- name (the unprefixed
    # name must not ride along on the TLS path).
    assert raw.split("=", 1)[0] == SECURE_SESSION_COOKIE_NAME
    lowered = raw.lower()
    assert "secure" in lowered
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "path=/" in lowered
    # __Host- cookies must carry no Domain attribute.
    assert "domain=" not in lowered


def test_https_ignores_unprefixed_cookie_even_with_live_token(https_client):
    # A page served from a sibling subdomain over HTTPS (or any off-origin
    # content that somehow learned the token) can present the token under
    # the unprefixed cookie name. Over TLS the server must not read it, so
    # the request cannot be fixated on the victim's session.
    owner = RevisionClient(app, base_url="https://testserver")
    created = owner.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    assert created.status_code == 200
    assert owner.post("/api/execute", json={}).status_code == 200
    live_token = owner.cookies.get(SECURE_SESSION_COOKIE_NAME)
    assert live_token

    intruder = RevisionClient(app, base_url="https://testserver")
    intruder.cookies.set(SESSION_COOKIE_NAME, live_token)
    response = intruder.get("/api/results/data")
    assert response.status_code == 404
    assert response.headers.get("set-cookie") is None

    # The planted cookie touched neither the store nor the victim's state.
    assert len(api_server.store) == 1
    assert owner.get("/api/results/data").status_code == 200


def test_https_write_with_only_unprefixed_cookie_gets_fresh_session(https_client):
    # The review's required regression: under HTTPS a request whose only
    # cookie is the unprefixed name receives a fresh __Host- session, never
    # the session that name identifies.
    owner = RevisionClient(app, base_url="https://testserver")
    owner.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    owner_token = owner.cookies.get(SECURE_SESSION_COOKIE_NAME)
    assert owner_token

    https_client.cookies.set(SESSION_COOKIE_NAME, owner_token)
    created = https_client.post("/api/load-sample", data={"sample_id": "stranded_features"})
    assert created.status_code == 200

    issued = https_client.cookies.get(SECURE_SESSION_COOKIE_NAME)
    assert issued and issued != owner_token
    assert https_client.cookies.get(SESSION_COOKIE_NAME) == owner_token  # still the planted one
    assert len(api_server.store) == 2
    # Both sessions remain independent: the fresh session can execute on its
    # own data, and the owner's is untouched.
    assert https_client.post("/api/execute", json={}).status_code == 200
    assert owner.post("/api/execute", json={}).status_code == 200


def test_host_cookie_presented_over_http_is_not_honoured(client):
    # Symmetry: the server must not honour the __Host- cookie over cleartext
    # either, so a stolen token value cannot be replayed on an HTTP origin.
    owner = RevisionClient(app, base_url="https://testserver")
    owner.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    owner.post("/api/execute", json={})
    live_token = owner.cookies.get(SECURE_SESSION_COOKIE_NAME)
    assert live_token

    client.cookies.set(SECURE_SESSION_COOKIE_NAME, live_token)
    assert client.get("/api/results/data").status_code == 404
    assert len(api_server.store) == 1
    assert owner.get("/api/results/data").status_code == 200


# ---------------------------------------------------------------------------
# Byte-exact session cookie names (review finding N1-R)
# ---------------------------------------------------------------------------


def _raw_request(method, path, cookie_headers, *, https=True, **kwargs):
    """Send ``cookie_headers`` to the app as undecoded bytes.

    Starlette's ``TestClient`` re-encodes header values as UTF-8, so it cannot
    put a raw ``0xA0``/``0x85`` byte on the wire the way a browser replaying a
    server-set cookie does; ``httpx.ASGITransport`` passes bytes through.
    """
    headers = [("cookie", value) for value in cookie_headers]
    base_url = "https://testserver" if https else "http://testserver"

    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as raw:
            return await raw.request(method, path, headers=headers, **kwargs)

    return anyio.run(send)


def _victim_with_results():
    """An HTTPS user with executed results; returns (client, live token)."""
    owner = RevisionClient(app, base_url="https://testserver")
    assert owner.post("/api/load-sample", data={"sample_id": "gene_overlap"}).status_code == 200
    assert owner.post("/api/execute", json={}).status_code == 200
    token = owner.cookies.get(SECURE_SESSION_COOKIE_NAME)
    assert token
    return owner, token


# U+00A0 (NBSP) and U+0085 (NEL) are str.isspace() but not cookie OWS:
# browsers do not treat "\xa0__Host-…" as a __Host- cookie (so a sibling
# subdomain can set it with Domain=), while Starlette's cookie parser strips
# them and used to resolve the victim's session from it. Treating the alias as
# absent (ignoring it) closes that fixation path *and* the availability
# regression the old fail-closed fix introduced: a sibling-planted alias can
# neither fixate nor permanently 400 every request from that browser (#53).
_ALIAS_PREFIXES = [pytest.param(b"\xa0", id="U+00A0"), pytest.param(b"\x85", id="U+0085")]

# Edge bytes that Python's str.strip() (and therefore Starlette's cookie
# parser) removes but that RFC 6265 cookie OWS does not. AnnotateR only ever
# sets the exact name, so none of these aliases is ever legitimate.
_ALIAS_PREFIX_BYTES = [
    pytest.param(b"\xa0", id="nbsp"),
    pytest.param(b"\x85", id="nel"),
    pytest.param(b"\x0b", id="vtab"),
    pytest.param(b"\x0c", id="formfeed"),
    pytest.param(b"\x1c", id="file-sep"),
    pytest.param(b"\x1d", id="group-sep"),
    pytest.param(b"\x1e", id="record-sep"),
    pytest.param(b"\x1f", id="unit-sep"),
    pytest.param(b"\n", id="lf"),
    pytest.param(b"\r", id="cr"),
    pytest.param(b"\xa0\xa0", id="nbsp-nbsp"),
]


@pytest.mark.parametrize("prefix", _ALIAS_PREFIXES)
def test_https_whitespace_prefixed_host_cookie_is_ignored_not_fatal(prefix):
    owner, token = _victim_with_results()
    victim_csv = owner.get("/api/export/csv")
    assert victim_csv.status_code == 200

    cookie = prefix + SECURE_SESSION_COOKIE_NAME.encode() + b"=" + token.encode()
    # Even with the victim's correct result revision: a revision is not a
    # credential and never substitutes for the session cookie. The alias is
    # ignored, so the request is served by a throwaway anonymous session
    # (no stored result + a claimed revision -> 409) and is *not* a fatal 400
    # that would deny service for as long as the planted cookie persists.
    rev = owner.revisions["result"]
    for path in ("/api/export/csv", "/api/results/data", "/api/results/gene-list"):
        response = _raw_request("GET", f"{path}?result_rev={rev}", [cookie])
        assert response.status_code != 400, path
        assert response.status_code == 409, path
        assert "set-cookie" not in response.headers
        assert victim_csv.text not in response.text

    # With no claimed revision the anonymous read is a plain 404.
    assert _raw_request("GET", "/api/results/data", [cookie]).status_code == 404

    # The ignored alias neither touched the store nor the victim's state.
    assert len(api_server.store) == 1
    assert owner.get("/api/export/csv").text == victim_csv.text


@pytest.mark.parametrize("prefix", _ALIAS_PREFIXES)
def test_https_alias_alongside_genuine_cookie_keeps_session(prefix):
    # The victim's own genuine __Host- cookie plus an attacker-planted alias
    # carrying the attacker's token. The alias is ignored, never promoted, so
    # it cannot fixate the session and cannot deny service: whichever order
    # the two appear in, the byte-exact cookie resolves the victim's session.
    owner, victim_token = _victim_with_results()
    _, attacker_token = _victim_with_results()
    rev = owner.revisions["result"]
    exact = SECURE_SESSION_COOKIE_NAME.encode()
    alias = prefix + exact
    for raw in (
        exact + b"=" + victim_token.encode() + b"; " + alias + b"=" + attacker_token.encode(),
        alias + b"=" + attacker_token.encode() + b"; " + exact + b"=" + victim_token.encode(),
    ):
        response = _raw_request("GET", f"/api/results/data?result_rev={rev}", [raw])
        # Only the victim's session holds this result revision, so a 200
        # proves the byte-exact cookie was used and the alias ignored.
        assert response.status_code == 200
        assert response.json()["total_rows"] > 0
    assert len(api_server.store) == 2


@pytest.mark.parametrize("prefix", _ALIAS_PREFIXES)
def test_http_whitespace_prefixed_cookie_is_ignored(prefix):
    owner = RevisionClient(app)
    owner.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    owner.post("/api/execute", json={})
    token = owner.cookies.get(SESSION_COOKIE_NAME)
    assert token

    cookie = prefix + SESSION_COOKIE_NAME.encode() + b"=" + token.encode()
    url = f"/api/results/data?result_rev={owner.revisions['result']}"
    # Ignored alias: anonymous session + claimed revision -> 409, never 400
    # and never the victim's session.
    assert _raw_request("GET", url, [cookie], https=False).status_code == 409
    # Plain-HTTP development continuity with the exact name is unaffected.
    exact = SESSION_COOKIE_NAME.encode() + b"=" + token.encode()
    assert _raw_request("GET", url, [exact], https=False).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param("same-header", id="one-header"),
        pytest.param("split-headers", id="two-cookie-headers"),
    ],
)
def test_duplicate_session_cookie_fails_closed(headers):
    owner, token = _victim_with_results()
    pair_a = f"{SECURE_SESSION_COOKIE_NAME}={token}".encode()
    pair_b = f"{SECURE_SESSION_COOKIE_NAME}=planted-token".encode()
    if headers == "same-header":
        raw = [pair_a + b"; " + pair_b]
    else:
        raw = [pair_a, pair_b]

    url = f"/api/results/data?result_rev={owner.revisions['result']}"
    assert _raw_request("GET", url, raw).status_code == 400
    assert owner.get("/api/results/data").status_code == 200


def test_https_exact_raw_cookie_header_keeps_session_continuity():
    # Legitimate continuity: the byte-exact __Host- name in a raw header (as a
    # browser sends it, with other unrelated cookies alongside) resolves the
    # session; the unprefixed name alongside is ignored over HTTPS, not
    # treated as ambiguous.
    owner, token = _victim_with_results()
    cookie = f"theme=dark; {SESSION_COOKIE_NAME}=other; {SECURE_SESSION_COOKIE_NAME}={token}"
    url = f"/api/results/data?result_rev={owner.revisions['result']}"
    assert _raw_request("GET", url, [cookie.encode()]).status_code == 200


def test_session_token_reader_is_byte_exact():
    from streamlit_app.api_sessions import (
        AmbiguousSessionCookie,
        session_token_from_cookie_headers,
    )

    name = SECURE_SESSION_COOKIE_NAME
    read = session_token_from_cookie_headers
    assert read([], name) is None
    assert read([b"a=1"], name) is None
    assert read([f"{name}=tok".encode()], name) == "tok"
    assert read([f"a=1;\t{name}=tok ; b=2".encode()], name) == "tok"
    # Names that are not byte-exact are ignored, whether or not a
    # whitespace-stripping parser would normalise them to the session name.
    assert read([f"__host-annotater_session=x; {name}x=y".encode()], name) is None
    assert read([b"\xc2\xa0" + name.encode() + b"=x"], name) is None
    for alias in (b"\xa0", b"\x85", b"\x0b", b"\x0c", b"\x1c", b"\xa0\xa0"):
        assert read([alias + name.encode() + b"=x"], name) is None
        assert read([name.encode() + alias + b"=x"], name) is None
        # ...and the exact cookie is still honoured when an alias sits beside it.
        assert read([alias + name.encode() + b"=other; " + name.encode() + b"=tok"], name) == "tok"
    # Genuine ambiguity (the byte-exact name presented twice) still fails
    # closed, whether the values agree or not.
    with pytest.raises(AmbiguousSessionCookie):
        read([f"{name}=a; {name}=b".encode()], name)
    with pytest.raises(AmbiguousSessionCookie):
        read([f"{name}=a".encode(), f"{name}=a".encode()], name)


@pytest.mark.parametrize("prefix", _ALIAS_PREFIX_BYTES)
def test_reader_ignores_every_whitespace_alias(prefix):
    from streamlit_app.api_sessions import session_token_from_cookie_headers

    exact = SECURE_SESSION_COOKIE_NAME.encode()
    # Leading and trailing alias bytes are ignored, never promoted.
    assert session_token_from_cookie_headers([prefix + exact + b"=x"], SECURE_SESSION_COOKIE_NAME) is None
    assert session_token_from_cookie_headers([exact + prefix + b"=x"], SECURE_SESSION_COOKIE_NAME) is None
    # The exact cookie beside an alias still resolves.
    assert (
        session_token_from_cookie_headers(
            [prefix + exact + b"=other; " + exact + b"=tok"], SECURE_SESSION_COOKIE_NAME
        )
        == "tok"
    )


def test_expired_session_token_is_treated_as_absent_not_fatal(monkeypatch):
    # A token that has aged out of the store is resolved as no session at all
    # (anonymous read -> 404 here), never a 400: expiry must not deny service.
    from streamlit_app.api_sessions import SessionStore

    expired_store = SessionStore(ttl_seconds=-1)
    monkeypatch.setattr(api_server, "store", expired_store)
    token = expired_store.create().token

    cookie = f"{SECURE_SESSION_COOKIE_NAME}={token}".encode()
    assert _raw_request("GET", "/api/results/data", [cookie]).status_code == 404
    assert _raw_request("GET", "/api/export/csv", [cookie]).status_code == 404


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
    a = RevisionClient(app)
    b = RevisionClient(app)

    assert a.post("/api/load-sample", data={"sample_id": "gene_overlap"}).status_code == 200

    # b never loaded anything and must not see a's datasets.
    assert b.post("/api/execute", json={}).status_code == 400
    assert b.get("/api/results/data").status_code == 404
    assert b.get("/api/export/csv").status_code == 404

    # Anonymous (cookie-less) requests never allocate a stored session or
    # receive a cookie: capacity is consumed only on the first state write
    # (review finding N4).
    assert b.cookies.get(SESSION_COOKIE_NAME) is None
    assert len(api_server.store) == 1

    token_a = a.cookies.get(SESSION_COOKIE_NAME)
    assert token_a

    assert a.post("/api/execute", json={}).status_code == 200
    rows_before = a.get("/api/results/data").json()["total_rows"]

    # b's own work must not affect a's stored results.
    assert (
        b.post("/api/load-sample", data={"sample_id": "closest_variants"}).status_code
        == 200
    )
    token_b = b.cookies.get(SESSION_COOKIE_NAME)
    assert token_b and token_b != token_a
    assert b.post("/api/execute", json={"mode": "closest"}).status_code == 200

    assert a.get("/api/results/data").json()["total_rows"] == rows_before


def test_unknown_cookie_token_is_ignored_and_replaced(client):
    from streamlit_app import api_server

    client.cookies.set(SESSION_COOKIE_NAME, "forged-token-value")
    # A stateless read with an unknown token reads nothing and, under the
    # stateless-read contract (review finding F7), must not allocate a
    # stored session or issue a replacement cookie.
    response = client.get("/api/results/data")
    assert response.status_code == 404
    assert response.headers.get("set-cookie") is None
    assert len(api_server.store) == 0

    # A state-changing request with the forged token gets a fresh session
    # that replaces the forged cookie.
    created = client.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    assert created.status_code == 200
    issued = created.headers.get("set-cookie")
    assert issued is not None
    assert "forged-token-value" not in issued


def test_sessions_loaded_for_different_samples_stay_distinct():
    a = RevisionClient(app)
    b = RevisionClient(app)
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
    a = RevisionClient(app)
    b = RevisionClient(app)
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
