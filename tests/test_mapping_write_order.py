"""apply-mapping participates in arrival-order write ordering (issue #60).

PR #57 ordered upload, sample-load and clear writes per ``(session, role)`` by
request arrival (``reserve_write_order`` / ``write_order_superseded`` /
``record_write_committed`` in ``streamlit_app/api_sessions.py``). ``POST
/api/apply-mapping`` was left out of that contract: its commit did not advance
the ``query`` side's committed high-water mark, so an upload that *arrived
before* a mapping but finished parsing *after* it committed would silently
overwrite the mapped table.

A successful mapping is a write to the ``query`` side. These tests pin that it
now reserves a stamp before the (possibly slow) column mapping, refuses to
commit when a later-started write already committed, and advances the
high-water mark only on success. An earlier in-flight upload is then refused
with 409 instead of clobbering the mapped dataset.

The parked-parse / parked-normalization helpers block the synchronous half of
one request in a worker thread until the test releases it, so the interleaving
is deterministic rather than timing-dependent (the upload harness is the same
one used by ``tests/test_upload_event_loop.py``).
"""

from __future__ import annotations

import contextlib
import itertools
import threading

import pytest
from tests.revision_client import RevisionClient
from tests.test_upload_event_loop import _parking_parse

from streamlit_app import api_server
from streamlit_app.api_server import app
from streamlit_app.api_sessions import SESSION_COOKIE_NAME, SessionStore
from streamlit_app.core.engine_registry import engine_available

AUTO = "Auto-detect"
ONE_BASED = "1-based (GFF/GTF/VCF)"
ZERO_BASED = "0-based (BED)"

#: A delimited table that always needs explicit column mapping (parity with the
#: Streamlit custom-file path), so ``/api/apply-mapping`` is required.
CUSTOM_CSV = (
    b"Chromosome\tStart\tEnd\tgene\n"
    b"chr1\t100\t200\tg1\n"
)
ANNOT = b"chr1\t99\t100\tleft_edge_base100\n"
#: A plain BED query: parses without mapping, so it is the "earlier upload".
RACING_QUERY = b"chr1\t5000\t6000\tr2\n"

MAP_JSON = {
    "chr_col": "Chromosome",
    "start_col": "Start",
    "end_col": "End",
    "strand_col": None,
    "coord_system": AUTO,
}


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    monkeypatch.setattr(api_server, "store", SessionStore())


def _tab() -> RevisionClient:
    return RevisionClient(app)


def _second_tab_of(tab: RevisionClient) -> RevisionClient:
    other = RevisionClient(app)
    other.cookies.set(SESSION_COOKIE_NAME, tab.cookies.get(SESSION_COOKIE_NAME))
    other.revisions.update(tab.revisions)
    return other


def _session(tab: RevisionClient):
    return api_server.store.get(tab.cookies.get(SESSION_COOKIE_NAME))


def _upload(tab, role, content, coord_system=AUTO, name=None):
    name = name or ("regions.tsv" if role == "query" else "annot.bed")
    response = tab.post(
        "/api/upload",
        files={"file": (name, content, "text/plain")},
        data={"role": role, "coord_system": coord_system},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _custom_query(tab):
    uploaded = _upload(tab, "query", CUSTOM_CSV, name="q.csv")
    assert uploaded["needs_mapping"] is True
    return uploaded


def _mapping(tab, **overrides):
    body = dict(MAP_JSON)
    body.update(overrides)
    return tab.post("/api/apply-mapping", json=body)


@contextlib.contextmanager
def _parking_norm(monkeypatch, park_indices, watchdog_seconds=5.0):
    """Block the mapping's normalization half on given 1-based call numbers.

    ``/api/apply-mapping`` calls the module-level ``normalize_intervals``
    exactly once, at the end of its (possibly slow) work and before its
    commit. Parking it holds the request between reserving its arrival-order
    stamp and committing it. Yields ``(entered, release, watchdog_fired)``.
    """
    real = api_server.normalize_intervals
    entered = threading.Event()
    release = threading.Event()
    watchdog_fired = threading.Event()
    counter = itertools.count(1)
    lock = threading.Lock()
    parked = set(park_indices)

    def wrapped(*args, **kwargs):
        with lock:
            number = next(counter)
        if number in parked:
            entered.set()
            release.wait(timeout=watchdog_seconds * 2)
        return real(*args, **kwargs)

    monkeypatch.setattr(api_server, "normalize_intervals", wrapped)
    watchdog = threading.Timer(watchdog_seconds, lambda: (watchdog_fired.set(), release.set()))
    watchdog.start()
    try:
        yield entered, release, watchdog_fired
    finally:
        release.set()
        watchdog.cancel()


def _post_in_thread(target, sink):
    def run():
        sink.append(target())

    thread = threading.Thread(target=run)
    thread.start()
    return thread


# ---------------------------------------------------------------------------
# 1. Earlier slow upload followed by a successful mapping
# ---------------------------------------------------------------------------


def test_earlier_slow_upload_followed_by_successful_mapping_is_refused(monkeypatch):
    if not engine_available("bedtools"):
        pytest.skip("bedtools is not installed")

    tab_a = _tab()
    uploaded = _custom_query(tab_a)
    tab_b = _second_tab_of(tab_a)

    with _parking_parse(monkeypatch, park_indices={1}) as (entered, release, watchdog):
        earlier: list = []
        uploader = _post_in_thread(
            lambda: tab_a.post(
                "/api/upload",
                files={"file": ("earlier.bed", RACING_QUERY, "text/plain")},
                data={"role": "query", "coord_system": AUTO},
            ),
            earlier,
        )
        assert entered.wait(10.0), "the earlier upload never reached its parse"

        # The mapping starts after the upload, so it outranks it by arrival and
        # commits while the upload is still parsing.
        mapped = tab_b.post(
            "/api/apply-mapping",
            json=dict(MAP_JSON, query_rev=uploaded["revision"]),
        )
        assert mapped.status_code == 200, mapped.text
        mapped_rev = mapped.json()["revision"]

        release.set()
        uploader.join(10.0)

    assert not watchdog.is_set()
    # The upload arrived first but finishes last: it must not overwrite the
    # mapped table it knows nothing about.
    assert earlier and earlier[0].status_code == 409, earlier and earlier[0].text
    assert earlier[0].json()["detail"]["code"] == "revision_conflict"
    stored = _session(tab_a).data["query"]
    assert stored["rev"] == mapped_rev
    assert stored["needs_mapping"] is False


# ---------------------------------------------------------------------------
# 2. Mapping followed by a newer upload
# ---------------------------------------------------------------------------


def test_mapping_followed_by_a_newer_upload_is_refused(monkeypatch):
    tab_a = _tab()
    uploaded = _custom_query(tab_a)
    tab_b = _second_tab_of(tab_a)

    with _parking_norm(monkeypatch, park_indices={1}) as (entered, release, watchdog):
        mapping: list = []
        typist = _post_in_thread(
            lambda: tab_a.post(
                "/api/apply-mapping",
                json=dict(MAP_JSON, query_rev=uploaded["revision"]),
            ),
            mapping,
        )
        assert entered.wait(10.0), "the mapping never reached normalization"

        # A newer upload lands while the older mapping is still working; it
        # outranks the mapping by arrival.
        newer = _upload(tab_b, "query", RACING_QUERY, name="newer.bed")

        release.set()
        typist.join(10.0)

    assert not watchdog.is_set()
    assert mapping and mapping[0].status_code == 409, mapping and mapping[0].text
    assert mapping[0].json()["detail"]["code"] == "revision_conflict"
    stored = _session(tab_a).data["query"]
    assert stored["rev"] == newer["revision"]
    assert stored["filename"] == "newer.bed"


# ---------------------------------------------------------------------------
# 3. Two concurrent mappings
# ---------------------------------------------------------------------------


def test_two_concurrent_mappings_only_the_later_started_commits(monkeypatch):
    tab_a = _tab()
    uploaded = _custom_query(tab_a)
    tab_b = _second_tab_of(tab_a)

    with _parking_norm(monkeypatch, park_indices={1}) as (entered, release, watchdog):
        first: list = []
        first_thread = _post_in_thread(
            lambda: tab_a.post(
                "/api/apply-mapping",
                json=dict(MAP_JSON, query_rev=uploaded["revision"]),
            ),
            first,
        )
        assert entered.wait(10.0), "the first mapping never reached normalization"

        # The second mapping starts after the first: it outranks it and commits
        # while the first is still parked.
        second = tab_b.post(
            "/api/apply-mapping",
            json=dict(MAP_JSON, query_rev=uploaded["revision"]),
        )
        assert second.status_code == 200, second.text
        second_rev = second.json()["revision"]

        release.set()
        first_thread.join(10.0)

    assert not watchdog.is_set()
    assert first and first[0].status_code == 409, first and first[0].text
    assert first[0].json()["detail"]["code"] == "revision_conflict"
    assert _session(tab_a).data["query"]["rev"] == second_rev


# ---------------------------------------------------------------------------
# 4. Failed mapping followed by a legitimate upload
# ---------------------------------------------------------------------------


def test_failed_mapping_does_not_advance_the_mark_or_supersede_an_upload(monkeypatch):
    tab_a = _tab()
    _custom_query(tab_a)
    session = _session(tab_a)
    high_water_before = session.write_done.get("query", 0)

    # A mapping that reserves a stamp but fails during column mapping (before
    # normalization/commit) must leave the committed high-water mark untouched.
    failed = _mapping(tab_a, chr_col="NotAColumn")
    assert failed.status_code == 400, failed.text
    assert _session(tab_a).write_done.get("query", 0) == high_water_before

    # An upload that arrived *before* that failed mapping still commits: the
    # failed mapping did not reserve a committed position above it.
    with _parking_parse(monkeypatch, park_indices={1}) as (entered, release, watchdog):
        earlier: list = []
        uploader = _post_in_thread(
            lambda: tab_a.post(
                "/api/upload",
                files={"file": ("legit.bed", RACING_QUERY, "text/plain")},
                data={"role": "query", "coord_system": AUTO},
            ),
            earlier,
        )
        assert entered.wait(10.0)
        assert _mapping(tab_a, chr_col="NotAColumn").status_code == 400
        release.set()
        uploader.join(10.0)

    assert not watchdog.is_set()
    assert earlier and earlier[0].status_code == 200, earlier and earlier[0].text
    assert _session(tab_a).write_done["query"] > high_water_before


# ---------------------------------------------------------------------------
# 5. Mapping and clear racing
# ---------------------------------------------------------------------------


def test_clear_committed_while_mapping_runs_is_not_resurrected(monkeypatch):
    tab_a = _tab()
    uploaded = _custom_query(tab_a)
    tab_b = _second_tab_of(tab_a)

    with _parking_norm(monkeypatch, park_indices={1}) as (entered, release, watchdog):
        mapping: list = []
        typist = _post_in_thread(
            lambda: tab_a.post(
                "/api/apply-mapping",
                json=dict(MAP_JSON, query_rev=uploaded["revision"]),
            ),
            mapping,
        )
        assert entered.wait(10.0)

        cleared = tab_b.post(
            "/api/dataset/clear",
            json={"role": "query", "revision": uploaded["revision"]},
        )
        assert cleared.status_code == 200, cleared.text

        release.set()
        typist.join(10.0)

    assert not watchdog.is_set()
    assert mapping and mapping[0].status_code == 409, mapping and mapping[0].text
    assert mapping[0].json()["detail"]["code"] == "revision_conflict"
    assert "query" not in _session(tab_a).data


# ---------------------------------------------------------------------------
# 6. Independent annotation writes
# ---------------------------------------------------------------------------


def test_mapping_does_not_disturb_independent_annotation_writes(monkeypatch):
    tab_a = _tab()
    uploaded = _custom_query(tab_a)
    _upload(tab_a, "annot", ANNOT)
    tab_b = _second_tab_of(tab_a)

    with _parking_norm(monkeypatch, park_indices={1}) as (entered, release, watchdog):
        mapping: list = []
        typist = _post_in_thread(
            lambda: tab_a.post(
                "/api/apply-mapping",
                json=dict(MAP_JSON, query_rev=uploaded["revision"]),
            ),
            mapping,
        )
        assert entered.wait(10.0)

        # An annotation upload is an independent side; it must commit normally
        # and be untouched by the mapping's query-side ordering.
        new_annot = _upload(tab_b, "annot", RACING_QUERY, name="newer.bed")

        release.set()
        typist.join(10.0)

    assert not watchdog.is_set()
    assert mapping and mapping[0].status_code == 200, mapping and mapping[0].text
    session = _session(tab_a)
    assert session.data["query"]["rev"] == mapping[0].json()["revision"]
    assert session.data["annot"]["rev"] == new_annot["revision"]
    assert session.data["annot"]["filename"] == "newer.bed"


# ---------------------------------------------------------------------------
# 7. Coordinate semantics after a successful mapping
# ---------------------------------------------------------------------------


def test_coordinate_semantics_survive_a_successful_mapping():
    if not engine_available("bedtools"):
        pytest.skip("bedtools is not installed")

    # A 1-based mapping of [100, 200] becomes the canonical [99, 200), which
    # overlaps the annotation [99, 100): exactly one match.
    tab = _tab()
    uploaded = _custom_query(tab)
    _upload(tab, "annot", ANNOT)
    mapped = tab.post(
        "/api/apply-mapping",
        json=dict(MAP_JSON, coord_system=ONE_BASED, query_rev=uploaded["revision"]),
    )
    assert mapped.status_code == 200, mapped.text
    assert (mapped.json()["preview"][0]["start"], mapped.json()["preview"][0]["end"]) == (99, 200)
    executed = tab.post("/api/execute", json={})
    assert executed.status_code == 200, executed.text
    assert executed.json()["stats"]["matched_query_count"] == 1

    # The same file mapped 0-based stays [100, 200) and matches nothing: the
    # declared system, not the mapping ordering fix, decides the science.
    api_server.store = SessionStore()
    other = _tab()
    uploaded = _custom_query(other)
    _upload(other, "annot", ANNOT)
    mapped = other.post(
        "/api/apply-mapping",
        json=dict(MAP_JSON, coord_system=ZERO_BASED, query_rev=uploaded["revision"]),
    )
    assert mapped.status_code == 200, mapped.text
    assert (mapped.json()["preview"][0]["start"], mapped.json()["preview"][0]["end"]) == (100, 200)
    executed = other.post("/api/execute", json={})
    assert executed.status_code == 200, executed.text
    assert executed.json()["stats"]["matched_query_count"] == 0


# ---------------------------------------------------------------------------
# 8. No stale write can silently replace a newer committed dataset
# ---------------------------------------------------------------------------


def test_no_stale_write_silently_replaces_a_newer_committed_mapping(monkeypatch):
    if not engine_available("bedtools"):
        pytest.skip("bedtools is not installed")

    tab_a = _tab()
    uploaded = _custom_query(tab_a)
    tab_b = _second_tab_of(tab_a)

    with _parking_parse(monkeypatch, park_indices={1}) as (entered, release, watchdog):
        stale: list = []
        uploader = _post_in_thread(
            lambda: tab_a.post(
                "/api/upload",
                files={"file": ("stale.bed", b"chr1\t1\t2\n", "text/plain")},
                data={"role": "query", "coord_system": ZERO_BASED},
            ),
            stale,
        )
        assert entered.wait(10.0)

        # The mapping commits first, with a distinct scientific interval, and
        # records the committed high-water mark for the query side.
        mapped = tab_b.post(
            "/api/apply-mapping",
            json=dict(MAP_JSON, coord_system=ONE_BASED, query_rev=uploaded["revision"]),
        )
        assert mapped.status_code == 200, mapped.text
        mapped_rev = mapped.json()["revision"]
        committed = dict(_session(tab_a).write_done)

        release.set()
        uploader.join(10.0)

    assert not watchdog.is_set()
    assert stale and stale[0].status_code == 409, stale and stale[0].text
    stored = _session(tab_a).data["query"]
    assert stored["rev"] == mapped_rev
    # The stale upload's interval never appears; the mapped interval remains.
    assert stored["df"]["start"].tolist() == [99]
    assert stored["df"]["end"].tolist() == [200]
    # The refused upload advanced nothing.
    assert _session(tab_a).write_done == committed
