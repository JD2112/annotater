"""Revision-safe dataset clearing (issues #51 and #52).

``POST /api/dataset/clear`` used to discard whatever was stored for a role
when the request named no revision. The React frontend sent exactly that on
the unknown-outcome path (an upload or mapping whose fetch rejected without
an HTTP response): if a second tab of the same browser session had uploaded
a newer dataset in the meantime, the revision-less clear wiped it. The
tightened contract refuses a revision-less clear once a dataset is stored
(428) and only ever removes the exact revision the client names (409 on a
mismatch), so no cleanup path can remove a dataset the tab does not own.

The companion frontend regression coverage lives in
``frontend/src/app.behavior.test.jsx``; these tests pin the server contract
those requests rely on.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from streamlit_app import api_server
from streamlit_app.api_server import app
from streamlit_app.api_sessions import SESSION_COOKIE_NAME, SessionStore
from tests.revision_client import RevisionClient

AUTO = "Auto-detect"
ONE_BASED = "1-based (GFF/GTF/VCF)"
QUERY = b"chr1\t100\t200\tr1\n"
ANNOT = b"chr1\t99\t100\tleft_edge_base100\n"


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    monkeypatch.setattr(api_server, "store", SessionStore())


def _tab() -> RevisionClient:
    return RevisionClient(app)


def _second_tab_of(tab: RevisionClient) -> RevisionClient:
    other = RevisionClient(app)
    other.cookies.set(SESSION_COOKIE_NAME, tab.cookies.get(SESSION_COOKIE_NAME))
    return other


def _session(tab: RevisionClient):
    return api_server.store.get(tab.cookies.get(SESSION_COOKIE_NAME))


def _unknown_revision_tab(tab: RevisionClient) -> TestClient:
    """A tab of the same session that has seen no revision (a plain client).

    ``RevisionClient`` echoes revisions it was given; this models the case the
    server must defend against on its own: a request that names no revision.
    """
    raw = TestClient(app)
    raw.cookies.set(SESSION_COOKIE_NAME, tab.cookies.get(SESSION_COOKIE_NAME))
    return raw


def _upload(tab, role, content, coord_system=AUTO):
    name = "regions.tsv" if role == "query" else "annot.bed"
    response = tab.post(
        "/api/upload",
        files={"file": (name, content, "text/plain")},
        data={"role": role, "coord_system": coord_system},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# The revision contract of a clear
# ---------------------------------------------------------------------------


def test_missing_revision_on_a_loaded_side_is_428_and_changes_nothing():
    tab = _tab()
    _upload(tab, "query", QUERY)
    session = _session(tab)
    stored_before = session.data["query"]
    high_water_before = dict(session.write_done)

    response = _unknown_revision_tab(tab).post(
        "/api/dataset/clear", json={"role": "query"}
    )

    assert response.status_code == 428
    detail = response.json()["detail"]
    assert "revision for the stored query dataset is required" in detail
    # Nothing was removed and the write-order high-water mark did not move.
    session = _session(tab)
    assert session.data.get("query") is stored_before
    assert session.write_done == high_water_before


def test_matching_revision_clears_the_dataset():
    tab = _tab()
    uploaded = _upload(tab, "query", QUERY)

    response = tab.post(
        "/api/dataset/clear",
        json={"role": "query", "revision": uploaded["revision"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "cleared": "query",
        "was_loaded": True,
    }
    assert "query" not in _session(tab).data


def test_stale_revision_is_409_and_preserves_the_newer_dataset():
    tab = _tab()
    stale = _upload(tab, "query", QUERY)["revision"]
    newer = _upload(tab, "query", QUERY, ONE_BASED)

    response = tab.post(
        "/api/dataset/clear", json={"role": "query", "revision": stale}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "revision_conflict"
    stored = _session(tab).data["query"]
    assert stored["rev"] == newer["revision"]


def test_clear_with_a_revision_but_nothing_stored_is_a_200_no_op():
    tab = _tab()
    response = tab.post(
        "/api/dataset/clear", json={"role": "query", "revision": "whatever"}
    )
    assert response.status_code == 200
    assert response.json()["was_loaded"] is False
    # A no-op removal still allocates no session (finding N4).
    assert len(api_server.store) == 0


def test_clearing_one_side_keeps_a_result_derived_from_another_revision():
    """Only a result derived from the cleared dataset is invalidated (F5).

    The result is bound to the query revision it ran on. Re-uploading the
    query gives a new revision, so clearing that new revision (which no
    stored result was derived from) must leave the result alone.
    """
    tab = _tab()
    if not _engine_available():
        pytest.skip("bedtools is not installed")
    first = _upload(tab, "query", QUERY)
    _upload(tab, "annot", ANNOT)
    executed = tab.post("/api/execute", json={})
    assert executed.status_code == 200, executed.text
    assert executed.json()["query_revision"] == first["revision"]

    second = _upload(tab, "query", QUERY)
    assert second["revision"] != first["revision"]

    response = tab.post(
        "/api/dataset/clear", json={"role": "query", "revision": second["revision"]}
    )
    assert response.status_code == 200
    # The result was derived from the first revision, not the cleared one.
    assert "result" in _session(tab).data


def _engine_available() -> bool:
    from streamlit_app.core.engine_registry import engine_available

    return engine_available("bedtools")


# ---------------------------------------------------------------------------
# Cross-tab cleanup (issue #51)
# ---------------------------------------------------------------------------


def test_cross_tab_cleanup_cannot_wipe_a_newer_dataset():
    tab_a = _tab()
    stale = _upload(tab_a, "query", QUERY)["revision"]  # the revision A owns

    tab_b = _second_tab_of(tab_a)
    newer = _upload(tab_b, "query", QUERY, ONE_BASED)  # a newer revision R2

    # A's unknown-outcome cleanup names the last revision it knows.
    response = tab_a.post(
        "/api/dataset/clear", json={"role": "query", "revision": stale}
    )
    assert response.status_code == 409, response.text
    assert _session(tab_a).data["query"]["rev"] == newer["revision"]

    # A client that knows no revision at all is refused rather than allowed to
    # fall back to deleting R2 (the pre-fix hole).
    raw = TestClient(app)
    raw.cookies.set(SESSION_COOKIE_NAME, tab_a.cookies.get(SESSION_COOKIE_NAME))
    response = raw.post("/api/dataset/clear", json={"role": "query"})
    assert response.status_code == 428, response.text
    assert _session(tab_a).data["query"]["rev"] == newer["revision"]


# ---------------------------------------------------------------------------
# Arrival-order high-water mark (issue #55)
# ---------------------------------------------------------------------------


def test_no_rejected_clear_advances_the_write_order_high_water_mark():
    tab = _tab()
    _upload(tab, "query", QUERY)
    session = _session(tab)
    high_water = dict(session.write_done)

    missing = _unknown_revision_tab(tab).post(
        "/api/dataset/clear", json={"role": "query"}
    )
    assert missing.status_code == 428
    assert _session(tab).write_done == high_water

    stale = _unknown_revision_tab(tab).post(
        "/api/dataset/clear", json={"role": "query", "revision": "not-the-stored-one"}
    )
    assert stale.status_code == 409
    assert _session(tab).write_done == high_water

    # The refused clears did not poison later writes: a fresh upload still
    # commits and advances the mark.
    reuploaded = _upload(tab, "query", QUERY)
    assert _session(tab).write_done["query"] > high_water.get("query", 0)

    # And the matching clear is the one that is allowed to commit.
    cleared = tab.post(
        "/api/dataset/clear",
        json={"role": "query", "revision": reuploaded["revision"]},
    )
    assert cleared.status_code == 200
    assert "query" not in _session(tab).data
