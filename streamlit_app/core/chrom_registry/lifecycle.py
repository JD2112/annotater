"""Resource accounting and lifecycle for session-scoped custom registries.

The scientific registry implementation (``custom.load_custom_registry`` and
``loader.ChromosomeRegistry``) is reused unchanged: this module only decides
whether a custom mapping may be built, keeps the resulting immutable registry
attached to exactly one session, and releases its accounting at the right
time. No public HTTP endpoint is defined here.

Accounting model
----------------
Three pools bound *custom* mappings only (bundled registries are immutable and
shared process-wide):

* ``retained_bytes`` -- registries that are currently reachable or still
  referenced by an execution lease. A retired registry keeps its accounting
  until its final lease is released.
* ``transient_bytes`` -- the temporary peak of one parse. A parse reservation
  is taken atomically together with the eventual retained charge, so two
  requests can never together oversubscribe the combined pool.
* ``combined_bytes`` -- the sum of retained and transient charges (a registry
  being parsed counts in both, deliberately conservative).

The values are *estimates*, never measurements of RSS. They implement the
approved M2.1c formulas exactly, with conservative integer rounding and a
whole-MiB ceiling::

    retained = ceil((1 MiB + rows * 1.4 KiB + bytes) / 1 MiB)
    parse    = ceil((8 MiB + rows * 2.25 KiB + 2 * bytes) / 1 MiB)

``default_memory_headroom`` is a separate, injected live check (cgroup v2 or
host available memory) used only to avoid starting a parse that the process
cannot hold. See ``docs/technical/registry-resource-lifecycle.md`` for the
authoritative contract and its limitations.

Lifecycle model
---------------
A :class:`RegistryLifecycle` owns one slot per session token. The slot keeps
the committed registry, its content digest and revision, and a write-order
domain *separate* from the dataset ``query``/``annot`` ordering. Registry
writes follow request arrival order:

* a successful write advances ``write_done``; a failed, superseded or stale
  write never does;
* a write whose stamp is below ``write_done`` is refused (409), so an earlier
  request can never overwrite a later committed one;
* identical content reuses the committed revision without parsing again;
* clearing leaves a tombstone slot so an in-flight earlier write cannot
  resurrect the registry;
* every commit re-checks that the session is still live, so a write that
  finishes after expiry/LRU eviction is discarded and cannot recreate the
  slot (the eviction callback releases any existing registry independently).

Execution leases prevent a registry from being released while a run is using
it: replacement, clear and eviction retire the registry, and its retained
accounting is released only when the final lease goes away. Lease and
reservation releases are idempotent.
"""

from __future__ import annotations

import hashlib
import math
import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from .custom import load_custom_registry
from .loader import ChromosomeRegistry

MIB = 1024 * 1024

#: Defaults from the approved M2.2a resource budget.
DEFAULT_RETAINED_BYTES = 768 * MIB
DEFAULT_TRANSIENT_PARSE_BYTES = 1280 * MIB
DEFAULT_COMBINED_BYTES = 2048 * MIB
DEFAULT_PARSE_CONCURRENCY = 1
DEFAULT_MEMORY_HEADROOM_RESERVE_BYTES = 128 * MIB

#: Bounded wait for the serialised parse slot before answering 429.
DEFAULT_PARSE_WAIT_SECONDS = 2.0

#: Approved M2.1c estimator constants. The fractional byte-per-row terms are
#: evaluated as exact integer ratios and only rounded up once, by the final
#: whole-MiB ceiling. ``1.4 KiB == 7/5 KiB`` and ``2.25 KiB == 9/4 KiB``.
KIB = 1024
RETAINED_BASE_BYTES = 1 * MIB
RETAINED_BYTES_PER_ROW_NUMERATOR = 7
RETAINED_BYTES_PER_ROW_DENOMINATOR = 5
PARSE_BASE_BYTES = 8 * MIB
PARSE_BYTES_PER_ROW_NUMERATOR = 9
PARSE_BYTES_PER_ROW_DENOMINATOR = 4
PARSE_INPUT_MULTIPLIER = 2

#: Retry-After (seconds) for a temporary capacity refusal.
DEFAULT_RETRY_AFTER_SECONDS = 1

CGROUP_V2_ROOT = Path("/sys/fs/cgroup")


# ---------------------------------------------------------------------------
# Estimators
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegistryEstimate:
    """Conservative accounting for one custom mapping.

    ``retained_bytes`` is charged while the registry lives; ``parse_bytes`` is
    the temporary peak charged while it is being built. ``total_bytes`` is the
    combined pool requirement. These are estimates for admission only and are
    not a claim about actual RSS.
    """

    row_count: int
    input_bytes: int
    retained_bytes: int
    parse_bytes: int

    @property
    def total_bytes(self) -> int:
        return self.retained_bytes + self.parse_bytes


def _ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def _estimate_with_ceiling(
    base_bytes: int,
    *,
    input_bytes: int,
    input_multiplier: int,
    row_count: int,
    row_bytes_numerator: int,
    row_bytes_denominator: int,
) -> int:
    """Ceil an exact rational byte estimate to a whole number of MiB."""
    numerator = (
        (base_bytes + input_multiplier * input_bytes) * row_bytes_denominator
        + row_count * row_bytes_numerator * KIB
    )
    denominator = row_bytes_denominator * MIB
    return _ceil_div(numerator, denominator) * MIB


def estimate_registry(row_count: int, input_bytes: int) -> RegistryEstimate:
    """The conservative retained/transient charge for one mapping.

    ``row_count`` is the number of data rows (the header is not a row) and
    ``input_bytes`` is the size of the UTF-8 mapping. Both must be
    non-negative integers. The approved M2.1c formulas are evaluated with
    integer arithmetic and rounded up to whole MiB.
    """
    if not isinstance(row_count, int) or not isinstance(input_bytes, int):
        raise TypeError("row_count and input_bytes must be integers")
    if row_count < 0 or input_bytes < 0:
        raise ValueError("row_count and input_bytes must be non-negative")
    retained = _estimate_with_ceiling(
        RETAINED_BASE_BYTES,
        input_bytes=input_bytes,
        input_multiplier=1,
        row_count=row_count,
        row_bytes_numerator=RETAINED_BYTES_PER_ROW_NUMERATOR,
        row_bytes_denominator=RETAINED_BYTES_PER_ROW_DENOMINATOR,
    )
    parse = _estimate_with_ceiling(
        PARSE_BASE_BYTES,
        input_bytes=input_bytes,
        input_multiplier=PARSE_INPUT_MULTIPLIER,
        row_count=row_count,
        row_bytes_numerator=PARSE_BYTES_PER_ROW_NUMERATOR,
        row_bytes_denominator=PARSE_BYTES_PER_ROW_DENOMINATOR,
    )
    return RegistryEstimate(row_count, input_bytes, retained, parse)


def count_custom_mapping_rows(content: bytes) -> int:
    """A conservative upper bound on data rows before structural parsing.

    Newline count minus the header line is an upper bound: empty lines and
    comment lines also count. A final line without a newline still counts.
    This avoids a full parse merely to reserve memory; the real loader still
    enforces :data:`DEFAULT_MAX_ROWS`.
    """
    data = _as_bytes(content)
    if not data:
        return 0
    lines = data.count(b"\n")
    if not data.endswith(b"\n"):
        lines += 1
    return max(0, lines - 1)


def _as_bytes(content) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, (bytearray, memoryview)):
        return bytes(content)
    raise TypeError("a custom mapping must be passed as bytes")


# ---------------------------------------------------------------------------
# Injected live-memory headroom (cgroup v2 where available)
# ---------------------------------------------------------------------------


def _read_int(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _cgroup_relative_path() -> str:
    """The process's cgroup v2 path from ``/proc/self/cgroup``, if any."""
    try:
        lines = Path("/proc/self/cgroup").read_text(
            encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in lines:
        # cgroup v2: "0::/path"; v1 and hybrid lines do not start with "0::".
        if line.startswith("0::"):
            return line[3:].strip("/")
    return ""


def cgroup_v2_headroom(
    root: Path | str = CGROUP_V2_ROOT,
    *,
    relative_path: str | None = None,
) -> int | None:
    """Available bytes under the nearest finite cgroup v2 ``memory.max``.

    Walks from the process's cgroup (or ``relative_path``) upwards, because
    cgroup v2 limits may be set on an ancestor. Returns ``None`` when cgroup
    v2 is unavailable or every limit is ``max`` (unlimited).
    """
    root_path = Path(root)
    if relative_path is None:
        relative_path = _cgroup_relative_path()
    candidate = root_path / relative_path.strip("/") if relative_path else root_path
    while True:
        limit = _read_int(candidate / "memory.max")
        if limit is not None:
            current = _read_int(candidate / "memory.current")
            if current is not None:
                return max(0, limit - current)
        if candidate == root_path:
            return None
        candidate = candidate.parent


def default_memory_headroom() -> int | None:
    """Best-effort live headroom in bytes, or ``None`` when unknown.

    cgroup v2 (containers) is preferred, then Linux ``MemAvailable``, then the
    host's available page count. The probe never raises: an unavailable or
    unreadable source means "unknown", not an artificial rejection.
    """
    try:
        headroom = cgroup_v2_headroom()
        if headroom is not None:
            return headroom
    except Exception:  # noqa: BLE001, S110 - probe is best-effort
        pass
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, UnicodeError):
        pass
    try:
        pages = os.sysconf("SC_AVPHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return int(pages) * int(page_size)
    except (OSError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# Budget and admission
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegistryBudgetConfig:
    """Configurable accounting limits for custom-mapping registries."""

    retained_bytes: int = DEFAULT_RETAINED_BYTES
    transient_bytes: int = DEFAULT_TRANSIENT_PARSE_BYTES
    combined_bytes: int = DEFAULT_COMBINED_BYTES
    parse_concurrency: int = DEFAULT_PARSE_CONCURRENCY
    memory_headroom_reserve_bytes: int = DEFAULT_MEMORY_HEADROOM_RESERVE_BYTES

    def __post_init__(self) -> None:
        for name in (
            "retained_bytes",
            "transient_bytes",
            "combined_bytes",
            "memory_headroom_reserve_bytes",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.retained_bytes > self.combined_bytes:
            raise ValueError("retained_bytes cannot exceed combined_bytes")
        if self.transient_bytes > self.combined_bytes:
            raise ValueError("transient_bytes cannot exceed combined_bytes")
        if not isinstance(self.parse_concurrency, int) or self.parse_concurrency < 1:
            raise ValueError("parse_concurrency must be a positive integer")

    @classmethod
    def from_settings(cls) -> RegistryBudgetConfig:
        """Defaults plus the deployment's ``ANNOTATER_REGISTRY_*`` overrides."""
        from streamlit_app.config import Settings

        return cls(
            retained_bytes=Settings.REGISTRY_RETAINED_BUDGET_BYTES,
            transient_bytes=Settings.REGISTRY_TRANSIENT_PARSE_BYTES,
            combined_bytes=Settings.REGISTRY_COMBINED_POOL_BYTES,
            parse_concurrency=Settings.REGISTRY_PARSE_CONCURRENCY,
            memory_headroom_reserve_bytes=(
                Settings.REGISTRY_MEMORY_HEADROOM_RESERVE_BYTES
            ),
        )


@dataclass(frozen=True)
class RegistryBudgetStats:
    """A consistent snapshot of the accounting counters."""

    retained_bytes: int
    reserved_retained_bytes: int
    transient_parse_bytes: int
    active_parses: int
    parse_concurrency: int
    retained_limit: int
    transient_limit: int
    combined_limit: int

    @property
    def accounted_bytes(self) -> int:
        return (
            self.retained_bytes
            + self.reserved_retained_bytes
            + self.transient_parse_bytes
        )


class RegistryAdmissionError(Exception):
    """A deterministic admission refusal carrying its HTTP status.

    ``status_code`` is 413 when the estimate can never fit the configured
    limits, 409 when a replacement is permanently impossible because the
    session's old and new registry charges cannot coexist, and 429 for
    temporary capacity or parse-slot contention. A ``retry_after`` value
    (seconds) is set on every temporary 429, never on a permanent 413 or 409
    refusal.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retry_after: int | None = None,
        estimate: RegistryEstimate | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.retry_after = retry_after
        self.estimate = estimate
        super().__init__(message)


class RegistryReplacementRequiresClear(RegistryAdmissionError):
    """A replacement cannot coexist with the session's existing registry.

    The old registry must stay charged while the new one is parsed. When the
    two charges cannot coexist even in an otherwise empty budget -- with no
    other session and no other reservation -- the replacement is permanently
    impossible in the current session state. It is not retryable; the caller
    must explicitly clear the existing registry first. The old registry,
    revision, results and accounting are untouched.

    A replacement that is only blocked by capacity held elsewhere (another
    session, another parse, or the accounting of an expired session awaiting
    cleanup) is *not* this error: it is a retryable 429.
    """

    def __init__(self, estimate: RegistryEstimate, reason: str) -> None:
        super().__init__(
            409,
            "replacement_requires_clear",
            f"Cannot replace this session's custom registry: {reason}. The "
            "existing registry must be explicitly cleared before this mapping "
            "can be uploaded for this session.",
            retry_after=None,
            estimate=estimate,
        )


class RegistryReservation:
    """An active parse reservation; commit it or abort it exactly once.

    The reservation holds both the transient parse charge and the eventual
    retained charge. It also owns the serialised parse slot. ``abort`` is
    idempotent and is called by the lifecycle on every failure path.
    """

    __slots__ = ("_active", "_budget", "_committed", "_estimate")

    def __init__(self, budget: RegistryBudget, estimate: RegistryEstimate) -> None:
        self._budget = budget
        self._estimate = estimate
        self._active = True
        self._committed = False

    @property
    def estimate(self) -> RegistryEstimate:
        return self._estimate

    @property
    def retained_bytes(self) -> int:
        return self._estimate.retained_bytes

    @property
    def transient_bytes(self) -> int:
        return self._estimate.parse_bytes

    @property
    def active(self) -> bool:
        return self._active

    @property
    def committed(self) -> bool:
        return self._committed

    def commit(self) -> None:
        """Move the reservation into permanent retained accounting."""
        self._budget._finish_reservation(self, commit=True)

    def abort(self) -> None:
        """Release every charge; harmless when already committed/aborted."""
        self._budget._finish_reservation(self, commit=False)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._active:
            self.abort()


class RegistryBudget:
    """Process-wide, thread-safe accounting for custom registries.

    All counters and the parse-slot state are guarded by one condition. A
    reservation is admitted atomically: it needs both a free parse slot and
    enough retained/transient/combined capacity, so concurrent requests can
    never collectively oversubscribe the configured pools.
    """

    def __init__(
        self,
        config: RegistryBudgetConfig | None = None,
        *,
        memory_headroom: Callable[[], int | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config or RegistryBudgetConfig.from_settings()
        self._memory_headroom = (
            default_memory_headroom
            if memory_headroom is None
            else memory_headroom
        )
        self._clock = clock
        self._condition = threading.Condition(threading.Lock())
        self._retained = 0
        self._reserved_retained = 0
        self._transient = 0
        self._active_parses = 0

    @property
    def config(self) -> RegistryBudgetConfig:
        return self._config

    def stats(self) -> RegistryBudgetStats:
        with self._condition:
            return RegistryBudgetStats(
                retained_bytes=self._retained,
                reserved_retained_bytes=self._reserved_retained,
                transient_parse_bytes=self._transient,
                active_parses=self._active_parses,
                parse_concurrency=self._config.parse_concurrency,
                retained_limit=self._config.retained_bytes,
                transient_limit=self._config.transient_bytes,
                combined_limit=self._config.combined_bytes,
            )

    def _permanent_error(
        self, estimate: RegistryEstimate
    ) -> RegistryAdmissionError | None:
        """413 when the estimate can never fit any configuration state."""
        if estimate.retained_bytes > self._config.retained_bytes:
            return RegistryAdmissionError(
                413,
                "registry_too_large",
                f"This mapping needs an estimated {_mib(estimate.retained_bytes)} "
                f"of retained registry memory; the configured retained budget "
                f"is {_mib(self._config.retained_bytes)}.",
                estimate=estimate,
            )
        if estimate.parse_bytes > self._config.transient_bytes:
            return RegistryAdmissionError(
                413,
                "registry_too_large",
                f"This mapping needs an estimated {_mib(estimate.parse_bytes)} "
                f"to parse; the configured transient parse cap is "
                f"{_mib(self._config.transient_bytes)}.",
                estimate=estimate,
            )
        if estimate.total_bytes > self._config.combined_bytes:
            return RegistryAdmissionError(
                413,
                "registry_too_large",
                f"This mapping needs an estimated {_mib(estimate.total_bytes)} "
                f"of the combined custom-mapping pool; the configured pool is "
                f"{_mib(self._config.combined_bytes)}.",
                estimate=estimate,
            )
        return None

    def _replacement_impossible(
        self, estimate: RegistryEstimate, replacing_retained_bytes: int
    ) -> str | None:
        """Why the session's old and new registry charges cannot coexist.

        The answer depends only on the session's own old registry and on the
        new estimate -- never on other sessions, other reservations or the
        current accounting. A replacement refused for this reason can never
        succeed in this session, while a replacement blocked by somebody
        else's capacity is merely temporary.
        """
        if (
            replacing_retained_bytes + estimate.retained_bytes
            > self._config.retained_bytes
        ):
            return (
                "the existing registry and the new mapping together need more "
                f"than the {_mib(self._config.retained_bytes)} retained "
                "registry budget"
            )
        if (
            replacing_retained_bytes + estimate.total_bytes
            > self._config.combined_bytes
        ):
            return (
                "the existing registry and the new mapping together need more "
                f"than the {_mib(self._config.combined_bytes)} combined "
                "custom-mapping pool"
            )
        return None

    def _capacity_reason(self, estimate: RegistryEstimate) -> str | None:
        """A human-readable temporary capacity reason, or ``None`` if it fits.

        The reason describes the *current* accounting: other sessions, other
        reservations and the transient charge of a running parse. It never
        describes the session's own old registry, which is handled by
        :meth:`_replacement_impossible`.
        """
        if (
            self._retained
            + self._reserved_retained
            + estimate.retained_bytes
            > self._config.retained_bytes
        ):
            return "retained registry capacity is currently in use"
        if self._transient + estimate.parse_bytes > self._config.transient_bytes:
            return "transient parse capacity is currently in use"
        if (
            self._retained
            + self._reserved_retained
            + self._transient
            + estimate.total_bytes
            > self._config.combined_bytes
        ):
            return "the combined custom-mapping pool is currently in use"
        return None

    def _headroom_allows(self, estimate: RegistryEstimate) -> bool:
        try:
            headroom = self._memory_headroom()
        except Exception:  # noqa: BLE001 - unknown probe is not an outage
            return True  # an unavailable probe is unknown, never an outage
        if headroom is None:
            return True
        required = (
            estimate.total_bytes + self._config.memory_headroom_reserve_bytes
        )
        return required <= headroom

    def reserve(
        self,
        estimate: RegistryEstimate,
        *,
        wait_seconds: float = 0.0,
        replacing_retained_bytes: int = 0,
    ) -> RegistryReservation:
        """Reserve a parse slot plus retained/transient capacity.

        Raises :class:`RegistryAdmissionError` with 413 for an estimate that
        can never fit, 409 when the session's old and new registry charges
        cannot coexist even in an otherwise empty budget, and 429 for
        temporary exhaustion or parse-slot contention.

        The 409 is decided from the session's own charges only: it means the
        replacement is permanently impossible until the caller clears the
        existing registry. Capacity that is in use by *other* sessions or by
        another parse is temporary and is refused with a retryable 429.

        A busy parse slot is waited for before capacity is judged, because the
        in-flight parse's own transient charge may be what is blocking
        admission. At most ``wait_seconds`` is spent waiting; the wait
        happens on the condition, never as a busy loop.
        """
        wait_seconds = max(0.0, float(wait_seconds))
        if replacing_retained_bytes < 0:
            raise ValueError("replacing_retained_bytes must be non-negative")
        permanent = self._permanent_error(estimate)
        if permanent is not None:
            raise permanent
        if replacing_retained_bytes:
            impossible = self._replacement_impossible(
                estimate, replacing_retained_bytes)
            if impossible is not None:
                raise RegistryReplacementRequiresClear(estimate, impossible)

        deadline = self._clock() + wait_seconds
        with self._condition:
            while True:
                if self._active_parses >= self._config.parse_concurrency:
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        raise RegistryAdmissionError(
                            429,
                            "parse_busy",
                            "Another custom mapping is being parsed. Retry "
                            "after the indicated delay.",
                            retry_after=max(
                                DEFAULT_RETRY_AFTER_SECONDS,
                                math.ceil(wait_seconds or 1.0),
                            ),
                            estimate=estimate,
                        )
                    self._condition.wait(remaining)
                    continue

                if not self._headroom_allows(estimate):
                    raise RegistryAdmissionError(
                        429,
                        "capacity_unavailable",
                        "The server does not currently have enough live memory "
                        "headroom to parse this mapping. Retry shortly.",
                        retry_after=DEFAULT_RETRY_AFTER_SECONDS,
                        estimate=estimate,
                    )
                capacity = self._capacity_reason(estimate)
                if capacity is not None:
                    raise RegistryAdmissionError(
                        429,
                        "capacity_unavailable",
                        f"Cannot admit this mapping: {capacity}. Retry shortly.",
                        retry_after=DEFAULT_RETRY_AFTER_SECONDS,
                        estimate=estimate,
                    )

                self._active_parses += 1
                self._reserved_retained += estimate.retained_bytes
                self._transient += estimate.parse_bytes
                return RegistryReservation(self, estimate)

    def _finish_reservation(
        self, reservation: RegistryReservation, *, commit: bool
    ) -> None:
        with self._condition:
            if not reservation._active:
                return
            estimate = reservation._estimate
            self._reserved_retained -= estimate.retained_bytes
            self._transient -= estimate.parse_bytes
            self._active_parses -= 1
            reservation._active = False
            if commit:
                self._retained += estimate.retained_bytes
                reservation._committed = True
            self._condition.notify_all()

    def release_retained(self, retained_bytes: int) -> None:
        """Release a retired registry's permanent charge (once per registry)."""
        if retained_bytes < 0:
            raise ValueError("retained_bytes must be non-negative")
        with self._condition:
            if retained_bytes > self._retained:
                raise RuntimeError(
                    f"attempted to release {retained_bytes} retained bytes "
                    f"but only {self._retained} are accounted")
            self._retained -= retained_bytes
            self._condition.notify_all()


def _mib(value: int) -> str:
    return f"{value / MIB:.1f} MiB"


# ---------------------------------------------------------------------------
# Registry references and leases
# ---------------------------------------------------------------------------


class RegistryLease:
    """An execution's active reference to one committed registry.

    Releasing is idempotent. The registry object stays valid even after it is
    retired; the lease only protects its accounting until the run finishes.
    """

    __slots__ = (
        "_digest",
        "_entry",
        "_lock",
        "_registry",
        "_released",
        "_revision",
    )

    def __init__(self, entry: RegistryEntry) -> None:
        self._entry = entry
        self._registry = entry.registry
        self._revision = entry.revision
        self._digest = entry.digest
        self._released = False
        self._lock = threading.Lock()

    @property
    def registry(self) -> ChromosomeRegistry:
        return self._registry

    @property
    def revision(self) -> str:
        return self._revision

    @property
    def digest(self) -> str:
        return self._digest

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        self._entry.release_lease()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class RegistryEntry:
    """One committed registry plus its lease/accounting state."""

    __slots__ = (
        "_budget",
        "_leases",
        "_lock",
        "_released",
        "_retired",
        "digest",
        "registry",
        "retained_bytes",
        "revision",
    )

    def __init__(
        self,
        registry: ChromosomeRegistry,
        digest: str,
        revision: str,
        retained_bytes: int,
        budget: RegistryBudget,
    ) -> None:
        self.registry = registry
        self.digest = digest
        self.revision = revision
        self.retained_bytes = retained_bytes
        self._budget = budget
        self._leases = 0
        self._retired = False
        self._released = False
        self._lock = threading.Lock()

    @property
    def leases(self) -> int:
        with self._lock:
            return self._leases

    @property
    def retired(self) -> bool:
        with self._lock:
            return self._retired

    def acquire(self) -> RegistryLease | None:
        with self._lock:
            if self._retired:
                return None
            self._leases += 1
        return RegistryLease(self)

    def retire(self) -> None:
        with self._lock:
            self._retired = True
            self._release_if_unused_locked()

    def release_lease(self) -> None:
        with self._lock:
            if self._leases <= 0:
                raise RuntimeError(
                    "custom-registry lease released without a matching acquire")
            self._leases -= 1
            self._release_if_unused_locked()

    def _release_if_unused_locked(self) -> None:
        if self._retired and self._leases == 0 and not self._released:
            self._released = True
            self._budget.release_retained(self.retained_bytes)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class RegistryLifecycleError(Exception):
    """Base class for a registry-lifecycle refusal."""

    status_code = 409
    code = "registry_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class RegistrySessionExpired(RegistryLifecycleError):
    """The session is no longer live; nothing may be committed for it."""

    status_code = 409
    code = "session_expired"


class RegistryWriteConflict(RegistryLifecycleError):
    """A later-started write already committed for this session."""

    status_code = 409
    code = "revision_conflict"


class RegistryNotAvailable(RegistryLifecycleError):
    """No committed registry is available for this session/revision."""

    status_code = 404
    code = "registry_not_available"


@dataclass(frozen=True)
class RegistryWriteTicket:
    """Arrival-order stamp reserved before parsing a registry write."""

    token: str
    stamp: int


@dataclass(frozen=True)
class RegistryWriteResult:
    revision: str
    digest: str
    reused: bool
    registry: ChromosomeRegistry


@dataclass
class _RegistrySlot:
    token: str
    entry: RegistryEntry | None = None
    write_seq: int = 0
    write_done: int = 0
    last_used: float = 0.0


def _new_revision() -> str:
    return secrets.token_urlsafe(16)


class RegistryLifecycle:
    """Session-scoped committed registries with leases and write ordering.

    ``is_live(token)`` is the commit-time authority for session liveness; it
    must not mutate session state or invoke eviction callbacks. The default
    treats any non-empty token as live, which keeps the class usable without a
    :class:`~streamlit_app.api_sessions.SessionStore` (tests inject their own).
    """

    def __init__(
        self,
        budget: RegistryBudget | None = None,
        *,
        is_live: Callable[[str], bool] | None = None,
        loader: Callable[[bytes], ChromosomeRegistry] | None = None,
        new_revision: Callable[[], str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._budget = budget or RegistryBudget()
        self._is_live = is_live or (lambda token: bool(token))
        self._loader = loader or load_custom_registry
        self._new_revision = new_revision or _new_revision
        self._clock = clock
        self._lock = threading.RLock()
        self._slots: dict[str, _RegistrySlot] = {}

    @property
    def budget(self) -> RegistryBudget:
        return self._budget

    def stats(self) -> RegistryBudgetStats:
        return self._budget.stats()

    def reserve_write(self, token: str) -> RegistryWriteTicket | None:
        """Reserve an arrival-order stamp for one registry write.

        Returns ``None`` for a not-yet-materialised anonymous session, matching
        the dataset write-order contract: it allocates no registry state. It
        also refuses expired, evicted or otherwise unknown tokens without
        creating a slot, and removes any stale slot left for such a token so a
        stream of invalid requests cannot grow lifecycle state.
        """
        if not token:
            return None
        moment = self._clock()
        with self._lock:
            if not self._is_live(token):
                self._drop_slot_locked(token)
                return None
            slot = self._slots.get(token)
            if slot is None:
                slot = _RegistrySlot(token=token, last_used=moment)
                self._slots[token] = slot
            slot.write_seq += 1
            slot.last_used = moment
            return RegistryWriteTicket(token, slot.write_seq)

    def _reserve_with_expiry_sweep(
        self,
        estimate: RegistryEstimate,
        *,
        wait_seconds: float,
        replacing_retained_bytes: int,
    ) -> RegistryReservation:
        """Admit once, then sweep expired sessions and retry once on 429.

        Only a *temporary* capacity refusal is swept and retried: a busy
        parse slot, a permanent 409 and a permanent 413 are re-raised
        unchanged, because neither waiting nor sweeping can help them.

        The sweep is the same side-effect-free-liveness check used elsewhere:
        it drops only sessions the injected authority reports as not live. It
        never evicts a live session to make room for another one.
        """
        try:
            return self._budget.reserve(
                estimate,
                wait_seconds=wait_seconds,
                replacing_retained_bytes=replacing_retained_bytes,
            )
        except RegistryAdmissionError as exc:
            if exc.code != "capacity_unavailable":
                raise
            self.sweep()
            return self._budget.reserve(
                estimate,
                wait_seconds=wait_seconds,
                replacing_retained_bytes=replacing_retained_bytes,
            )

    def register(
        self,
        token: str,
        content: bytes,
        *,
        ticket: RegistryWriteTicket | None = None,
        wait_seconds: float = DEFAULT_PARSE_WAIT_SECONDS,
    ) -> RegistryWriteResult:
        """Commit a custom mapping for ``token`` (build or reuse by digest).

        Identical content reuses the committed revision without parsing. A
        different digest is parsed under the serialised slot and replaces the
        previous registry, retiring it (memory stays accounted while leases
        remain). A replacement whose own old and new charges cannot coexist
        even in an otherwise empty budget is refused with
        :class:`RegistryReplacementRequiresClear` and changes nothing; a
        replacement that is only blocked by capacity held elsewhere is
        refused with a retryable 429 instead. Any failure, supersession or
        expired session releases the reservation and never advances the
        high-water mark.
        """
        data = _as_bytes(content)
        if not token:
            raise RegistrySessionExpired(
                "a custom registry requires a stored session")
        if ticket is not None and ticket.token != token:
            raise ValueError("write ticket belongs to another session")
        if ticket is None:
            # Callers that did not reserve before parsing are still ordered by
            # the moment they entered this write.
            ticket = self.reserve_write(token)
        digest = hashlib.sha256(data).hexdigest()
        moment = self._clock()

        # Fast path: identical content already committed -> no parse at all.
        with self._lock:
            if not self._is_live(token):
                self._drop_slot_locked(token)
                raise RegistrySessionExpired(
                    "the session expired before the registry write committed")
            slot = self._slots.get(token)
            if slot is not None and self._superseded(slot, ticket):
                raise RegistryWriteConflict(
                    "a later-started registry write already committed for this "
                    "session; this older write was discarded")
            if (
                slot is not None
                and slot.entry is not None
                and slot.entry.digest == digest
            ):
                self._commit_stamp_locked(slot, ticket, moment)
                return RegistryWriteResult(
                    revision=slot.entry.revision,
                    digest=digest,
                    reused=True,
                    registry=slot.entry.registry,
                )
            previous_retained = (
                slot.entry.retained_bytes
                if slot is not None and slot.entry is not None
                else 0
            )

        estimate = estimate_registry(
            count_custom_mapping_rows(data), len(data))
        reservation = self._reserve_with_expiry_sweep(
            estimate,
            wait_seconds=wait_seconds,
            replacing_retained_bytes=previous_retained,
        )
        try:
            registry = self._loader(data)

            with self._lock:
                if not self._is_live(token):
                    # A stale completion must not resurrect an evicted session.
                    self._drop_slot_locked(token)
                    raise RegistrySessionExpired(
                        "the session expired while the registry was being "
                        "parsed; nothing was committed")
                slot = self._slots.get(token)
                if slot is None:
                    slot = _RegistrySlot(token=token, last_used=moment)
                    self._slots[token] = slot
                if self._superseded(slot, ticket):
                    raise RegistryWriteConflict(
                        "a later-started registry write already committed for "
                        "this session; this older write was discarded")
                if (
                    slot.entry is not None
                    and slot.entry.digest == digest
                ):
                    # Someone committed identical content while we parsed.
                    reservation.abort()
                    self._commit_stamp_locked(slot, ticket, moment)
                    return RegistryWriteResult(
                        revision=slot.entry.revision,
                        digest=digest,
                        reused=True,
                        registry=slot.entry.registry,
                    )

                revision = self._new_revision()
                new_entry = RegistryEntry(
                    registry,
                    digest,
                    revision,
                    reservation.retained_bytes,
                    self._budget,
                )
                reservation.commit()
                previous = slot.entry
                slot.entry = new_entry
                slot.last_used = moment
                if previous is not None:
                    previous.retire()
                self._commit_stamp_locked(slot, ticket, moment)
                return RegistryWriteResult(
                    revision=revision,
                    digest=digest,
                    reused=False,
                    registry=registry,
                )
        finally:
            # Idempotent: a committed reservation is left untouched, every
            # error/cancellation path releases parse and retained charges.
            reservation.abort()

    def clear(
        self,
        token: str,
        *,
        ticket: RegistryWriteTicket | None = None,
        expected_revision: str | None = None,
    ) -> bool:
        """Remove the session's registry and release it when unleased.

        A mismatch of ``expected_revision`` is a conflict and commits nothing.
        Clearing leaves a tombstone slot so an in-flight earlier write cannot
        resurrect the registry. Returns ``True`` when a registry was removed.
        """
        if not token:
            raise RegistrySessionExpired(
                "a custom registry requires a stored session")
        if ticket is not None and ticket.token != token:
            raise ValueError("write ticket belongs to another session")
        if ticket is None:
            ticket = self.reserve_write(token)
        moment = self._clock()
        with self._lock:
            if not self._is_live(token):
                self._drop_slot_locked(token)
                raise RegistrySessionExpired(
                    "the session expired before the registry clear committed")
            slot = self._slots.get(token)
            if slot is None:
                slot = _RegistrySlot(token=token, last_used=moment)
                self._slots[token] = slot
            if self._superseded(slot, ticket):
                raise RegistryWriteConflict(
                    "a later-started registry write already committed for this "
                    "session; this older clear was discarded")
            current = slot.entry.revision if slot.entry is not None else None
            if expected_revision is not None and current != expected_revision:
                raise RegistryWriteConflict(
                    "the committed registry revision no longer matches the "
                    "revision this request owns; nothing was cleared")
            removed = slot.entry is not None
            if slot.entry is not None:
                slot.entry.retire()
                slot.entry = None
            slot.last_used = moment
            self._commit_stamp_locked(slot, ticket, moment)
            return removed

    def acquire(
        self,
        token: str,
        *,
        expected_revision: str | None = None,
    ) -> RegistryLease:
        """Take an active execution lease on the committed registry."""
        moment = self._clock()
        with self._lock:
            if not self._is_live(token):
                self._drop_slot_locked(token)
                raise RegistrySessionExpired(
                    "the session expired before the registry could be used")
            slot = self._slots.get(token)
            if slot is None or slot.entry is None:
                raise RegistryNotAvailable(
                    "no custom registry is loaded for this session")
            if (
                expected_revision is not None
                and slot.entry.revision != expected_revision
            ):
                raise RegistryWriteConflict(
                    "the committed registry revision no longer matches the "
                    "revision this execution owns")
            lease = slot.entry.acquire()
            if lease is None:  # unreachable while the slot lock is held
                raise RegistryNotAvailable(
                    "the custom registry was retired before it could be used")
            slot.last_used = moment
            return lease

    def current_revision(self, token: str) -> str | None:
        with self._lock:
            if not token or not self._is_live(token):
                return None
            slot = self._slots.get(token)
            return slot.entry.revision if slot and slot.entry else None

    def current_registry(self, token: str) -> ChromosomeRegistry | None:
        with self._lock:
            if not token or not self._is_live(token):
                return None
            slot = self._slots.get(token)
            return slot.entry.registry if slot and slot.entry else None

    def release_session(self, token: str) -> None:
        """Release a session's slot (session expiry or LRU eviction)."""
        with self._lock:
            self._drop_slot_locked(token)

    def sweep(self, *, live: Callable[[str], bool] | None = None) -> int:
        """Drop slots for sessions that are no longer live; returns the count.

        Used as a safety net when the session store does not call the eviction
        callback (or when it is configured independently). It never evicts a
        live session's registry to make room for another one.
        """
        checker = live or self._is_live
        with self._lock:
            dead = [token for token in self._slots if not checker(token)]
            for token in dead:
                self._drop_slot_locked(token)
            return len(dead)

    def __len__(self) -> int:
        with self._lock:
            return sum(1 for slot in self._slots.values() if slot.entry is not None)

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _superseded(
        slot: _RegistrySlot, ticket: RegistryWriteTicket | None
    ) -> bool:
        return ticket is not None and ticket.stamp < slot.write_done

    @staticmethod
    def _commit_stamp_locked(
        slot: _RegistrySlot,
        ticket: RegistryWriteTicket | None,
        moment: float,
    ) -> None:
        if ticket is not None and ticket.stamp > slot.write_done:
            slot.write_done = ticket.stamp
        slot.last_used = moment

    def _drop_slot_locked(self, token: str) -> None:
        slot = self._slots.pop(token, None)
        if slot is not None and slot.entry is not None:
            slot.entry.retire()
            slot.entry = None
