"""Upload parsing runs off the event loop (issue #55, M1.1 hardening).

The bundled ``start-script.sh`` runs a single Uvicorn worker, so the FastAPI
event loop is the only request loop the process has. Format detection,
parsing and normalization are CPU-bound and can take seconds on a large
upload; running them inside the ``upload_file`` coroutine would freeze the
loop for that whole time, stalling every other session's request and the
container ``/health`` probe (the compose/Docker healthcheck and the
deployment readiness probe both call it).

These tests pin the fix and the contract it must not disturb:

1. the loop keeps serving ``/health`` while an upload parses (a worker
   thread runs the parse);
2. a second session is served while the first session's upload parses;
3. two concurrent uploads in independent sessions never crosstalk;
4. upload validation/error contracts stay prompt under that concurrency;
5. a mix of successful and failing uploads leaves no temp dirs behind;
6. a clear racing an in-flight upload never leaves a torn dataset/revision
   and never lets a tab act on a revision a concurrent write replaced.

The parked-parse helper swaps the module-level
:func:`streamlit_app.api_server._detect_parse_and_normalize` for a wrapper
that blocks in a worker thread until the test releases it. A watchdog timer
releases it if the test itself misbehaves (so a regression fails rather than
hangs) and records that it had to -- which is exactly how a fixed-vs-broken
event loop is told apart.
"""

from __future__ import annotations

import contextlib
import itertools
import tempfile
import threading
from pathlib import Path

import anyio
import httpx
import pytest

from streamlit_app import api_server
from streamlit_app.api_server import app
from streamlit_app.api_sessions import SESSION_COOKIE_NAME, SessionStore
from streamlit_app.core.engine_registry import engine_available
from tests.revision_client import RevisionClient

QUERY = b"chr1\t10\t20\n"
ANNOT = b"chr1\t99\t100\n"
REPLACEMENT = b"chr1\t100\t200\tr2\n"
INVALID = b"chr1\tnotnum\t20\n"


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    monkeypatch.setattr(api_server, "store", SessionStore())


@contextlib.contextmanager
def _parking_parse(monkeypatch, park_indices, watchdog_seconds=5.0):
    """Block the sync parse half on the given 1-based call numbers.

    Yields ``(entered, release, watchdog_fired)``. ``entered`` is set when a
    parked call is reached; ``release`` unblocks every parked call; and
    ``watchdog_fired`` is set only if the watchdog had to release them,
    i.e. the caller failed to free the loop in time.
    """
    real = api_server._detect_parse_and_normalize
    entered = threading.Event()
    release = threading.Event()
    watchdog_fired = threading.Event()
    counter = itertools.count(1)
    lock = threading.Lock()
    parked = set(park_indices)

    def wrapped(temp_path, role, declared):
        with lock:
            number = next(counter)
        if number in parked:
            entered.set()
            release.wait(timeout=watchdog_seconds * 2)
        return real(temp_path, role, declared)

    monkeypatch.setattr(api_server, "_detect_parse_and_normalize", wrapped)
    watchdog = threading.Timer(watchdog_seconds, lambda: (watchdog_fired.set(), release.set()))
    watchdog.start()
    try:
        yield entered, release, watchdog_fired
    finally:
        release.set()
        watchdog.cancel()


def _upload_kwargs(content, role="query", name="q.bed"):
    return {
        "files": {"file": (name, content, "text/plain")},
        "data": {"role": role},
    }


# ---------------------------------------------------------------------------
# 1: the loop is not blocked while an upload parses
# ---------------------------------------------------------------------------


def test_upload_parse_does_not_block_the_event_loop(monkeypatch):
    with _parking_parse(monkeypatch, park_indices={1}) as (entered, release, watchdog_fired):
        outcome: dict = {}

        async def scenario():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                uploads: list = []

                async def upload():
                    uploads.append(
                        await client.post(
                            "/api/upload", timeout=30.0, **_upload_kwargs(QUERY)
                        )
                    )

                async with anyio.create_task_group() as tg:
                    tg.start_soon(upload)
                    # Park is reached off the loop; wait for it without blocking it.
                    assert await anyio.to_thread.run_sync(entered.wait, 10.0)
                    # The loop must still answer while the parse is parked.
                    outcome["health"] = await client.get("/health", timeout=2.0)
                    outcome["served_before_release"] = not watchdog_fired.is_set()
                    release.set()
                outcome["upload"] = uploads[0]

        anyio.run(scenario)

        assert outcome["health"].status_code == 200
        assert outcome["served_before_release"], (
            "the event loop was blocked while the upload parsed: /health was "
            "only served after the parse watchdog fired"
        )
        assert not watchdog_fired.is_set()
        assert outcome["upload"].status_code == 200


# ---------------------------------------------------------------------------
# 2: a second session is served while the first parses
# ---------------------------------------------------------------------------


def test_second_session_is_served_while_first_upload_parses(monkeypatch):
    with _parking_parse(monkeypatch, park_indices={1}) as (entered, release, watchdog_fired):
        outcome: dict = {}

        async def scenario():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                first: list = []

                async def upload_first():
                    first.append(
                        await client.post(
                            "/api/upload", timeout=30.0, **_upload_kwargs(QUERY, name="a.bed")
                        )
                    )

                async with anyio.create_task_group() as tg:
                    tg.start_soon(upload_first)
                    assert await anyio.to_thread.run_sync(entered.wait, 10.0)
                    # A different browser: no cookie was issued yet (the first
                    # upload has not returned), so this is its own session.
                    outcome["second"] = await client.post(
                        "/api/upload", timeout=5.0, **_upload_kwargs(b"chr2\t5\t9\n", name="b.bed")
                    )
                    outcome["served_before_release"] = not watchdog_fired.is_set()
                    release.set()
                outcome["first"] = first[0]

        anyio.run(scenario)

        assert outcome["served_before_release"], (
            "a second session's upload was stalled behind the first session's parse"
        )
        assert outcome["second"].status_code == 200
        assert outcome["first"].status_code == 200
        assert outcome["second"].json()["revision"] != outcome["first"].json()["revision"]
        # Two independent sessions, each holding its own dataset.
        assert len(api_server.store) == 2


# ---------------------------------------------------------------------------
# 4: error contracts stay prompt under concurrency
# ---------------------------------------------------------------------------


def test_upload_errors_are_prompt_while_another_parse_is_parked(monkeypatch):
    with _parking_parse(monkeypatch, park_indices={1}) as (entered, release, watchdog_fired):
        outcome: dict = {}

        async def scenario():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                parked: list = []

                async def upload_ok():
                    parked.append(
                        await client.post(
                            "/api/upload", timeout=30.0, **_upload_kwargs(QUERY)
                        )
                    )

                async with anyio.create_task_group() as tg:
                    tg.start_soon(upload_ok)
                    assert await anyio.to_thread.run_sync(entered.wait, 10.0)
                    invalid = await client.post(
                        "/api/upload", timeout=5.0, **_upload_kwargs(INVALID, name="bad.bed")
                    )
                    bad_role = await client.post(
                        "/api/upload", timeout=5.0, **_upload_kwargs(QUERY, role="nope")
                    )
                    outcome["invalid_status"] = invalid.status_code
                    outcome["bad_role_status"] = bad_role.status_code
                    outcome["prompt"] = not watchdog_fired.is_set()
                    release.set()
                outcome["ok"] = parked[0]

        anyio.run(scenario)

        assert outcome["prompt"], "error responses waited for the concurrent parse"
        assert outcome["invalid_status"] == 400
        assert outcome["bad_role_status"] == 400
        assert outcome["ok"].status_code == 200


# ---------------------------------------------------------------------------
# 3: concurrent uploads in independent sessions do not crosstalk
# ---------------------------------------------------------------------------


def test_concurrent_uploads_in_independent_sessions_do_not_crosstalk():
    statuses: list[int] = []
    tokens: dict[str, str] = {}

    def worker(chrom: str):
        client = RevisionClient(app)
        for _ in range(6):
            response = client.post(
                "/api/upload",
                files={"file": ("q.bed", f"{chrom}\t10\t20\n".encode(), "text/plain")},
                data={"role": "query"},
            )
            statuses.append(response.status_code)
        tokens[chrom] = client.cookies.get(SESSION_COOKIE_NAME)

    threads = [
        threading.Thread(target=worker, args=("chrA",)),
        threading.Thread(target=worker, args=("chrB",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert statuses == [200] * 12
    assert len(api_server.store) == 2
    for chrom in ("chrA", "chrB"):
        entry = api_server.store.get(tokens[chrom]).data["query"]
        assert set(entry["df"]["chr"]) == {chrom}


# ---------------------------------------------------------------------------
# 5: temp-file lifecycle under concurrent success and failure
# ---------------------------------------------------------------------------


def _leftover_upload_dirs() -> set[str]:
    return {path.name for path in Path(tempfile.gettempdir()).glob("annotater-upload-*")}


def test_concurrent_success_and_failure_leave_no_temp_dirs():
    before = _leftover_upload_dirs()

    def good():
        RevisionClient(app).post(
            "/api/upload",
            files={"file": ("q.bed", QUERY, "text/plain")},
            data={"role": "query"},
        )

    def bad():
        RevisionClient(app).post(
            "/api/upload",
            files={"file": ("bad.bed", INVALID, "text/plain")},
            data={"role": "query"},
        )

    threads = [threading.Thread(target=good) for _ in range(4)]
    threads += [threading.Thread(target=bad) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert _leftover_upload_dirs() == before


# ---------------------------------------------------------------------------
# 6: a clear racing an in-flight upload leaves no mismatched state
# ---------------------------------------------------------------------------


def test_clear_racing_an_upload_never_leaves_mismatched_state(monkeypatch):
    if not engine_available("bedtools"):
        pytest.skip("bedtools is not installed")

    tab_a = RevisionClient(app)
    assert tab_a.post(
        "/api/upload", files={"file": ("a.bed", ANNOT, "text/plain")}, data={"role": "annot"}
    ).status_code == 200
    assert tab_a.post(
        "/api/upload", files={"file": ("q.bed", QUERY, "text/plain")}, data={"role": "query"}
    ).status_code == 200

    tab_b = RevisionClient(app)
    tab_b.cookies.set(SESSION_COOKIE_NAME, tab_a.cookies.get(SESSION_COOKIE_NAME))
    tab_b.revisions.update(tab_a.revisions)
    stale_query_rev = tab_a.revisions["query"]

    # The two setup uploads above ran before the patch, so A's replacement is
    # the first parse the wrapper sees.
    with _parking_parse(monkeypatch, park_indices={1}) as (entered, release, watchdog_fired):
        replaced: list = []
        uploader = threading.Thread(
            target=lambda: replaced.append(
                tab_a.post(
                    "/api/upload",
                    files={"file": ("q2.bed", REPLACEMENT, "text/plain")},
                    data={"role": "query"},
                )
            )
        )
        uploader.start()
        assert entered.wait(10.0)
        # Another tab of the same browser clears the query while A's
        # replacement is mid-parse.
        cleared = tab_b.post(
            "/api/dataset/clear", json={"role": "query", "revision": stale_query_rev}
        )
        assert cleared.status_code == 200, cleared.text
        release.set()
        uploader.join(10.0)

    assert not watchdog_fired.is_set()
    assert replaced and replaced[0].status_code == 200
    new_rev = replaced[0].json()["revision"]

    token = tab_b.cookies.get(SESSION_COOKIE_NAME)
    entry = api_server.store.get(token).data["query"]
    # The dataset and its revision were published together (no torn state),
    # and the late commit carries a revision distinct from the cleared one.
    assert entry["rev"] == new_rev
    assert new_rev != stale_query_rev
    assert [row["start"] for row in entry["df"].to_dict("records")] == [100]

    # A tab still displaying the revision a concurrent write replaced cannot
    # act on the state that now exists: it is refused, never silently served.
    tab_b.revisions["query"] = stale_query_rev
    run = tab_b.post("/api/execute", json={})
    assert run.status_code == 409, run.text
    detail = run.json()["detail"]
    assert detail["code"] == "revision_conflict"
    assert "query" in detail["stale"]
