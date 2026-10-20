"""Custom-registry resource accounting and session lifecycle (M2.2a).

These tests exercise the internal foundation only: no HTTP endpoint and no
frontend contract is involved. Budgets, memory probes, clocks and registry
loaders are injected, so the tests are deterministic and allocate only tiny
registries. The fixtures pin:

* the conservative row/byte estimator and the retained/transient/combined
  boundary decisions (413 vs 429);
* serialised parse-slot contention with a bounded wait and Retry-After;
* digest idempotency, replacement, clear, expiry/LRU eviction and tombstones;
* arrival-order registry writes, including stale in-flight writes;
* lease-protected retirement and idempotent release on every failure path.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from streamlit_app.api_sessions import SessionStore
from streamlit_app.core.chrom_registry import (
    DEFAULT_COMBINED_BYTES,
    DEFAULT_RETAINED_BYTES,
    DEFAULT_TRANSIENT_PARSE_BYTES,
    RegistryAdmissionError,
    RegistryBudget,
    RegistryBudgetConfig,
    RegistryEstimate,
    RegistryLifecycle,
    RegistryNotAvailable,
    RegistrySessionExpired,
    RegistryWriteConflict,
    cgroup_v2_headroom,
    count_custom_mapping_rows,
    estimate_registry,
    load_custom_registry,
)
from streamlit_app.core.chrom_registry.lifecycle import (
    PARSE_BASE_BYTES,
    PARSE_BYTES_PER_ROW,
    PARSE_INPUT_MULTIPLIER,
    RETAINED_BASE_BYTES,
    RETAINED_BYTES_PER_ROW,
)

MIB = 1024 * 1024
HEADER = b"assembly\tucsc\tensembl\tgenbank\trefseq\n"


def mapping(*rows: tuple[str, str, str, str, str]) -> bytes:
    body = [b"\t".join(cell.encode() for cell in row) for row in rows]
    return HEADER + b"\n".join(body) + (b"\n" if body else b"")


CONTENT_A = mapping(("1", "chr1", "1", "CM000001.1", "NC_000001.1"))
CONTENT_B = mapping(
    ("1", "chr1", "1", "CM000001.1", "NC_000001.1"),
    ("2", "chr2", "2", "CM000002.1", "NC_000002.1"),
)
CONTENT_C = mapping(("3", "chr3", "3", "CM000003.1", "NC_000003.1"))


def make_budget(**overrides) -> RegistryBudget:
    values = {
        "retained_bytes": 8 * MIB,
        "transient_bytes": 8 * MIB,
        "combined_bytes": 16 * MIB,
        "parse_concurrency": 1,
        "memory_headroom_reserve_bytes": 0,
    }
    values.update(overrides)
    return RegistryBudget(
        RegistryBudgetConfig(**values), memory_headroom=lambda: None)


def make_lifecycle(budget=None, **kwargs) -> RegistryLifecycle:
    return RegistryLifecycle(
        budget or make_budget(), loader=load_custom_registry, **kwargs)


def retained_for(content: bytes) -> int:
    return estimate_registry(
        count_custom_mapping_rows(content), len(content)).retained_bytes


# ---------------------------------------------------------------------------
# Estimator
# ---------------------------------------------------------------------------


def test_estimator_values_are_pinned_at_the_published_limits():
    estimate = estimate_registry(500_000, 64 * MIB)

    assert estimate.retained_bytes == (
        RETAINED_BASE_BYTES + 500_000 * RETAINED_BYTES_PER_ROW)
    assert estimate.parse_bytes == (
        PARSE_BASE_BYTES
        + 64 * MIB * PARSE_INPUT_MULTIPLIER
        + 500_000 * PARSE_BYTES_PER_ROW)
    assert estimate.total_bytes == (
        estimate.retained_bytes + estimate.parse_bytes)
    # The published maxima are inside the published pools.
    assert estimate.retained_bytes <= DEFAULT_RETAINED_BYTES
    assert estimate.parse_bytes <= DEFAULT_TRANSIENT_PARSE_BYTES
    assert estimate.total_bytes <= DEFAULT_COMBINED_BYTES
    assert estimate.retained_bytes == 768_065_536
    assert estimate.parse_bytes == 969_392_128


def test_estimator_is_monotonic_and_rejects_negative_input():
    small = estimate_registry(1, 1)
    large = estimate_registry(2, 1)
    assert large.retained_bytes > small.retained_bytes
    with pytest.raises(ValueError):
        estimate_registry(-1, 0)
    with pytest.raises(ValueError):
        estimate_registry(0, -1)
    with pytest.raises(TypeError):
        estimate_registry(1.0, 0)


def test_row_count_is_a_conservative_pre_parse_upper_bound():
    assert count_custom_mapping_rows(b"") == 0
    assert count_custom_mapping_rows(HEADER) == 0
    assert count_custom_mapping_rows(CONTENT_A) == 1
    assert count_custom_mapping_rows(CONTENT_B) == 2
    # A missing final newline still counts the last row.
    assert count_custom_mapping_rows(CONTENT_A.rstrip(b"\n")) == 1
    # Empty/comment lines are over-counted on purpose.
    assert count_custom_mapping_rows(HEADER + b"\n") == 1


# ---------------------------------------------------------------------------
# Budget: boundaries, 413, 429, parse slot
# ---------------------------------------------------------------------------


def test_413_for_estimates_that_can_never_fit():
    budget = make_budget(
        retained_bytes=1_000, transient_bytes=2_000, combined_bytes=3_000)

    for estimate in (
        RegistryEstimate(0, 0, 1_001, 0),
        RegistryEstimate(0, 0, 0, 2_001),
        RegistryEstimate(0, 0, 1_500, 1_501),
    ):
        with pytest.raises(RegistryAdmissionError) as info:
            budget.reserve(estimate)
        assert info.value.status_code == 413
        assert info.value.code == "registry_too_large"
        assert info.value.retry_after is None
    assert budget.stats().accounted_bytes == 0


def test_exact_combined_boundary_is_admitted():
    budget = make_budget(
        retained_bytes=1_000, transient_bytes=1_000, combined_bytes=2_000)
    estimate = RegistryEstimate(0, 0, 1_000, 1_000)

    reservation = budget.reserve(estimate)
    assert reservation.committed is False
    reservation.commit()
    stats = budget.stats()
    assert stats.retained_bytes == 1_000
    assert stats.reserved_retained_bytes == 0
    assert stats.transient_parse_bytes == 0
    assert stats.active_parses == 0


def test_temporary_capacity_exhaustion_is_429_and_does_not_evict():
    budget = make_budget(
        retained_bytes=1_000, transient_bytes=1_000, combined_bytes=2_000)
    first = budget.reserve(RegistryEstimate(0, 0, 1_000, 100))
    first.commit()

    with pytest.raises(RegistryAdmissionError) as info:
        budget.reserve(RegistryEstimate(0, 0, 1, 0))
    assert info.value.status_code == 429
    assert info.value.code == "capacity_unavailable"
    assert info.value.retry_after is None
    # The existing accounting is untouched (no silent eviction).
    assert budget.stats().retained_bytes == 1_000


def test_parse_slot_contention_is_429_with_retry_after():
    budget = make_budget(parse_concurrency=1)
    held = budget.reserve(estimate_registry(1, 100))

    with pytest.raises(RegistryAdmissionError) as info:
        budget.reserve(estimate_registry(1, 100), wait_seconds=0)
    assert info.value.status_code == 429
    assert info.value.code == "parse_busy"
    assert info.value.retry_after is not None and info.value.retry_after >= 1
    # Releasing the slot lets the next parse start.
    held.abort()
    budget.reserve(estimate_registry(1, 100)).abort()


def test_bounded_wait_acquires_the_serialised_parse_slot():
    budget = make_budget(parse_concurrency=1)
    held = budget.reserve(estimate_registry(1, 100))
    released = threading.Event()

    def release() -> None:
        time.sleep(0.05)
        held.abort()
        released.set()

    thread = threading.Thread(target=release)
    thread.start()
    try:
        reservation = budget.reserve(
            estimate_registry(1, 100), wait_seconds=2.0)
        assert released.is_set()
        reservation.abort()
    finally:
        thread.join(timeout=2)


def test_injected_memory_headroom_is_a_temporary_429():
    budget = RegistryBudget(
        RegistryBudgetConfig(
            retained_bytes=10_000,
            transient_bytes=10_000,
            combined_bytes=20_000,
            memory_headroom_reserve_bytes=100,
        ),
        memory_headroom=lambda: 500,
    )
    # 400 + reserve 100 fits exactly; 401 does not.
    budget.reserve(RegistryEstimate(0, 0, 200, 200)).abort()
    with pytest.raises(RegistryAdmissionError) as info:
        budget.reserve(RegistryEstimate(0, 0, 201, 200))
    assert info.value.status_code == 429
    assert info.value.code == "capacity_unavailable"


def test_cgroup_v2_headroom_supports_nested_paths_and_parent_limits(tmp_path):
    root = tmp_path / "cgroup"
    nested = root / "user.slice" / "session.scope"
    nested.mkdir(parents=True)
    (root / "memory.max").write_text("1000\n")
    (root / "memory.current").write_text("400\n")
    assert cgroup_v2_headroom(root, relative_path="user.slice/session.scope") == 600

    (nested / "memory.max").write_text("max\n")
    (nested / "memory.current").write_text("999\n")
    assert cgroup_v2_headroom(root, relative_path="user.slice/session.scope") == 600


# ---------------------------------------------------------------------------
# Lifecycle: idempotency, replacement, clear
# ---------------------------------------------------------------------------


def test_same_digest_is_reused_without_rebuilding():
    calls: list[bytes] = []

    def loader(data: bytes):
        calls.append(data)
        return load_custom_registry(data)

    life = RegistryLifecycle(make_budget(), loader=loader)
    first = life.register("session", CONTENT_A)
    second = life.register("session", CONTENT_A)

    assert first.reused is False
    assert second.reused is True
    assert second.revision == first.revision
    assert calls == [CONTENT_A]
    assert life.stats().retained_bytes == retained_for(CONTENT_A)
    assert life.stats().active_parses == 0
    assert life.current_revision("session") == first.revision


def test_different_content_replaces_and_releases_the_old_registry():
    life = make_lifecycle()
    first = life.register("session", CONTENT_A)
    second = life.register("session", CONTENT_B)

    assert second.revision != first.revision
    assert life.current_revision("session") == second.revision
    assert life.current_registry("session") is second.registry
    assert len(life.current_registry("session")) == 2
    assert life.stats().retained_bytes == retained_for(CONTENT_B)


def test_clear_with_revision_is_atomic_and_double_clear_is_harmless():
    life = make_lifecycle()
    written = life.register("session", CONTENT_A)

    with pytest.raises(RegistryWriteConflict):
        life.clear("session", expected_revision="not-the-revision")
    assert life.current_revision("session") == written.revision

    assert life.clear("session", expected_revision=written.revision) is True
    assert life.current_revision("session") is None
    assert life.stats().retained_bytes == 0
    assert life.clear("session") is False
    assert life.stats().retained_bytes == 0
    with pytest.raises(RegistryNotAvailable):
        life.acquire("session")


def test_acquire_can_be_bound_to_the_revision_it_displayed():
    life = make_lifecycle()
    written = life.register("session", CONTENT_A)
    with pytest.raises(RegistryWriteConflict):
        life.acquire("session", expected_revision="stale")
    with life.acquire("session", expected_revision=written.revision) as lease:
        assert lease.registry.resolve("chr1").seq_id == "custom:000001"


# ---------------------------------------------------------------------------
# Leases
# ---------------------------------------------------------------------------


def test_retired_registry_memory_is_accounted_until_the_last_lease():
    life = make_lifecycle()
    life.register("session", CONTENT_A)
    old_bytes = retained_for(CONTENT_A)
    new_bytes = retained_for(CONTENT_B)

    lease = life.acquire("session")
    replacement = life.register("session", CONTENT_B)

    assert lease.revision != replacement.revision
    assert life.stats().retained_bytes == old_bytes + new_bytes
    # The in-flight execution still sees the registry it leased.
    assert lease.registry.resolve("chr1").seq_id == "custom:000001"

    lease.release()
    assert life.stats().retained_bytes == new_bytes
    lease.release()  # idempotent: no double release
    assert life.stats().retained_bytes == new_bytes

    life.clear("session")
    assert life.stats().retained_bytes == 0


def test_clear_with_an_active_lease_defers_release():
    life = make_lifecycle()
    life.register("session", CONTENT_A)
    lease = life.acquire("session")
    assert life.clear("session") is True
    assert life.stats().retained_bytes == retained_for(CONTENT_A)
    lease.release()
    assert life.stats().retained_bytes == 0


# ---------------------------------------------------------------------------
# Session expiry and LRU eviction
# ---------------------------------------------------------------------------


def test_session_expiry_releases_registry_through_the_eviction_callback():
    store = SessionStore(ttl_seconds=10.0, max_sessions=4)
    life = RegistryLifecycle(
        make_budget(), is_live=store.contains, loader=load_custom_registry)
    store.set_on_evict(life.release_session)

    base = time.monotonic()
    session = store.create(now=base)
    life.register(session.token, CONTENT_A)
    assert life.stats().retained_bytes == retained_for(CONTENT_A)

    assert store.get(session.token, now=base + 11.0) is None
    assert life.current_revision(session.token) is None
    assert life.stats().retained_bytes == 0
    assert len(life) == 0


def test_lru_session_eviction_releases_the_registry():
    store = SessionStore(ttl_seconds=1000.0, max_sessions=1)
    life = RegistryLifecycle(
        make_budget(), is_live=store.contains, loader=load_custom_registry)
    store.set_on_evict(life.release_session)

    base = time.monotonic()
    first = store.create(now=base)
    life.register(first.token, CONTENT_A)
    second = store.create(now=base + 1.0)  # evicts `first`
    life.register(second.token, CONTENT_B)

    assert store.contains(first.token, now=base + 1.0) is False
    assert life.current_revision(first.token) is None
    assert life.current_revision(second.token) is not None
    assert life.stats().retained_bytes == retained_for(CONTENT_B)


def test_stale_write_finishing_after_eviction_does_not_resurrect_it():
    store = SessionStore(ttl_seconds=1000.0, max_sessions=4)
    started = threading.Event()
    release = threading.Event()

    def loader(data: bytes):
        if data == CONTENT_C:
            started.set()
            assert release.wait(timeout=5)
        return load_custom_registry(data)

    life = RegistryLifecycle(
        make_budget(), is_live=store.contains, loader=loader)
    store.set_on_evict(life.release_session)
    session = store.create()
    ticket = life.reserve_write(session.token)
    failures: list[BaseException] = []

    def write() -> None:
        try:
            life.register(session.token, CONTENT_C, ticket=ticket)
        except BaseException as exc:  # noqa: BLE001 - propagate to assertion
            failures.append(exc)

    thread = threading.Thread(target=write)
    thread.start()
    try:
        assert started.wait(timeout=5)
        store.drop(session.token)
        assert life.current_revision(session.token) is None
        assert life.stats().retained_bytes == 0
    finally:
        release.set()
        thread.join(timeout=5)

    assert len(failures) == 1 and isinstance(failures[0], RegistrySessionExpired)
    assert life.current_revision(session.token) is None
    assert len(life) == 0
    assert life.stats().accounted_bytes == 0


# ---------------------------------------------------------------------------
# Arrival-order registry writes (separate from query/annot ordering)
# ---------------------------------------------------------------------------


def test_an_earlier_write_cannot_overwrite_a_later_committed_write():
    # Concurrency 2 lets both parses overlap so completion order differs from
    # arrival order; this is exactly the stale-write case.
    budget = make_budget(parse_concurrency=2)
    life = RegistryLifecycle(budget, loader=load_custom_registry)
    life.register("session", CONTENT_A)

    started = threading.Event()
    release = threading.Event()

    def loader(data: bytes):
        if data == CONTENT_C:
            started.set()
            assert release.wait(timeout=5)
        return load_custom_registry(data)

    life._loader = loader
    earlier = life.reserve_write("session")
    later = life.reserve_write("session")
    failures: list[BaseException] = []

    def write_earlier() -> None:
        try:
            life.register("session", CONTENT_C, ticket=earlier)
        except BaseException as exc:  # noqa: BLE001 - propagate to assertion
            failures.append(exc)

    thread = threading.Thread(target=write_earlier)
    thread.start()
    try:
        assert started.wait(timeout=5)
        committed = life.register("session", CONTENT_B, ticket=later)
        assert committed.reused is False
    finally:
        release.set()
        thread.join(timeout=5)

    assert len(failures) == 1 and isinstance(failures[0], RegistryWriteConflict)
    assert life.current_revision("session") == committed.revision
    assert len(life.current_registry("session")) == 2
    assert life.stats().retained_bytes == retained_for(CONTENT_B)
    assert life.stats().transient_parse_bytes == 0


def test_identical_content_commit_supersedes_an_in_flight_earlier_parse():
    # With the default serialised parser, a later same-content write can take
    # the digest fast path while the earlier different parse is in flight.
    life = make_lifecycle()
    existing = life.register("session", CONTENT_A)

    started = threading.Event()
    release = threading.Event()

    def loader(data: bytes):
        if data == CONTENT_C:
            started.set()
            assert release.wait(timeout=5)
        return load_custom_registry(data)

    life._loader = loader
    earlier = life.reserve_write("session")
    failures: list[BaseException] = []

    def write_earlier() -> None:
        try:
            life.register("session", CONTENT_C, ticket=earlier)
        except BaseException as exc:  # noqa: BLE001 - propagate to assertion
            failures.append(exc)

    thread = threading.Thread(target=write_earlier)
    thread.start()
    try:
        assert started.wait(timeout=5)
        later = life.reserve_write("session")
        reused = life.register("session", CONTENT_A, ticket=later)
        assert reused.reused is True
        assert reused.revision == existing.revision
    finally:
        release.set()
        thread.join(timeout=5)

    assert len(failures) == 1 and isinstance(failures[0], RegistryWriteConflict)
    assert life.current_revision("session") == existing.revision
    assert life.stats().retained_bytes == retained_for(CONTENT_A)
    assert life.stats().accounted_bytes == retained_for(CONTENT_A)


def test_a_later_clear_blocks_an_in_flight_earlier_write():
    life = make_lifecycle()
    life.register("session", CONTENT_A)

    started = threading.Event()
    release = threading.Event()

    def loader(data: bytes):
        if data == CONTENT_C:
            started.set()
            assert release.wait(timeout=5)
        return load_custom_registry(data)

    life._loader = loader
    earlier = life.reserve_write("session")
    failures: list[BaseException] = []

    def write_earlier() -> None:
        try:
            life.register("session", CONTENT_C, ticket=earlier)
        except BaseException as exc:  # noqa: BLE001 - propagate to assertion
            failures.append(exc)

    thread = threading.Thread(target=write_earlier)
    thread.start()
    try:
        assert started.wait(timeout=5)
        later = life.reserve_write("session")
        assert life.clear("session", ticket=later) is True
        assert life.current_revision("session") is None
    finally:
        release.set()
        thread.join(timeout=5)

    assert len(failures) == 1 and isinstance(failures[0], RegistryWriteConflict)
    assert life.current_revision("session") is None
    assert life.stats().accounted_bytes == 0


def test_failed_writes_do_not_advance_the_high_water_mark():
    life = make_lifecycle()
    first = life.reserve_write("session")
    with pytest.raises(ValueError):
        life._loader = lambda data: (_ for _ in ()).throw(ValueError("bad"))
        life.register("session", CONTENT_A, ticket=first)

    life._loader = load_custom_registry
    older = life.reserve_write("session")
    assert older.stamp > first.stamp
    # The failed write never advanced write_done, so this still commits.
    written = life.register("session", CONTENT_A, ticket=first)
    assert written.reused is False
    assert life.current_revision("session") == written.revision


# ---------------------------------------------------------------------------
# Failure cleanup and repeated loops
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("error", [ValueError("bad"), asyncio.CancelledError()])
def test_parse_failure_and_cancellation_release_every_reservation(error):
    def loader(data: bytes):
        raise error

    life = RegistryLifecycle(make_budget(), loader=loader)
    with pytest.raises(type(error)):
        life.register("session", CONTENT_A)
    stats = life.stats()
    assert stats.retained_bytes == 0
    assert stats.reserved_retained_bytes == 0
    assert stats.transient_parse_bytes == 0
    assert stats.active_parses == 0

    life._loader = load_custom_registry
    assert life.register("session", CONTENT_A).reused is False


def test_repeated_failure_loops_cannot_leak_capacity_or_the_parse_slot():
    calls = {"n": 0}

    def loader(data: bytes):
        calls["n"] += 1
        raise RuntimeError("parse failed")

    budget = make_budget()
    life = RegistryLifecycle(budget, loader=loader)
    for _ in range(50):
        with pytest.raises(RuntimeError):
            life.register("session", CONTENT_A)
        assert budget.stats().accounted_bytes == 0
        assert budget.stats().active_parses == 0

    assert calls["n"] == 50
    life._loader = load_custom_registry
    written = life.register("session", CONTENT_A)
    assert written.reused is False
    assert budget.stats().retained_bytes == retained_for(CONTENT_A)


def test_concurrent_admissions_cannot_oversubscribe_the_retained_pool():
    one = retained_for(CONTENT_A)
    budget = make_budget(
        retained_bytes=2 * one,
        transient_bytes=8 * MIB,
        combined_bytes=16 * MIB,
        parse_concurrency=2,
    )
    life = RegistryLifecycle(budget, loader=load_custom_registry)
    start = threading.Barrier(8)
    successes: list[str] = []
    refusals: list[RegistryAdmissionError] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        start.wait(timeout=5)
        try:
            result = life.register(f"session-{index}", CONTENT_A, wait_seconds=0)
        except RegistryAdmissionError as exc:
            with lock:
                refusals.append(exc)
        else:
            with lock:
                successes.append(result.revision)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(successes) == 2
    assert len(refusals) == 6
    assert all(exc.status_code == 429 for exc in refusals)
    stats = budget.stats()
    assert stats.retained_bytes == 2 * one
    assert stats.retained_bytes <= stats.retained_limit
    assert stats.accounted_bytes <= stats.combined_limit
    assert stats.active_parses == 0
