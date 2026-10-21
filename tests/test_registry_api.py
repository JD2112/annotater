"""Custom chromosome registries over HTTP (M2.2b).

The M2.2a lifecycle (budget, admission, write ordering, leases, expiry
cleanup) is exercised by ``tests/test_registry_lifecycle.py``; this module
exercises the *endpoint contract* built on top of it: the three
``/api/registry`` endpoints, the ``registry_rev`` binding of
``POST /api/execute``, the result provenance and the export consistency.

Everything is deterministic and small: the budget, the memory probe, the
loader and the clock are injected, the fixtures use tiny synthetic mappings
and the concurrency cases use barriers instead of real delays. No test
allocates a large registry, and no test waits for a real timeout.
"""

from __future__ import annotations

import hashlib
import threading
from types import SimpleNamespace

import anyio
import pytest
from fastapi.testclient import TestClient

from streamlit_app import api_registry, api_server
from streamlit_app.api_server import app
from streamlit_app.api_sessions import SESSION_COOKIE_NAME, SessionStore
from streamlit_app.core.chrom_registry import (
    RegistryBudget,
    RegistryBudgetConfig,
    RegistryLifecycle,
    load_custom_registry,
)
from streamlit_app.core.engine_registry import engine_available
from tests.revision_client import RevisionClient

MIB = 1024 * 1024
HEADER = b"assembly\tucsc\tensembl\tgenbank\trefseq\n"

#: One sequence, named in all five authorities.
MAPPING_ONE = (
    HEADER
    + b"1\tchr1\t1\tCM000001.1\tNC_000001.1\n"
)
#: Two sequences: a different mapping, so a different digest.
MAPPING_TWO = (
    HEADER
    + b"1\tchr1\t1\tCM000001.1\tNC_000001.1\n"
    + b"2\tchr2\t2\tCM000002.1\tNC_000002.1\n"
)

QUERY_BED = b"chr1\t100\t200\n"
ANNOT_BED = b"1\t100\t200\n"

QUERY_VCF = (
    b"##fileformat=VCFv4.2\n"
    b"##contig=<ID=1>\n"
    b'##INFO=<ID=DP,Number=.,Type=Integer,Description="read depth">\n'
    b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
    b"1\t100\tsnv1\tA\tT\t50\tPASS\tDP=10\n"
)


def digest_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def install_lifecycle(monkeypatch, *, loader=None, **budget_overrides):
    """Install a fresh store and a small-budget registry lifecycle.

    The budgets are deliberately tiny: one tiny mapping costs 2 MiB
    retained and 9 MiB transient with the approved estimator, so a few
    mappings exhaust the pool and the admission branches are reachable
    without allocating a large registry. The loader can be replaced to
    block a parse at a chosen point.
    """
    values = {
        "retained_bytes": 8 * MIB,
        "transient_bytes": 16 * MIB,
        "combined_bytes": 32 * MIB,
        "parse_concurrency": 1,
        "memory_headroom_reserve_bytes": 0,
    }
    values.update(budget_overrides)
    budget = RegistryBudget(
        RegistryBudgetConfig(**values), memory_headroom=lambda: None)
    lifecycle = RegistryLifecycle(
        budget,
        is_live=lambda token: api_server.store.contains(token),
        loader=loader or load_custom_registry,
    )
    store = SessionStore()
    store.set_on_evict(lifecycle.release_session)
    monkeypatch.setattr(api_server, "store", store)
    monkeypatch.setattr(api_server, "registry_lifecycle", lifecycle)
    return lifecycle


@pytest.fixture()
def lifecycle(monkeypatch):
    return install_lifecycle(monkeypatch)


@pytest.fixture()
def client():
    return TestClient(app)


def second_tab(client) -> TestClient:
    """Another tab of the same browser: the same cookie, its own state."""
    other = TestClient(app)
    token = client.cookies.get(SESSION_COOKIE_NAME)
    if token is not None:
        other.cookies.set(SESSION_COOKIE_NAME, token)
    return other


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def upload_mapping(client, content=MAPPING_ONE, name="mapping.tsv"):
    return client.post(
        "/api/registry", files={"file": (name, content, "text/plain")})


def registry_metadata(client):
    response = client.get("/api/registry")
    assert response.status_code == 200, response.text
    return response.json()["registry"]


def upload_dataset(client, role, content, name=None):
    name = name or ("query.bed" if role == "query" else "annot.bed")
    response = client.post(
        "/api/upload",
        files={"file": (name, content, "text/plain")},
        data={"role": role, "coord_system": "0-based"},
    )
    assert response.status_code == 200, response.text
    return response.json()["revision"]


def load_datasets(client, query=QUERY_BED, annot=ANNOT_BED):
    query_name = (
        "query.vcf" if query.startswith(b"##fileformat") else "query.bed")
    return (
        upload_dataset(client, "query", query, name=query_name),
        upload_dataset(client, "annot", annot),
    )


def run_execution(client, **overrides):
    body = {
        "engine": "bedtools",
        "mode": "overlap",
        "join": "left",
        "chr_naming": "ucsc",
    }
    body.update(overrides)
    return client.post("/api/execute", json=body)


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


class TestUpload:
    def test_valid_mapping_is_committed_with_its_metadata(
        self, lifecycle, client
    ):
        response = upload_mapping(client)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "success"
        assert body["reused"] is False
        registry = body["registry"]
        assert registry["source"] == "custom"
        assert registry["name"] == "Custom chromosome mapping"
        assert registry["row_count"] == 1
        assert registry["digest"] == digest_of(MAPPING_ONE)
        assert registry["revision"]
        # A custom mapping is a source of chromosome identity, not a genome
        # assembly: it never reports an assembly identity (SPEC 5.1.1 §7).
        assert registry["assembly"] is None

    def test_get_returns_the_same_metadata_without_the_content(
        self, lifecycle, client
    ):
        upload_mapping(client)
        registry = registry_metadata(client)
        assert registry["revision"]
        assert registry["digest"] == digest_of(MAPPING_ONE)
        assert registry["row_count"] == 1
        # The mapping content is never exposed.
        assert "CM000001.1" not in str(registry)
        assert "chr1" not in str(registry)

    def test_get_without_a_registry_is_empty_and_allocates_no_session(
        self, lifecycle, client
    ):
        response = client.get("/api/registry")
        assert response.status_code == 200
        assert response.json()["registry"] is None
        assert response.headers.get("set-cookie") is None
        assert len(api_server.store) == 0

    def test_upload_allocates_the_session(self, lifecycle, client):
        assert upload_mapping(client).status_code == 200
        assert len(api_server.store) == 1

    def test_invalid_mapping_is_rejected_with_its_issues(
        self, lifecycle, client
    ):
        response = upload_mapping(client, b"seq_id\tucsc\n1\tchr1\n")
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["code"] == "invalid_mapping"
        assert detail["issues"]
        assert detail["issues"][0]["code"] == "HEADER"
        assert detail["issues"][0]["rows"] == [1]
        # A refused upload stores nothing and allocates no session.
        assert len(api_server.store) == 0

    def test_ambiguous_alias_is_rejected(self, lifecycle, client):
        content = (
            HEADER
            + b"1\tchr1\t1\tCM000001.1\tNC_000001.1\n"
            + b"2\tchr1\t2\tCM000002.1\tNC_000002.1\n"
        )
        response = upload_mapping(client, content)
        assert response.status_code == 400
        issues = response.json()["detail"]["issues"]
        codes = {issue["code"] for issue in issues}
        assert "ALIAS_COLLISION" in codes

    def test_row_without_any_name_is_rejected(self, lifecycle, client):
        content = HEADER + b"1\tchr1\t1\tCM000001.1\tNC_000001.1\n\t\t\t\t\n"
        response = upload_mapping(client, content)
        assert response.status_code == 400
        issues = response.json()["detail"]["issues"]
        codes = {issue["code"] for issue in issues}
        assert "NO_ALIAS" in codes

    def test_same_digest_reuses_the_committed_revision(
        self, lifecycle, client
    ):
        first = upload_mapping(client).json()
        second = upload_mapping(client).json()
        assert second["reused"] is True
        assert second["registry"]["revision"] == first["registry"]["revision"]
        assert second["registry"]["digest"] == first["registry"]["digest"]
        # One registry is charged, not two.
        stats = lifecycle.stats()
        assert stats.retained_bytes == 2 * MIB
        assert stats.active_parses == 0

    def test_replacement_commits_a_new_revision(self, lifecycle, client):
        first = upload_mapping(client).json()["registry"]
        second = upload_mapping(client, MAPPING_TWO).json()["registry"]
        assert second["revision"] != first["revision"]
        assert second["digest"] != first["digest"]
        assert second["row_count"] == 2
        assert registry_metadata(client)["revision"] == second["revision"]
        # The replaced registry is retired: one registry stays charged.
        assert lifecycle.stats().retained_bytes == 2 * MIB


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_without_a_revision_is_refused(self, lifecycle, client):
        upload_mapping(client)
        response = client.delete("/api/registry")
        assert response.status_code == 428
        assert response.json()["detail"]["code"] == "revision_required"
        # Nothing was removed.
        assert registry_metadata(client) is not None

    def test_clear_with_a_stale_revision_is_refused(self, lifecycle, client):
        upload_mapping(client)
        upload_mapping(client, MAPPING_TWO)
        stale = "not-the-current-revision"
        response = client.delete(
            "/api/registry", params={"registry_rev": stale})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "revision_conflict"
        assert registry_metadata(client) is not None

    def test_clear_with_the_owned_revision_removes_the_registry(
        self, lifecycle, client
    ):
        revision = upload_mapping(client).json()["registry"]["revision"]
        response = client.delete(
            "/api/registry", params={"registry_rev": revision})
        assert response.status_code == 200
        assert response.json()["cleared"] is True
        assert registry_metadata(client) is None
        # The accounting is released with the registry.
        assert lifecycle.stats().retained_bytes == 0

    def test_clear_of_an_empty_registry_is_a_no_op(self, lifecycle, client):
        response = client.delete("/api/registry")
        assert response.status_code == 200
        assert response.json()["cleared"] is False
        # A no-op removal is not a write: it allocates no session.
        assert len(api_server.store) == 0

    def test_clear_invalidates_only_custom_results(self, lifecycle, client):
        query_rev, annot_rev = load_datasets(client)
        revision = upload_mapping(client).json()["registry"]["revision"]
        run = run_execution(
            client, query_rev=query_rev, annot_rev=annot_rev,
            registry_rev=revision)
        assert run.status_code == 200, run.text
        result_rev = run.json()["result_revision"]

        assert client.delete(
            "/api/registry", params={"registry_rev": revision}
        ).status_code == 200

        # The result derived from the discarded mapping is gone; asking for
        # it is a stale-result rejection, not a silent empty export.
        stale = client.get(
            "/api/results/data", params={"result_rev": result_rev})
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "revision_conflict"


# ---------------------------------------------------------------------------
# Admission (413 / 429 / 409)
# ---------------------------------------------------------------------------


class TestAdmission:
    def test_mapping_above_the_retained_budget_is_refused(
        self, monkeypatch, client
    ):
        install_lifecycle(monkeypatch, retained_bytes=1 * MIB)
        response = upload_mapping(client)
        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "registry_too_large"
        assert len(api_server.store) == 0

    def test_mapping_above_the_byte_limit_is_refused(
        self, monkeypatch, client
    ):
        install_lifecycle(monkeypatch)
        monkeypatch.setattr(api_registry, "DEFAULT_MAX_BYTES", 16)
        response = upload_mapping(client)
        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "registry_too_large"

    def test_mapping_above_the_row_limit_is_refused(self, monkeypatch, client):
        install_lifecycle(monkeypatch)
        monkeypatch.setattr(api_registry, "DEFAULT_MAX_ROWS", 1)
        response = upload_mapping(client, MAPPING_TWO)
        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "registry_too_large"

    def test_capacity_of_another_session_is_a_retryable_refusal(
        self, monkeypatch, client
    ):
        lifecycle = install_lifecycle(monkeypatch, retained_bytes=2 * MIB)
        assert upload_mapping(client).status_code == 200
        other = TestClient(app)
        response = upload_mapping(other)
        assert response.status_code == 429
        detail = response.json()["detail"]
        assert detail["code"] == "capacity_unavailable"
        assert response.headers["Retry-After"]
        # The other session's registry is untouched and nothing leaked.
        assert lifecycle.stats().retained_bytes == 2 * MIB
        assert lifecycle.stats().active_parses == 0

    def test_replacement_that_cannot_coexist_requires_a_clear(
        self, monkeypatch, client
    ):
        install_lifecycle(monkeypatch, retained_bytes=2 * MIB)
        first = upload_mapping(client).json()["registry"]
        response = upload_mapping(client, MAPPING_TWO)
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "replacement_requires_clear"
        # The old registry survives the refusal.
        assert registry_metadata(client)["revision"] == first["revision"]

    def test_busy_parse_slot_is_a_retryable_refusal(self, monkeypatch, client):
        started = threading.Event()
        release = threading.Event()

        def blocking_loader(content):
            started.set()
            release.wait(10)
            return load_custom_registry(content)

        lifecycle = install_lifecycle(monkeypatch, loader=blocking_loader)
        monkeypatch.setattr(api_registry, "PARSE_WAIT_SECONDS", 0.05)

        first = TestClient(app)
        outcome = {}

        def upload():
            outcome["response"] = upload_mapping(first)

        worker = threading.Thread(target=upload)
        worker.start()
        assert started.wait(10)

        other = TestClient(app)
        response = upload_mapping(other)
        assert response.status_code == 429
        detail = response.json()["detail"]
        assert detail["code"] == "parse_busy"
        assert response.headers["Retry-After"]

        release.set()
        worker.join(10)
        assert outcome["response"].status_code == 200
        # The refused parse left no reservation behind.
        assert lifecycle.stats().active_parses == 0
        assert lifecycle.stats().transient_parse_bytes == 0


# ---------------------------------------------------------------------------
# Session liveness and write ordering
# ---------------------------------------------------------------------------


class TestLiveness:
    def test_upload_after_the_session_expired_commits_nothing(
        self, monkeypatch, client
    ):
        started = threading.Event()
        release = threading.Event()

        def blocking_loader(content):
            started.set()
            release.wait(10)
            return load_custom_registry(content)

        lifecycle = install_lifecycle(monkeypatch, loader=blocking_loader)
        # A session that expires while the mapping is being parsed.
        store = _ExpiringStore(lifecycle)
        monkeypatch.setattr(api_server, "store", store)

        outcome = {}

        def upload():
            outcome["response"] = upload_mapping(client)

        worker = threading.Thread(target=upload)
        worker.start()
        assert started.wait(10)
        store.expire()
        release.set()
        worker.join(10)

        response = outcome["response"]
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "session_expired"
        # Nothing was committed and nothing leaked.
        assert lifecycle.current_revision("") is None
        assert lifecycle.stats().retained_bytes == 0
        assert lifecycle.stats().active_parses == 0
        assert lifecycle.stats().transient_parse_bytes == 0

    def test_clear_during_an_in_flight_upload_supersedes_it(
        self, monkeypatch, client
    ):
        started = threading.Event()
        release = threading.Event()

        def blocking_loader(content):
            started.set()
            release.wait(10)
            return load_custom_registry(content)

        lifecycle = install_lifecycle(monkeypatch, loader=blocking_loader)
        # The browser already owns a session, so the upload and the clear
        # address the same one.
        load_datasets(client)

        outcome = {}

        def upload():
            outcome["response"] = upload_mapping(client, MAPPING_TWO)

        worker = threading.Thread(target=upload)
        worker.start()
        assert started.wait(10)

        # The clear arrives while the upload is still parsing. Nothing is
        # stored yet, so it is a no-op -- but it leaves a tombstone.
        cleared = client.delete("/api/registry")
        assert cleared.status_code == 200
        assert cleared.json()["cleared"] is False

        release.set()
        worker.join(10)
        response = outcome["response"]
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "revision_conflict"
        # The superseded upload did not resurrect a registry.
        assert registry_metadata(client) is None
        assert lifecycle.stats().retained_bytes == 0


def _store_with_ttl(lifecycle, ttl_seconds: float) -> SessionStore:
    store = SessionStore(ttl_seconds=ttl_seconds)
    store.set_on_evict(lifecycle.release_session)
    return store


class _ExpiringStore(SessionStore):
    """A store whose sessions expire on demand, without a wall-clock wait."""

    def __init__(self, lifecycle):
        super().__init__()
        self.set_on_evict(lifecycle.release_session)
        self._expired = False

    def expire(self) -> None:
        self._expired = True

    def _is_expired(self, session, now) -> bool:
        return self._expired or super()._is_expired(session, now)


# ---------------------------------------------------------------------------
# Execution integration
# ---------------------------------------------------------------------------


class TestExecution:
    def test_custom_mapping_normalizes_the_annotation(self, lifecycle, client):
        query_rev, annot_rev = load_datasets(client)
        revision = upload_mapping(client).json()["registry"]["revision"]
        response = run_execution(
            client, query_rev=query_rev, annot_rev=annot_rev,
            registry_rev=revision)
        assert response.status_code == 200, response.text
        body = response.json()
        # The annotation table ("1") was normalized to the mapping's UCSC
        # name ("chr1") and therefore overlaps the query.
        assert body["stats"]["matched_count"] == 1
        assert body["preview"][0]["annot_chr"] == "chr1"

    def test_result_carries_the_custom_registry_provenance(
        self, lifecycle, client
    ):
        query_rev, annot_rev = load_datasets(client)
        registry = upload_mapping(client).json()["registry"]
        response = run_execution(
            client, query_rev=query_rev, annot_rev=annot_rev,
            registry_rev=registry["revision"])
        assert response.status_code == 200, response.text
        provenance = response.json()["registry"]
        assert provenance["source"] == "custom"
        assert provenance["revision"] == registry["revision"]
        assert provenance["digest"] == registry["digest"]
        assert provenance["name"] == "Custom chromosome mapping"
        assert provenance["row_count"] == 1
        assert provenance["assembly"] is None
        # The stored result carries the same provenance.
        stored = api_server.store.get(
            client.cookies.get(SESSION_COOKIE_NAME)).data["result"]
        assert stored["registry"]["revision"] == registry["revision"]
        # The normalization report names the custom mapping, not an assembly.
        report = response.json()["chromosome_normalization"]
        assert report["assembly"] is None
        assert report["registry_name"] == "Custom chromosome mapping"

    def test_bundled_assembly_keeps_its_canonical_provenance(
        self, lifecycle, client
    ):
        query_rev, annot_rev = load_datasets(client)
        response = run_execution(
            client, query_rev=query_rev, annot_rev=annot_rev, assembly="hg38")
        assert response.status_code == 200, response.text
        provenance = response.json()["registry"]
        assert provenance["source"] == "bundled"
        # The canonical assembly id is reported, whatever spelling the
        # client used (SPEC 5.1.1 item 14).
        assert provenance["assembly"] == "GRCh38"
        assert provenance["revision"] is None
        assert provenance["digest"] is None
        report = response.json()["chromosome_normalization"]
        assert report["assembly"] == "GRCh38"

    def test_keep_original_names_claims_no_registry(self, lifecycle, client):
        query_rev, annot_rev = load_datasets(client)
        # A custom mapping is loaded but not used by this run.
        upload_mapping(client)
        response = run_execution(
            client, query_rev=query_rev, annot_rev=annot_rev, chr_naming=None)
        assert response.status_code == 200, response.text
        provenance = response.json()["registry"]
        assert provenance["source"] == "none"
        assert provenance["revision"] is None
        assert provenance["name"] is None
        assert response.json()["chromosome_normalization"] is None

    def test_custom_and_bundled_sources_cannot_be_mixed(
        self, lifecycle, client
    ):
        query_rev, annot_rev = load_datasets(client)
        revision = upload_mapping(client).json()["registry"]["revision"]
        response = run_execution(
            client, query_rev=query_rev, annot_rev=annot_rev,
            registry_rev=revision, assembly="hg38")
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "registry_source_conflict"

    def test_a_run_that_keeps_the_names_uses_no_source_at_all(
        self, lifecycle, client
    ):
        query_rev, annot_rev = load_datasets(client)
        revision = upload_mapping(client).json()["registry"]["revision"]
        # Nothing is normalized, so there is no source to mix and no
        # registry to bind: the run keeps the names as provided.
        response = run_execution(
            client, query_rev=query_rev, annot_rev=annot_rev,
            chr_naming=None, registry_rev=revision, assembly="hg38")
        assert response.status_code == 200, response.text
        assert response.json()["registry"]["source"] == "none"

    def test_run_without_a_registry_revision_uses_the_bundled_assembly(
        self, lifecycle, client
    ):
        query_rev, annot_rev = load_datasets(client)
        upload_mapping(client)
        response = run_execution(
            client, query_rev=query_rev, annot_rev=annot_rev, assembly="hg38")
        assert response.status_code == 200, response.text
        assert response.json()["registry"]["source"] == "bundled"

    def test_run_with_a_stale_registry_revision_is_refused(
        self, lifecycle, client
    ):
        query_rev, annot_rev = load_datasets(client)
        first = upload_mapping(client).json()["registry"]["revision"]
        upload_mapping(client, MAPPING_TWO)
        response = run_execution(
            client, query_rev=query_rev, annot_rev=annot_rev,
            registry_rev=first)
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "revision_conflict"
        assert detail["stale"] == ["registry"]

    def test_run_without_any_custom_registry_is_refused(
        self, lifecycle, client
    ):
        query_rev, annot_rev = load_datasets(client)
        response = run_execution(
            client, query_rev=query_rev, annot_rev=annot_rev,
            registry_rev="there-is-no-such-registry")
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "revision_conflict"

    def test_replacement_during_the_run_discards_the_result(
        self, monkeypatch, client
    ):
        lifecycle = install_lifecycle(monkeypatch)
        query_rev, annot_rev = load_datasets(client)
        revision = upload_mapping(client).json()["registry"]["revision"]

        started = threading.Event()
        release = threading.Event()
        real_execute = api_server.execute_annotation_core

        def blocking_execute(request):
            started.set()
            assert release.wait(10)
            return real_execute(request)

        monkeypatch.setattr(
            api_server, "execute_annotation_core", blocking_execute)

        outcome = {}

        def run():
            outcome["response"] = run_execution(
                client, query_rev=query_rev, annot_rev=annot_rev,
                registry_rev=revision)

        worker = threading.Thread(target=run)
        worker.start()
        assert started.wait(10)

        # Another tab replaces the mapping while the run is executing.
        other = second_tab(client)
        replaced = upload_mapping(other, MAPPING_TWO)
        assert replaced.status_code == 200
        release.set()
        worker.join(10)

        response = outcome["response"]
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "revision_conflict"
        assert detail["stale"] == ["registry"]
        # No result was stored.
        session = api_server.store.get(client.cookies.get(SESSION_COOKIE_NAME))
        assert "result" not in session.data
        # The lease was released: only the current registry is charged.
        assert lifecycle.stats().retained_bytes == 2 * MIB
        assert lifecycle.stats().active_parses == 0

    @pytest.mark.parametrize("engine", ["bedtools", "polars-bio"])
    def test_both_engines_normalize_with_the_custom_mapping(
        self, lifecycle, client, engine
    ):
        if not engine_available(engine):
            pytest.skip(f"{engine} is not installed")
        query_rev, annot_rev = load_datasets(client)
        revision = upload_mapping(client).json()["registry"]["revision"]
        response = run_execution(
            client, query_rev=query_rev, annot_rev=annot_rev,
            registry_rev=revision, engine=engine)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["stats"]["engine"] == engine
        assert body["stats"]["matched_count"] == 1
        assert body["preview"][0]["annot_chr"] == "chr1"
        assert body["registry"]["source"] == "custom"


# ---------------------------------------------------------------------------
# Tabs and sessions
# ---------------------------------------------------------------------------


class TestTabsAndSessions:
    def test_a_stale_tab_cannot_run_with_an_old_registry_revision(
        self, lifecycle, client
    ):
        query_rev, annot_rev = load_datasets(client)
        first = upload_mapping(client).json()["registry"]
        tab = second_tab(client)
        # The other tab displays the first revision ...
        assert registry_metadata(tab)["revision"] == first["revision"]
        # ... and this tab replaces the mapping.
        second = upload_mapping(client, MAPPING_TWO).json()["registry"]
        assert second["revision"] != first["revision"]

        refused = run_execution(
            tab, query_rev=query_rev, annot_rev=annot_rev,
            registry_rev=first["revision"])
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "revision_conflict"

        accepted = run_execution(
            tab, query_rev=query_rev, annot_rev=annot_rev,
            registry_rev=second["revision"])
        assert accepted.status_code == 200, accepted.text

    def test_a_stale_tab_cannot_clear_a_replaced_registry(
        self, lifecycle, client
    ):
        first = upload_mapping(client).json()["registry"]
        tab = second_tab(client)
        upload_mapping(client, MAPPING_TWO)
        response = tab.delete(
            "/api/registry", params={"registry_rev": first["revision"]})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "revision_conflict"
        assert registry_metadata(client) is not None

    def test_a_registry_is_not_shared_between_sessions(
        self, lifecycle, client
    ):
        revision = upload_mapping(client).json()["registry"]["revision"]
        other = TestClient(app)
        assert registry_metadata(other) is None
        # Another session cannot run with this session's registry revision.
        query_rev, annot_rev = load_datasets(other)
        response = run_execution(
            other, query_rev=query_rev, annot_rev=annot_rev,
            registry_rev=revision)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "revision_conflict"

    def test_replacing_the_mapping_invalidates_the_previous_result(
        self, lifecycle, client
    ):
        query_rev, annot_rev = load_datasets(client)
        revision = upload_mapping(client).json()["registry"]["revision"]
        run = run_execution(
            client, query_rev=query_rev, annot_rev=annot_rev,
            registry_rev=revision)
        assert run.status_code == 200, run.text
        result_rev = run.json()["result_revision"]

        assert upload_mapping(client, MAPPING_TWO).status_code == 200
        stale = client.get(
            "/api/results/data", params={"result_rev": result_rev})
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "revision_conflict"

    def test_replacing_the_mapping_keeps_unrelated_results(
        self, lifecycle, client
    ):
        query_rev, annot_rev = load_datasets(client)
        run = run_execution(
            client, query_rev=query_rev, annot_rev=annot_rev, assembly="hg38")
        assert run.status_code == 200, run.text
        result_rev = run.json()["result_revision"]

        upload_mapping(client)
        kept = client.get(
            "/api/results/data", params={"result_rev": result_rev})
        assert kept.status_code == 200


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


class TestExports:
    def test_csv_tsv_and_vcf_exports_agree_with_the_custom_mapping(
        self, lifecycle, client
    ):
        query_rev, annot_rev = load_datasets(
            client, query=QUERY_VCF, annot=ANNOT_BED)
        revision = upload_mapping(client).json()["registry"]["revision"]
        run = run_execution(
            client, query_rev=query_rev, annot_rev=annot_rev,
            registry_rev=revision)
        assert run.status_code == 200, run.text
        result_rev = run.json()["result_revision"]

        csv = client.get("/api/export/csv", params={"result_rev": result_rev})
        assert csv.status_code == 200
        assert "chr1" in csv.text

        tsv = client.get("/api/export/tsv", params={"result_rev": result_rev})
        assert tsv.status_code == 200
        assert "chr1" in tsv.text

        vcf = client.get("/api/export/vcf", params={"result_rev": result_rev})
        assert vcf.status_code == 200
        # The contig declaration is normalized through the custom mapping,
        # exactly like a data row.
        assert "##contig=<ID=chr1>" in vcf.text
        data_lines = [
            line for line in vcf.text.splitlines()
            if line and not line.startswith("#")
        ]
        assert data_lines
        for line in data_lines:
            assert line.split("\t")[0] == "chr1"

    def test_export_of_a_superseded_result_is_refused(self, lifecycle, client):
        query_rev, annot_rev = load_datasets(client)
        revision = upload_mapping(client).json()["registry"]["revision"]
        run = run_execution(
            client, query_rev=query_rev, annot_rev=annot_rev,
            registry_rev=revision)
        assert run.status_code == 200, run.text
        result_rev = run.json()["result_revision"]
        upload_mapping(client, MAPPING_TWO)
        export = client.get(
            "/api/export/csv", params={"result_rev": result_rev})
        assert export.status_code == 409
        assert export.json()["detail"]["code"] == "revision_conflict"


# ---------------------------------------------------------------------------
# Accounting
# ---------------------------------------------------------------------------


class TestFrontendParity:
    """The tab model of the React frontend, exercised through the API.

    The frontend remembers the revision of the custom mapping it displays
    and echoes it on every run, exactly like it does for the dataset
    revisions. ``tests/revision_client.py`` mirrors that behaviour.
    """

    def test_a_tab_echoes_the_registry_revision_it_displays(self, lifecycle):
        tab = RevisionClient(app)
        query_rev, annot_rev = load_datasets(tab)
        response = tab.post(
            "/api/registry",
            files={"file": ("mapping.tsv", MAPPING_ONE, "text/plain")})
        assert response.status_code == 200, response.text
        revision = response.json()["registry"]["revision"]
        assert tab.revisions["registry"] == revision

        run = tab.post("/api/execute", json={
            "engine": "bedtools",
            "mode": "overlap",
            "join": "left",
            "chr_naming": "ucsc",
        })
        assert run.status_code == 200, run.text
        assert run.json()["registry"]["source"] == "custom"
        assert run.json()["registry"]["revision"] == revision

    def test_a_tab_drops_the_registry_revision_when_it_is_cleared(
        self, lifecycle
    ):
        tab = RevisionClient(app)
        response = tab.post(
            "/api/registry",
            files={"file": ("mapping.tsv", MAPPING_ONE, "text/plain")})
        revision = response.json()["registry"]["revision"]
        cleared = tab.delete(
            "/api/registry", params={"registry_rev": revision})
        assert cleared.status_code == 200, cleared.text
        assert "registry" not in tab.revisions


class TestAccounting:
    def test_a_refused_upload_leaks_no_accounting(self, monkeypatch, client):
        lifecycle = install_lifecycle(monkeypatch, retained_bytes=1 * MIB)
        assert upload_mapping(client).status_code == 413
        stats = lifecycle.stats()
        assert stats.retained_bytes == 0
        assert stats.reserved_retained_bytes == 0
        assert stats.transient_parse_bytes == 0
        assert stats.active_parses == 0

    def test_an_invalid_mapping_leaks_no_accounting(self, lifecycle, client):
        assert upload_mapping(client, b"nope\n").status_code == 400
        stats = lifecycle.stats()
        assert stats.retained_bytes == 0
        assert stats.transient_parse_bytes == 0
        assert stats.active_parses == 0

    def test_a_failed_run_releases_the_lease(self, monkeypatch, client):
        lifecycle = install_lifecycle(monkeypatch)
        query_rev, annot_rev = load_datasets(client)
        revision = upload_mapping(client).json()["registry"]["revision"]

        def failing_execute(request):
            raise api_server.AnnotationExecutionError(
                "engine exploded",
                engine_label="Bedtools", mode="overlap", join="left")

        monkeypatch.setattr(
            api_server, "execute_annotation_core", failing_execute)
        response = run_execution(
            client, query_rev=query_rev, annot_rev=annot_rev,
            registry_rev=revision)
        assert response.status_code == 500
        # The registry stays charged (it is still the session's registry) and
        # no lease keeps it alive beyond the run.
        assert lifecycle.stats().retained_bytes == 2 * MIB
        assert lifecycle.stats().active_parses == 0

    def test_session_eviction_releases_the_registry(self, monkeypatch, client):
        lifecycle = install_lifecycle(monkeypatch)
        upload_mapping(client)
        assert lifecycle.stats().retained_bytes == 2 * MIB
        token = client.cookies.get(SESSION_COOKIE_NAME)
        api_server.store.drop(token)
        assert lifecycle.stats().retained_bytes == 0

    def test_a_cancelled_upload_leaves_no_reservation_behind(
        self, monkeypatch
    ):
        started = threading.Event()
        release = threading.Event()

        def blocking_loader(content):
            started.set()
            release.wait(10)
            return load_custom_registry(content)

        lifecycle = install_lifecycle(monkeypatch, loader=blocking_loader)
        session = api_server.store.create()

        async def scenario():
            with anyio.move_on_after(0.05):
                await api_registry.upload_custom_registry(
                    _FakeRequest(),
                    _FakeUpload(MAPPING_ONE),
                    session,
                    lifecycle=lifecycle,
                    materialize=lambda request, current: current,
                    parse_limiter=lambda: anyio.CapacityLimiter(1),
                )

        # The parse is released while the request is being cancelled.
        timer = threading.Timer(0.2, release.set)
        timer.start()
        try:
            anyio.run(scenario)
        finally:
            timer.cancel()
            release.set()

        stats = lifecycle.stats()
        # No parse reservation and no transient charge survive the
        # cancellation: the accounting is exactly the committed registry.
        assert stats.active_parses == 0
        assert stats.transient_parse_bytes == 0
        assert stats.reserved_retained_bytes == 0
        assert stats.retained_bytes in (0, 2 * MIB)


class _FakeRequest:
    """The minimal request the registry upload needs."""

    def __init__(self):
        self.state = SimpleNamespace()


class _FakeUpload:
    """The minimal upload the registry upload needs."""

    def __init__(self, content: bytes):
        self._content = content

    async def read(self, size: int = -1) -> bytes:
        chunk, self._content = self._content, b""
        return chunk
