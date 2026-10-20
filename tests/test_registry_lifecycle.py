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
    RegistryReplacementRequiresClear,
    RegistrySessionExpired,
    RegistryWriteConflict,
    RegistryWriteResult,
    cgroup_v2_headroom,
    count_custom_mapping_rows,
    estimate_registry,
    load_custom_registry,
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
        "retained_bytes": 16 * MIB,
        "transient_bytes": 24 * MIB,
        "combined_bytes": 40 * MIB,
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


@pytest.mark.parametrize(
    ("rows", "input_bytes", "retained_mib", "parse_mib"),
    [
        # Independent hand-computed vectors for the approved M2.1c formulas:
        #   retained = ceil((1 MiB + rows * 1.4 KiB + bytes) / 1 MiB)
        #   parse    = ceil((8 MiB + rows * 2.25 KiB + 2 * bytes) / 1 MiB)
        (1_000, 100 * 1024, 3, 11),
        (10_000, 1 * MIB, 16, 32),
        (100_000, 16 * MIB, 154, 260),
        (500_000, 64 * MIB, 749, 1235),
        # Additional vectors from the M2.2a review probe.
        (100_000, 64 * MIB, 202, 356),
        (500_000, 25 * MIB, 710, 1157),
    ],
)
def test_approved_estimator_vectors_are_pinned_to_whole_mib(
    rows, input_bytes, retained_mib, parse_mib
):
    estimate = estimate_registry(rows, input_bytes)

    assert estimate.retained_bytes == retained_mib * MIB
    assert estimate.parse_bytes == parse_mib * MIB
    assert estimate.total_bytes == (retained_mib + parse_mib) * MIB


def test_estimator_rounds_up_conservatively_to_whole_mib():
    empty = estimate_registry(0, 0)
    assert empty.retained_bytes == 1 * MIB
    assert empty.parse_bytes == 8 * MIB

    # Any non-zero row/byte charge rounds the retained pool up to the next MiB.
    tiny = estimate_registry(1, 1)
    assert tiny.retained_bytes == 2 * MIB
    assert tiny.parse_bytes == 9 * MIB


def test_published_maxima_are_inside_the_published_pools():
    estimate = estimate_registry(500_000, 64 * MIB)

    assert estimate.retained_bytes <= DEFAULT_RETAINED_BYTES
    assert estimate.parse_bytes <= DEFAULT_TRANSIENT_PARSE_BYTES
    assert estimate.total_bytes <= DEFAULT_COMBINED_BYTES


def test_estimator_is_monotonic_and_rejects_negative_input():
    small = estimate_registry(1, 1)
    large = estimate_registry(1_000, 1)
    assert large.retained_bytes > small.retained_bytes
    assert large.parse_bytes > small.parse_bytes
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
    assert info.value.retry_after is not None and info.value.retry_after >= 1
    # The existing accounting is untouched (no silent eviction).
    assert budget.stats().retained_bytes == 1_000


def test_transient_capacity_exact_boundary_is_admitted():
    budget = make_budget(
        retained_bytes=1_000, transient_bytes=1_000, combined_bytes=2_000)
    reservation = budget.reserve(RegistryEstimate(0, 0, 0, 1_000))
    assert budget.stats().transient_parse_bytes == 1_000
    reservation.abort()
    assert budget.stats().accounted_bytes == 0

    with pytest.raises(RegistryAdmissionError) as info:
        budget.reserve(RegistryEstimate(0, 0, 0, 1_001))
    assert info.value.status_code == 413
    assert info.value.code == "registry_too_large"


def test_combined_capacity_boundary_and_permanent_413():
    budget = make_budget(
        retained_bytes=1_000, transient_bytes=2_000, combined_bytes=3_000)

    # Exactly the combined pool: retained and transient each fit on their own.
    reservation = budget.reserve(RegistryEstimate(0, 0, 1_000, 2_000))
    assert budget.stats().accounted_bytes == 3_000
    reservation.abort()

    # One byte over the combined pool can never be admitted, even when each
    # component is below its own limit.
    with pytest.raises(RegistryAdmissionError) as info:
        budget.reserve(RegistryEstimate(0, 0, 1_000, 2_001))
    assert info.value.status_code == 413
    assert info.value.code == "registry_too_large"
    assert info.value.retry_after is None


def test_temporary_transient_and_combined_exhaustion_are_429():
    budget = make_budget(
        retained_bytes=5_000,
        transient_bytes=5_000,
        combined_bytes=6_000,
        parse_concurrency=2,
    )
    first = budget.reserve(RegistryEstimate(0, 0, 1_000, 2_000))
    assert first.active

    # A second parse would exceed the transient pool (2_000 + 2_000 > 5_000
    # is false here, so use a larger request for the transient reason).
    with pytest.raises(RegistryAdmissionError) as info:
        budget.reserve(RegistryEstimate(0, 0, 1_000, 4_000))
    assert info.value.status_code == 429
    assert info.value.code == "capacity_unavailable"
    assert info.value.retry_after is not None and info.value.retry_after >= 1
    assert "transient" in str(info.value)

    # Combined exhaustion: retained 1_000 + transient 2_000 (first) plus a
    # second total of 4_000 exceeds the 6_000 combined pool.
    with pytest.raises(RegistryAdmissionError) as info:
        budget.reserve(RegistryEstimate(0, 0, 1_000, 3_000))
    assert info.value.status_code == 429
    assert info.value.code == "capacity_unavailable"
    assert info.value.retry_after is not None and info.value.retry_after >= 1
    assert "combined" in str(info.value)

    first.abort()
    assert budget.stats().accounted_bytes == 0


def test_parse_busy_takes_precedence_over_capacity_exhaustion():
    budget = make_budget(
        retained_bytes=1 * MIB,
        transient_bytes=4 * MIB,
        combined_bytes=8 * MIB,
        parse_concurrency=1,
    )
    held = budget.reserve(RegistryEstimate(0, 0, 1 * MIB, 1 * MIB))

    with pytest.raises(RegistryAdmissionError) as info:
        budget.reserve(RegistryEstimate(0, 0, 1 * MIB, 1 * MIB), wait_seconds=0)
    assert info.value.status_code == 429
    assert info.value.code == "parse_busy"
    assert info.value.retry_after is not None and info.value.retry_after >= 1

    held.abort()


def test_bounded_wait_rechecks_capacity_after_the_parse_slot_frees():
    budget = make_budget(
        retained_bytes=1 * MIB,
        transient_bytes=4 * MIB,
        combined_bytes=8 * MIB,
        parse_concurrency=1,
    )
    held = budget.reserve(RegistryEstimate(0, 0, 1 * MIB, 1 * MIB))
    released = threading.Event()

    def release() -> None:
        time.sleep(0.05)
        held.abort()
        released.set()

    thread = threading.Thread(target=release)
    thread.start()
    try:
        reservation = budget.reserve(
            RegistryEstimate(0, 0, 1 * MIB, 1 * MIB), wait_seconds=2.0)
        assert released.is_set()
        reservation.abort()
    finally:
        thread.join(timeout=2)


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
    assert info.value.retry_after is not None and info.value.retry_after >= 1


@pytest.mark.parametrize(
    ("kind", "expected_code"),
    [
        ("parse_busy", "parse_busy"),
        ("replacement_requires_clear", "replacement_requires_clear"),
        ("registry_too_large", "registry_too_large"),
    ],
)
def test_no_expiry_sweep_outside_temporary_capacity_refusals(kind, expected_code):
    # Only a temporary capacity refusal may trigger the expiry sweep and its
    # single retry. A busy parse slot, a permanent 409 and a permanent 413
    # must not sweep anything.
    retained = 1 * MIB if kind == "registry_too_large" else 3 * MIB
    budget = make_budget(
        retained_bytes=retained,
        transient_bytes=24 * MIB,
        combined_bytes=40 * MIB,
    )
    life = make_lifecycle(budget)
    sweeps: list[int] = []
    original_sweep = life.sweep

    def counting_sweep(**kwargs):
        sweeps.append(1)
        return original_sweep(**kwargs)

    life.sweep = counting_sweep

    if kind == "parse_busy":
        held = budget.reserve(estimate_registry(1, 100))
        try:
            with pytest.raises(RegistryAdmissionError) as info:
                life.register("a", CONTENT_A, wait_seconds=0)
        finally:
            held.abort()
    elif kind == "replacement_requires_clear":
        life.register("a", CONTENT_A)
        with pytest.raises(RegistryAdmissionError) as info:
            life.register("a", CONTENT_B)
    else:
        with pytest.raises(RegistryAdmissionError) as info:
            life.register("a", CONTENT_A)

    assert info.value.code == expected_code
    assert sweeps == []


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


def test_small_replacement_succeeds_atomically():
    life = make_lifecycle()
    first = life.register("session", CONTENT_A)
    first_bytes = retained_for(CONTENT_A)

    second = life.register("session", CONTENT_B)

    assert second.revision != first.revision
    assert life.current_revision("session") == second.revision
    assert life.current_registry("session") is second.registry
    stats = life.stats()
    assert stats.retained_bytes == retained_for(CONTENT_B)
    assert stats.retained_bytes < first_bytes + retained_for(CONTENT_B)
    assert stats.reserved_retained_bytes == 0
    assert stats.transient_parse_bytes == 0
    assert stats.active_parses == 0


def test_replacement_that_cannot_coexist_is_refused_without_state_change():
    # Both registries fit alone, but the old one must stay charged while the
    # new one is parsed. The replacement is therefore permanently impossible
    # until the caller explicitly clears the existing registry.
    budget = make_budget(
        retained_bytes=3 * MIB,
        transient_bytes=24 * MIB,
        combined_bytes=40 * MIB,
    )
    life = make_lifecycle(budget)
    first = life.register("session", CONTENT_A)
    first_registry = life.current_registry("session")

    with pytest.raises(RegistryReplacementRequiresClear) as info:
        life.register("session", CONTENT_B)

    assert info.value.status_code == 409
    assert info.value.code == "replacement_requires_clear"
    assert info.value.retry_after is None
    assert "clear" in str(info.value).lower()
    assert life.current_revision("session") == first.revision
    assert life.current_registry("session") is first_registry
    stats = life.stats()
    assert stats.retained_bytes == retained_for(CONTENT_A)
    assert stats.reserved_retained_bytes == 0
    assert stats.transient_parse_bytes == 0
    assert stats.active_parses == 0

    # Clearing explicitly releases the old charge, after which the upload
    # succeeds in the same session.
    assert life.clear("session") is True
    second = life.register("session", CONTENT_B)
    assert second.revision != first.revision
    assert life.stats().retained_bytes == retained_for(CONTENT_B)


def test_leased_registry_is_not_released_by_a_refused_replacement_or_clear():
    budget = make_budget(
        retained_bytes=3 * MIB,
        transient_bytes=24 * MIB,
        combined_bytes=40 * MIB,
    )
    life = make_lifecycle(budget)
    first = life.register("session", CONTENT_A)
    lease = life.acquire("session")

    with pytest.raises(RegistryReplacementRequiresClear):
        life.register("session", CONTENT_B)
    assert life.current_revision("session") == first.revision
    assert life.stats().retained_bytes == retained_for(CONTENT_A)

    # A lease keeps the old registry accounted after an explicit clear.
    assert life.clear("session") is True
    assert life.stats().retained_bytes == retained_for(CONTENT_A)
    lease.release()
    assert life.stats().retained_bytes == 0

    # The explicit clear now permits the upload.
    written = life.register("session", CONTENT_B)
    assert life.current_revision("session") == written.revision
    assert life.stats().retained_bytes == retained_for(CONTENT_B)


# ---------------------------------------------------------------------------
# Replacement admission classification: permanent 409 versus temporary 429
# ---------------------------------------------------------------------------


def test_expired_session_capacity_is_swept_so_a_replacement_succeeds():
    # Session B holds the retained pool. When B expires, the sweep must
    # release its stale charge, otherwise A's replacement is refused even
    # though it fits once the expired session is gone.
    now = [100.0]
    store = SessionStore(ttl_seconds=10.0, max_sessions=4)
    budget = make_budget(
        retained_bytes=4 * MIB,
        transient_bytes=24 * MIB,
        combined_bytes=40 * MIB,
    )
    life = RegistryLifecycle(
        budget,
        is_live=lambda token: store.contains(token, now=now[0]),
        loader=load_custom_registry,
    )
    store.set_on_evict(life.release_session)
    a = store.create(now=now[0])
    b = store.create(now=now[0])
    life.register(a.token, CONTENT_A)
    life.register(b.token, CONTENT_A)
    assert life.stats().retained_bytes == 4 * MIB

    # A stays live, B expires. Nothing has released B's charge yet.
    now[0] = 105.0
    assert store.get(a.token, now=now[0]) is not None
    now[0] = 111.0
    assert store.contains(b.token, now=now[0]) is False
    assert store.contains(a.token, now=now[0]) is True
    assert life.stats().retained_bytes == 4 * MIB

    written = life.register(a.token, CONTENT_B)

    assert written.reused is False
    assert life.current_revision(a.token) == written.revision
    assert life.current_revision(b.token) is None
    assert life.stats().retained_bytes == retained_for(CONTENT_B)
    assert len(life) == 1


def test_cross_session_capacity_exhaustion_is_429_and_recovers_after_release():
    # A's old and new registries fit together (2 + 2 MiB <= 4 MiB), so the
    # replacement is not permanently impossible: session B simply holds the
    # capacity for now. That is a retryable 429, not a 409.
    budget = make_budget(
        retained_bytes=4 * MIB,
        transient_bytes=24 * MIB,
        combined_bytes=40 * MIB,
    )
    life = make_lifecycle(budget)
    attempts: list[int] = []
    original_reserve = budget.reserve

    def counting_reserve(estimate, **kwargs):
        attempts.append(1)
        return original_reserve(estimate, **kwargs)

    budget.reserve = counting_reserve
    sweeps: list[int] = []
    original_sweep = life.sweep

    def counting_sweep(**kwargs):
        sweeps.append(1)
        return original_sweep(**kwargs)

    life.sweep = counting_sweep

    first = life.register("a", CONTENT_A)
    life.register("b", CONTENT_A)
    assert life.stats().retained_bytes == 4 * MIB

    with pytest.raises(RegistryAdmissionError) as info:
        life.register("a", CONTENT_B)

    error = info.value
    assert error.status_code == 429
    assert error.code == "capacity_unavailable"
    assert error.retry_after is not None and error.retry_after >= 1
    # Exactly one expiry sweep and exactly one retry.
    assert len(sweeps) == 1
    assert len(attempts) == 4  # A, B, the refused attempt and its retry

    # B releases its capacity; the unchanged request now succeeds.
    assert life.clear("b") is True
    written = life.register("a", CONTENT_B)

    assert written.reused is False
    assert written.revision != first.revision
    assert life.current_revision("a") == written.revision
    assert life.stats().retained_bytes == retained_for(CONTENT_B)


def test_self_capacity_impossible_replacement_is_409_without_retry_after():
    # The old and the new registry cannot coexist even in an otherwise empty
    # budget, so no amount of waiting or sweeping can help.
    budget = make_budget(
        retained_bytes=3 * MIB,
        transient_bytes=24 * MIB,
        combined_bytes=40 * MIB,
    )
    life = make_lifecycle(budget)
    first = life.register("a", CONTENT_A)

    with pytest.raises(RegistryReplacementRequiresClear) as info:
        life.register("a", CONTENT_B)

    assert info.value.status_code == 409
    assert info.value.code == "replacement_requires_clear"
    assert info.value.retry_after is None
    assert "clear" in str(info.value).lower()
    assert life.current_revision("a") == first.revision
    assert life.stats().retained_bytes == retained_for(CONTENT_A)


def test_combined_pool_self_impossibility_is_409():
    # The retained pool has room for both registries, but the combined pool
    # does not: the replacement is still permanently impossible.
    budget = make_budget(
        retained_bytes=8 * MIB,
        transient_bytes=12 * MIB,
        combined_bytes=12 * MIB,
    )
    life = make_lifecycle(budget)
    first = life.register("a", CONTENT_A)
    assert life.stats().retained_bytes == retained_for(CONTENT_A)

    with pytest.raises(RegistryReplacementRequiresClear) as info:
        life.register("a", CONTENT_B)

    assert info.value.status_code == 409
    assert info.value.retry_after is None
    assert life.current_revision("a") == first.revision
    assert life.stats().retained_bytes == retained_for(CONTENT_A)


@pytest.mark.parametrize(
    ("retained_bytes", "with_other_session", "expected_status", "expected_code"),
    [
        (4 * MIB, True, 429, "capacity_unavailable"),
        (3 * MIB, False, 409, "replacement_requires_clear"),
    ],
)
def test_refused_replacement_preserves_registry_revision_and_accounting(
    retained_bytes, with_other_session, expected_status, expected_code
):
    budget = make_budget(
        retained_bytes=retained_bytes,
        transient_bytes=24 * MIB,
        combined_bytes=40 * MIB,
    )
    life = make_lifecycle(budget)
    first = life.register("a", CONTENT_A)
    lease = life.acquire("a")
    if with_other_session:
        life.register("b", CONTENT_A)

    with pytest.raises(RegistryAdmissionError) as info:
        life.register("a", CONTENT_B)

    assert info.value.status_code == expected_status
    assert info.value.code == expected_code
    if expected_status == 429:
        assert info.value.retry_after is not None
    else:
        assert info.value.retry_after is None

    # The registry, its revision and the leased result survive the refusal.
    assert life.current_revision("a") == first.revision
    assert life.current_registry("a") is not None
    assert lease.registry.resolve("chr1").seq_id == "custom:000001"
    stats = life.stats()
    assert stats.reserved_retained_bytes == 0
    assert stats.transient_parse_bytes == 0
    assert stats.active_parses == 0
    assert stats.retained_bytes == (
        4 * MIB if with_other_session else retained_for(CONTENT_A)
    )


def test_retired_registry_with_an_active_lease_stays_charged_until_release():
    # A retired registry keeps its charge while an execution still leases it,
    # so the charge keeps blocking other sessions until the lease is gone.
    budget = make_budget(
        retained_bytes=5 * MIB,
        transient_bytes=24 * MIB,
        combined_bytes=40 * MIB,
    )
    life = make_lifecycle(budget)
    life.register("a", CONTENT_A)
    lease = life.acquire("a")
    life.register("a", CONTENT_B)

    assert life.stats().retained_bytes == (
        retained_for(CONTENT_A) + retained_for(CONTENT_B)
    )

    with pytest.raises(RegistryAdmissionError) as info:
        life.register("b", CONTENT_A)
    assert info.value.status_code == 429
    assert info.value.code == "capacity_unavailable"

    lease.release()
    assert life.stats().retained_bytes == retained_for(CONTENT_B)
    life.register("b", CONTENT_A)
    assert life.stats().retained_bytes == (
        retained_for(CONTENT_B) + retained_for(CONTENT_A)
    )


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


def test_double_release_is_detected_instead_of_clamped():
    budget = make_budget()
    reservation = budget.reserve(RegistryEstimate(0, 0, 1 * MIB, 0))
    reservation.commit()
    budget.release_retained(1 * MIB)
    assert budget.stats().retained_bytes == 0
    with pytest.raises(RuntimeError):
        budget.release_retained(1)


def test_lease_and_entry_double_release_are_detected():
    life = make_lifecycle()
    life.register("session", CONTENT_A)
    lease = life.acquire("session")
    life.clear("session")
    assert life.stats().retained_bytes == retained_for(CONTENT_A)

    lease.release()
    lease.release()  # the lease itself is idempotent
    assert life.stats().retained_bytes == 0
    with pytest.raises(RuntimeError):
        lease._entry.release_lease()


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


def test_expired_session_accounting_is_swept_before_capacity_refusal():
    # Session A's registry stays charged after A expires. Admitting B must
    # release that stale charge itself, not wait for another session create.
    now = [100.0]
    store = SessionStore(ttl_seconds=10.0, max_sessions=4)
    budget = make_budget(
        retained_bytes=3 * MIB,
        transient_bytes=24 * MIB,
        combined_bytes=40 * MIB,
    )
    life = RegistryLifecycle(
        budget,
        is_live=lambda token: store.contains(token, now=now[0]),
        loader=load_custom_registry,
    )
    store.set_on_evict(life.release_session)
    stale = store.create(now=now[0])
    live = store.create(now=now[0])
    life.register(stale.token, CONTENT_A)
    assert life.stats().retained_bytes == retained_for(CONTENT_A)

    now[0] = 105.0
    assert store.get(live.token, now=now[0]) is live
    now[0] = 111.0
    assert store.contains(stale.token, now=now[0]) is False
    # No create/sweep has run yet: the stale registry is still accounted.
    assert life.stats().retained_bytes == retained_for(CONTENT_A)

    written = life.register(live.token, CONTENT_B)

    assert life.current_revision(live.token) == written.revision
    assert life.current_revision(stale.token) is None
    assert life.stats().retained_bytes == retained_for(CONTENT_B)
    assert len(life) == 1


def test_reserve_write_does_not_create_slots_for_invalid_sessions():
    now = [100.0]
    store = SessionStore(ttl_seconds=10.0, max_sessions=4)
    life = RegistryLifecycle(
        make_budget(),
        is_live=lambda token: store.contains(token, now=now[0]),
        loader=load_custom_registry,
    )

    for _ in range(100):
        assert life.reserve_write("never-issued") is None
    assert len(life._slots) == 0

    session = store.create(now=now[0])
    assert life.reserve_write(session.token) is not None
    assert len(life._slots) == 1

    # Expiry without any eviction callback: reserve_write must remove the
    # stale slot instead of keeping or re-creating it.
    now[0] = 200.0
    for _ in range(100):
        assert life.reserve_write(session.token) is None
    assert len(life._slots) == 0

    # LRU/drop eviction without a callback has the same effect.
    evicted = store.create(now=now[0])
    assert life.reserve_write(evicted.token) is not None
    store.drop(evicted.token)
    assert life.reserve_write(evicted.token) is None
    assert len(life._slots) == 0


def test_session_store_notifies_on_drop_get_expiry_sweep_and_create():
    evicted: list[str] = []
    store = SessionStore(
        ttl_seconds=10.0, max_sessions=2, on_evict=evicted.append)

    dropped = store.create(now=0.0)
    store.drop(dropped.token)
    assert evicted == [dropped.token]

    evicted.clear()
    expired = store.create(now=100.0)
    assert store.get(expired.token, now=111.0) is None
    assert evicted == [expired.token]

    evicted.clear()
    first = store.create(now=200.0)
    second = store.create(now=200.0)
    assert store.sweep(now=211.0) == 2
    assert set(evicted) == {first.token, second.token}

    evicted.clear()
    stale_on_create = store.create(now=300.0)
    store.create(now=311.0)
    assert evicted == [stale_on_create.token]

    evicted.clear()
    lru_first = store.create(now=400.0)
    store.create(now=400.0)
    store.create(now=400.0)  # over max_sessions: evicts the LRU session
    assert lru_first.token in evicted


def test_contains_ignores_expiry_without_notifying_the_callback():
    evicted: list[str] = []
    store = SessionStore(ttl_seconds=10.0, on_evict=evicted.append)
    session = store.create(now=0.0)

    assert store.contains(session.token, now=11.0) is False
    assert evicted == []
    assert len(store) == 1


def test_eviction_callback_errors_never_escape_the_store(caplog):
    store = SessionStore(ttl_seconds=10.0)
    store.set_on_evict(lambda token: (_ for _ in ()).throw(RuntimeError("boom")))
    session = store.create()

    store.drop(session.token)  # must not raise
    assert len(store) == 0
    assert "session eviction callback failed" in caplog.text


def test_eviction_callback_can_reenter_the_store_without_deadlock():
    events: list[tuple[str, bool]] = []
    store = SessionStore(ttl_seconds=10.0, max_sessions=4)

    def callback(token: str) -> None:
        events.append((token, store.contains(token)))
        store.sweep()

    store.set_on_evict(callback)
    session = store.create()
    thread = threading.Thread(target=store.drop, args=(session.token,))
    thread.start()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert events == [(session.token, False)]


def test_session_store_sweep_runs_its_callbacks_outside_the_store_lock():
    # A callback that re-enters the store deadlocks when it runs while the
    # store lock is held. The bounded join turns that deadlock into a failure
    # instead of a hung test.
    events: list[tuple[str, bool]] = []
    store = SessionStore(ttl_seconds=10.0, max_sessions=4)

    def callback(token: str) -> None:
        events.append((token, store.contains(token)))
        store.sweep()

    store.set_on_evict(callback)
    first = store.create(now=0.0)
    second = store.create(now=0.0)

    finished = threading.Event()

    def run() -> None:
        store.sweep(now=11.0)
        finished.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=2)

    assert finished.is_set()
    assert not thread.is_alive()
    assert {token for token, _ in events} == {first.token, second.token}
    assert all(seen is False for _, seen in events)
    assert len(store) == 0


def test_identical_digest_fast_path_rechecks_session_liveness():
    live = [True]
    life = RegistryLifecycle(
        make_budget(),
        is_live=lambda token: live[0],
        loader=load_custom_registry,
    )
    life.register("session", CONTENT_A)

    live[0] = False
    with pytest.raises(RegistrySessionExpired):
        life.register("session", CONTENT_A)  # identical-content fast path

    assert life.stats().retained_bytes == 0
    assert len(life._slots) == 0


def test_same_digest_fast_path_with_a_reserved_ticket_rejects_an_expired_session():
    # The ticket was reserved while the session was live, so the fast path
    # itself is the only liveness guard for this write.
    live = [True]
    life = RegistryLifecycle(
        make_budget(),
        is_live=lambda token: live[0],
        loader=load_custom_registry,
    )
    life.register("session", CONTENT_A)
    slot = life._slots["session"]
    ticket = life.reserve_write("session")
    assert ticket is not None
    committed_stamp = slot.write_done

    live[0] = False
    with pytest.raises(RegistrySessionExpired):
        life.register("session", CONTENT_A, ticket=ticket)

    # The refusal commits nothing: no stamp advance and no resurrected
    # registry. The dead session's own accounting is released.
    assert slot.write_done == committed_stamp
    assert life.current_revision("session") is None
    assert life.stats().retained_bytes == 0
    assert len(life._slots) == 0


@pytest.mark.parametrize("operation", ["clear", "acquire"])
def test_expired_session_is_refused_by_clear_and_acquire(operation):
    live = [True]
    life = RegistryLifecycle(
        make_budget(),
        is_live=lambda token: live[0],
        loader=load_custom_registry,
    )
    life.register("session", CONTENT_A)

    live[0] = False
    with pytest.raises(RegistrySessionExpired):
        getattr(life, operation)("session")

    assert life.stats().retained_bytes == 0
    assert len(life._slots) == 0


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


def test_same_digest_in_flight_parses_converge_on_one_revision():
    budget = make_budget(parse_concurrency=2)
    calls: list[bytes] = []
    started = [threading.Event(), threading.Event()]
    release = [threading.Event(), threading.Event()]
    calls_lock = threading.Lock()

    def loader(data: bytes):
        with calls_lock:
            index = len(calls)
            calls.append(data)
        started[index].set()
        assert release[index].wait(timeout=5)
        return load_custom_registry(data)

    life = RegistryLifecycle(budget, loader=loader)
    results: dict[str, RegistryWriteResult] = {}
    failures: list[BaseException] = []

    def write(name: str, ticket) -> None:
        try:
            results[name] = life.register(
                "session", CONTENT_C, ticket=ticket)
        except BaseException as exc:  # noqa: BLE001 - propagate to assertion
            failures.append(exc)

    earlier = life.reserve_write("session")
    earlier_thread = threading.Thread(
        target=write, args=("earlier", earlier))
    earlier_thread.start()
    assert started[0].wait(timeout=5)

    later = life.reserve_write("session")
    later_thread = threading.Thread(target=write, args=("later", later))
    later_thread.start()
    assert started[1].wait(timeout=5)

    # The earlier-started parse commits first; the later in-flight parse must
    # then reuse that revision rather than replace it with a second registry.
    release[0].set()
    earlier_thread.join(timeout=5)
    release[1].set()
    later_thread.join(timeout=5)

    assert failures == []
    assert len(calls) == 2
    assert results["earlier"].revision == results["later"].revision
    assert results["earlier"].reused is False
    assert results["later"].reused is True
    stats = life.stats()
    assert stats.retained_bytes == retained_for(CONTENT_C)
    assert stats.accounted_bytes == retained_for(CONTENT_C)
    assert stats.active_parses == 0


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
        transient_bytes=24 * MIB,
        combined_bytes=40 * MIB,
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
