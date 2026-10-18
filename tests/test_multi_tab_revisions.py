"""Multi-tab scientific consistency (release-gate finding F1).

All tabs of one browser share the session cookie but keep their own UI
state. Before revisions, tab A could execute on tab B's datasets, and its
results/export reads served tab B's result, silently and scientifically
wrong (the gate reproduced an Auto-detect tab exporting a 1-based run).

Each test models tabs as :class:`RevisionClient` instances sharing one
cookie: they share server state but remember only the revisions their own
responses returned, exactly like the React frontend.

Fixture semantics make the applied coordinate convention visible: the query
``chr1 100 200`` overlaps the annotation ``chr1 [99,100)`` only when the
query is read 1-based (start 99), so 1 match = 1-based, 0 matches = 0-based.
"""

from __future__ import annotations

import threading

import pytest

from streamlit_app import api_server
from streamlit_app.api_server import app
from streamlit_app.api_sessions import SESSION_COOKIE_NAME, SessionStore
from streamlit_app.core.engine_registry import engine_available
from tests.revision_client import RevisionClient

ONE_BASED = "1-based (GFF/GTF/VCF)"
AUTO = "Auto-detect"
QUERY = b"chr1\t100\t200\tr1\n"
ANNOT = b"chr1\t99\t100\tleft_edge_base100\n"
ANNOT_OTHER = b"chr1\t5000\t6000\tfar\n"


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    monkeypatch.setattr(api_server, "store", SessionStore())


@pytest.fixture(autouse=True)
def _bedtools():
    if not engine_available("bedtools"):
        pytest.skip("bedtools is not installed")


def _tab():
    return RevisionClient(app)


def _second_tab_of(tab):
    """Another tab of the same browser: same cookie, its own UI state."""
    other = RevisionClient(app)
    other.cookies.set(SESSION_COOKIE_NAME, tab.cookies.get(SESSION_COOKIE_NAME))
    return other


def _upload(tab, role, content, coord_system=AUTO, name=None):
    name = name or ("regions.tsv" if role == "query" else "annot.bed")
    response = tab.post(
        "/api/upload",
        files={"file": (name, content, "text/plain")},
        data={"role": role, "coord_system": coord_system},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _try_upload(tab, role, content, coord_system=AUTO, name=None):
    """Upload that tolerates supersession (issue #55).

    Two tabs of one session uploading the same side at once is inherently
    conflicting; the server now keeps the later-started write and refuses the
    superseded one with 409. Returns the body on success, ``None`` when this
    upload was superseded by the other tab's newer write.
    """
    name = name or ("regions.tsv" if role == "query" else "annot.bed")
    response = tab.post(
        "/api/upload",
        files={"file": (name, content, "text/plain")},
        data={"role": role, "coord_system": coord_system},
    )
    if response.status_code == 409:
        assert response.json()["detail"]["code"] == "revision_conflict"
        return None
    assert response.status_code == 200, response.text
    return response.json()


def _load(tab, coord_system=AUTO, annot=ANNOT):
    _upload(tab, "annot", annot)
    return _upload(tab, "query", QUERY, coord_system)


def _try_load(tab, coord_system=AUTO, annot=ANNOT):
    """Like :func:`_load` but returns False when either side was superseded."""
    if _try_upload(tab, "annot", annot) is None:
        return False
    return _try_upload(tab, "query", QUERY, coord_system) is not None


def _run(tab, **body):
    return tab.post("/api/execute", json=body)


def _matched(response):
    assert response.status_code == 200, response.text
    return response.json()["stats"]["matched_query_count"]


def _conflict(response, *stale):
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "revision_conflict"
    assert sorted(detail["stale"]) == sorted(stale)
    assert "another tab" in detail["message"]
    return detail


# ---------------------------------------------------------------------------
# Revision issuance
# ---------------------------------------------------------------------------


def test_every_state_transition_returns_a_fresh_opaque_revision():
    tab = _tab()
    sample = tab.post("/api/load-sample", data={"sample_id": "gene_overlap"}).json()
    upload = _upload(tab, "query", QUERY)
    run = _run(tab).json()
    revisions = [
        sample["query"]["revision"], sample["annot"]["revision"],
        upload["revision"], run["result_revision"],
    ]
    assert len(set(revisions)) == len(revisions)
    token = tab.cookies.get(SESSION_COOKIE_NAME)
    for rev in revisions:
        assert len(rev) >= 22 and rev not in token
    # The execute response states exactly which dataset revisions it used.
    assert run["query_revision"] == upload["revision"]
    assert run["annot_revision"] == sample["annot"]["revision"]

    mapped_tab = _tab()
    custom = _upload(mapped_tab, "query", b"c,p\nchr1,100\n", name="q.csv")
    mapped = mapped_tab.post("/api/apply-mapping", json={
        "chr_col": "c", "start_col": "p", "end_col": None, "coord_system": AUTO,
    })
    assert mapped.status_code == 200, mapped.text
    assert mapped.json()["revision"] not in (custom["revision"], *revisions)


# ---------------------------------------------------------------------------
# Two tabs, one cookie
# ---------------------------------------------------------------------------


def test_two_tabs_loading_different_datasets_cannot_run_on_each_others_data():
    tab_a = _tab()
    _load(tab_a, AUTO)
    tab_b = _second_tab_of(tab_a)
    _load(tab_b, ONE_BASED, annot=ANNOT_OTHER)

    # Tab A still displays its own Auto-detect query + annotation; the
    # session now holds tab B's. Running must refuse, not use B's data.
    _conflict(_run(tab_a), "query", "annot")
    assert "result" not in api_server.store.get(tab_a.cookies.get(SESSION_COOKIE_NAME)).data
    # Tab B runs on exactly what it displays.
    assert _matched(_run(tab_b)) == 0  # ANNOT_OTHER is far away


def test_tab_a_execution_after_tab_b_changes_one_dataset():
    tab_a = _tab()
    _load(tab_a, AUTO)
    assert _matched(_run(tab_a)) == 0  # Auto-detect -> 0-based -> no match
    tab_b = _second_tab_of(tab_a)
    _upload(tab_b, "query", QUERY, ONE_BASED)

    # The gate's re-run case: A's UI is unchanged; previously this ran on
    # B's 1-based query and reported 1 of 1 matched.
    _conflict(_run(tab_a), "query")
    # A's own previous result was not replaced and is still served to A.
    assert tab_a.get("/api/export/csv").status_code == 200


def test_tab_a_export_after_tab_b_executes_is_a_conflict_not_tab_bs_result():
    tab_a = _tab()
    _load(tab_a, AUTO)
    assert _matched(_run(tab_a)) == 0
    a_csv = tab_a.get("/api/export/csv")
    assert a_csv.status_code == 200
    assert "left_edge_base100" not in a_csv.text  # A's run matched nothing

    tab_b = _second_tab_of(tab_a)
    _load(tab_b, ONE_BASED)
    assert _matched(_run(tab_b)) == 1
    b_csv = tab_b.get("/api/export/csv")
    assert "left_edge_base100" in b_csv.text

    # The gate's export case: A still shows "0 of 1 matched"; its Export
    # used to download B's 1-based result. Every format now refuses.
    for fmt in ("csv", "tsv", "xlsx"):
        response = tab_a.get(f"/api/export/{fmt}")
        _conflict(response, "result")
        assert "left_edge_base100" not in response.text
    assert tab_a.get("/api/export/vcf").status_code == 409


def test_tab_a_pagination_and_gene_list_after_tab_b_executes():
    tab_a = _tab()
    tab_a.post("/api/load-sample", data={"sample_id": "gene_overlap"})
    assert _run(tab_a).status_code == 200
    assert tab_a.get("/api/results/data", params={"page": 1, "page_size": 2}).status_code == 200
    assert tab_a.get("/api/results/gene-list").status_code == 200

    tab_b = _second_tab_of(tab_a)
    tab_b.post("/api/load-sample", data={"sample_id": "closest_variants"})
    assert _run(tab_b, mode="closest").status_code == 200

    for params in ({}, {"page": 2, "page_size": 1}, {"filter_type": "matched"},
                   {"filter_type": "unmatched"}):
        _conflict(tab_a.get("/api/results/data", params=params), "result")
    _conflict(tab_a.get("/api/results/gene-list"), "result")
    # B reads its own result.
    assert tab_b.get("/api/results/data").status_code == 200
    assert tab_b.get("/api/results/gene-list").status_code == 200


def test_mapping_and_clear_from_a_stale_tab_do_not_touch_the_other_tabs_query():
    tab_a = _tab()
    _upload(tab_a, "query", b"c,p\nchr1,100\n", name="q.csv")
    tab_b = _second_tab_of(tab_a)
    b_query = _upload(tab_b, "query", QUERY, ONE_BASED)

    mapping = tab_a.post("/api/apply-mapping", json={
        "chr_col": "c", "start_col": "p", "end_col": None, "coord_system": AUTO,
    })
    _conflict(mapping, "query")
    stale_clear = tab_a.post("/api/dataset/clear", json={
        "role": "query", "revision": tab_a.revisions["query"],
    })
    _conflict(stale_clear, "query")
    stored = api_server.store.get(tab_b.cookies.get(SESSION_COOKIE_NAME)).data["query"]
    assert stored["rev"] == b_query["revision"]
    assert stored["filename"] == "regions.tsv"


# ---------------------------------------------------------------------------
# Missing / invalid / expired revisions fail safely
# ---------------------------------------------------------------------------


def test_missing_invalid_and_expired_revisions_never_fall_back():
    tab = _tab()
    _load(tab, ONE_BASED)
    assert _run(tab).status_code == 200
    query_rev, annot_rev = tab.revisions["query"], tab.revisions["annot"]
    result_rev = tab.revisions["result"]
    raw = _second_tab_of(tab)  # same cookie, knows no revisions

    # Missing: state exists but the request does not say which -> 428.
    assert raw.post("/api/execute", json={}).status_code == 428
    assert raw.post("/api/execute", json={"query_rev": query_rev}).status_code == 428
    for path in ("/api/results/data", "/api/results/gene-list", "/api/export/csv"):
        assert raw.get(path).status_code == 428

    # Invalid (guessed / malformed) -> 409; over-long -> 422.
    _conflict(raw.post("/api/execute", json={"query_rev": "x", "annot_rev": annot_rev}), "query")
    for path in ("/api/results/data", "/api/results/gene-list", "/api/export/csv"):
        _conflict(raw.get(path, params={"result_rev": "not-a-revision"}), "result")
        assert raw.get(path, params={"result_rev": "x" * 65}).status_code == 422

    # The correct revisions still work, from any tab of this session.
    assert raw.get("/api/export/csv", params={"result_rev": result_rev}).status_code == 200

    # Expired session: the revisions no longer name anything -> 409 for
    # claims, never another session's or an empty "success".
    api_server.store = SessionStore()
    fresh = _second_tab_of(tab)
    fresh.revisions.update(tab.revisions)
    _conflict(_run(fresh), "query", "annot")
    _conflict(fresh.get("/api/export/csv"), "result")


def test_clear_drops_only_a_result_derived_from_the_cleared_dataset():
    tab = _tab()
    _load(tab, AUTO)
    assert _run(tab).status_code == 200
    rev = tab.revisions["result"]
    assert tab.post("/api/dataset/clear", json={"role": "query"}).status_code == 200
    # The result derived from the cleared query is gone; a tab still
    # displaying it gets a conflict, not some other result.
    _conflict(tab.get("/api/export/csv", params={"result_rev": rev}), "result")


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_dataset_replaced_while_execute_runs_discards_the_result(monkeypatch):
    tab_a = _tab()
    _load(tab_a, AUTO)
    tab_b = _second_tab_of(tab_a)
    real = api_server.execute_annotation_core

    def racing(request):
        _upload(tab_b, "query", QUERY, ONE_BASED)  # lands mid-run
        return real(request)

    monkeypatch.setattr(api_server, "execute_annotation_core", racing)
    _conflict(_run(tab_a), "query")
    monkeypatch.setattr(api_server, "execute_annotation_core", real)
    # The run's result was not stored for anyone to read.
    assert "result" not in api_server.store.get(tab_a.cookies.get(SESSION_COOKIE_NAME)).data


def test_dataset_cleared_while_execute_runs_discards_the_result(monkeypatch):
    tab_a = _tab()
    _load(tab_a, AUTO)
    tab_b = _second_tab_of(tab_a)
    real = api_server.execute_annotation_core

    def racing(request):
        tab_b.post("/api/dataset/clear", json={"role": "annot"})
        return real(request)

    monkeypatch.setattr(api_server, "execute_annotation_core", racing)
    _conflict(_run(tab_a), "annot")


def test_concurrent_tabs_never_read_or_export_each_others_results():
    """Two tabs hammering one session from threads.

    Invariant: every successful execute used exactly the revisions its tab
    sent, and every successful export carries that tab's own scientific
    signal (1-based tab -> match row present, Auto tab -> absent). Any
    other outcome must be an explicit 409.
    """
    tab_a = _tab()
    _load(tab_a, AUTO)
    tab_b = _second_tab_of(tab_a)
    failures = []
    completed = []
    lock = threading.Lock()

    def worker(tab, coord_system, expect_match):
        for _ in range(8):
            # The other tab may supersede one of this tab's uploads (409);
            # skip that iteration -- it carries no scientific claim.
            if not _try_load(tab, coord_system):
                continue
            with lock:
                completed.append(1)
            sent = (tab.revisions["query"], tab.revisions["annot"])
            run = _run(tab)
            if run.status_code == 409:
                continue
            if run.status_code != 200:
                failures.append(("execute", run.status_code, run.text))
                continue
            body = run.json()
            if (body["query_revision"], body["annot_revision"]) != sent:
                failures.append(("wrong datasets", body["query_revision"], sent))
            if (body["stats"]["matched_query_count"] == 1) != expect_match:
                failures.append(("wrong science", coord_system, body["stats"]))
            export = tab.get("/api/export/csv")
            if export.status_code == 409:
                continue
            if export.status_code != 200 or ("left_edge_base100" in export.text) != expect_match:
                failures.append(("wrong export", coord_system, export.status_code))

    threads = [
        threading.Thread(target=worker, args=(tab_a, AUTO, False)),
        threading.Thread(target=worker, args=(tab_b, ONE_BASED, True)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert failures == []
    # Supersession must not have swallowed the whole workload: the test only
    # means something if a good number of uploads/executes actually ran.
    assert len(completed) >= 4, f"only {len(completed)} iterations survived supersession"


# ---------------------------------------------------------------------------
# Recovery and isolation
# ---------------------------------------------------------------------------


def test_reupload_after_conflict_restores_a_consistent_tab():
    tab_a = _tab()
    _load(tab_a, AUTO)
    tab_b = _second_tab_of(tab_a)
    _load(tab_b, ONE_BASED)
    _conflict(_run(tab_a), "query", "annot")

    # Tab A explicitly reloads its own data: now it runs on exactly that.
    _load(tab_a, AUTO)
    assert _matched(_run(tab_a)) == 0
    assert "left_edge_base100" not in tab_a.get("/api/export/csv").text
    # ...and it is tab B that is now told its view is stale.
    _conflict(_run(tab_b), "query", "annot")


def test_independent_sessions_stay_isolated_even_with_known_revisions():
    owner = _tab()
    _load(owner, ONE_BASED)
    assert _run(owner).status_code == 200
    owner_csv = owner.get("/api/export/csv").text

    stranger = _tab()  # a different browser: its own cookie
    stranger.revisions.update(owner.revisions)  # even knowing every revision
    _conflict(_run(stranger), "query", "annot")
    response = stranger.get("/api/export/csv")
    assert response.status_code == 409
    assert "left_edge_base100" not in response.text
    assert stranger.cookies.get(SESSION_COOKIE_NAME) is None

    # The stranger's own work never disturbs the owner's.
    _load(stranger, AUTO)
    assert _run(stranger).status_code == 200
    assert owner.get("/api/export/csv").text == owner_csv
