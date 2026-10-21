"""Session-scoped custom chromosome registries over HTTP (M2.2b).

This module is the HTTP boundary for the custom-registry lifecycle in
:mod:`streamlit_app.core.chrom_registry.lifecycle`. It maps the lifecycle's
admission, write-order, lease and liveness semantics onto the endpoint
contract and never re-implements them: the budget, the estimators and the
lifecycle itself are reused unchanged, and the scientific registry
(:func:`~streamlit_app.core.chrom_registry.load_custom_registry`) and the
normalization code are not touched at all. A custom mapping becomes an
ordinary immutable ``ChromosomeRegistry`` that the shared runtime resolver
and normalizer use exactly as they use a bundled assembly.

Endpoint contract
-----------------

``POST /api/registry``
    Upload a custom chromosome mapping (multipart field ``file``). The
    mapping is validated structurally and admitted against the resource
    budget; it replaces the session's registry, or -- for identical content
    -- reuses the committed revision without parsing again.

``GET /api/registry``
    The current session's registry *metadata*. The mapping content is never
    returned: only the revision, the content digest, the display name and
    the number of sequences.

``DELETE /api/registry``
    Revision-scoped clear. The revision the client owns must be named, so a
    clear can never silently discard a registry another tab replaced.

Error contract
--------------

The endpoints use the repository's existing error conventions:

============  ==========================================================
Status        Meaning
============  ==========================================================
400           the mapping is structurally invalid (the issues are
              listed; the content is never echoed in bulk)
409           the revision is stale, the session expired, or the
              replacement is permanently impossible in this session
413           the mapping exceeds a resource limit (bytes, rows, or the
              retained/transient/combined budget)
428           a registry exists and the request did not name the
              revision it owns
429           temporary capacity or parse-slot contention, with
              ``Retry-After``
============  ==========================================================

Every error body is ``{"code", "message", "stale"}`` -- the shape the React
frontend already understands for revision conflicts -- with the additional
``issues``/``more`` fields for an invalid mapping.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import anyio
from anyio import CapacityLimiter
from fastapi import HTTPException, Request, UploadFile

from streamlit_app.api_sessions import Session
from streamlit_app.core.chrom_registry import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_ROWS,
    DEFAULT_PARSE_WAIT_SECONDS,
    CustomRegistryError,
    RegistryAdmissionError,
    RegistryLease,
    RegistryLifecycle,
    RegistryLifecycleError,
    RegistryNotAvailable,
    RegistrySessionExpired,
    RegistryWriteConflict,
    count_custom_mapping_rows,
)

_logger = logging.getLogger(__name__)

#: The role name a registry error reports in its ``stale`` list, matching the
#: dataset sides ("query"/"annot") of the existing revision contract.
REGISTRY_ROLE = "registry"

#: Bounded wait for the serialised custom-mapping parse slot before the
#: request is refused with 429 ``parse_busy``. The parse slot itself belongs
#: to the lifecycle; this is only how long a request waits for it.
PARSE_WAIT_SECONDS = DEFAULT_PARSE_WAIT_SECONDS

#: Read size for the uploaded mapping.
_CHUNK_BYTES = 1024 * 1024


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def registry_error(
    status_code: int,
    code: str,
    message: str,
    *,
    stale: Optional[List[str]] = None,
    retry_after: Optional[int] = None,
    **extra: Any,
) -> HTTPException:
    """One registry error, in the shape the frontend already understands."""
    detail: Dict[str, Any] = {
        "code": code,
        "message": message,
        "stale": list(stale or ()),
    }
    detail.update(extra)
    headers = {"Retry-After": str(retry_after)} if retry_after else None
    return HTTPException(
        status_code=status_code, detail=detail, headers=headers)


def _issues_payload(error: CustomRegistryError) -> List[Dict[str, Any]]:
    """The structural problems of an invalid mapping, as plain data."""
    return [
        {
            "code": issue.code,
            "message": issue.message,
            "rows": list(issue.rows),
            "columns": list(issue.columns),
        }
        for issue in error.issues
    ]


def translate_registry_error(exc: BaseException) -> HTTPException:
    """Map a lifecycle or loader failure onto the endpoint's error contract.

    The lifecycle has already decided *whether* a refusal is permanent
    (413, 409) or temporary (429) and how long to wait before a retry, so
    this function only translates: it never re-decides an admission.
    """
    if isinstance(exc, RegistryAdmissionError):
        # 413 (permanently too large), 409 (permanently impossible
        # replacement) or 429 (temporary capacity/parse contention).
        return registry_error(
            exc.status_code,
            exc.code,
            str(exc),
            retry_after=exc.retry_after,
        )
    if isinstance(exc, RegistrySessionExpired):
        return registry_error(
            409, "session_expired", str(exc), stale=[REGISTRY_ROLE])
    if isinstance(exc, RegistryWriteConflict):
        return registry_error(
            409, "revision_conflict", str(exc), stale=[REGISTRY_ROLE])
    if isinstance(exc, RegistryNotAvailable):
        # The client named a registry revision that this session does not
        # have: the same "claimed revision absent" case as a dataset.
        return registry_error(
            409, "revision_conflict", str(exc), stale=[REGISTRY_ROLE])
    if isinstance(exc, CustomRegistryError):
        return registry_error(
            400,
            "invalid_mapping",
            str(exc),
            issues=_issues_payload(exc),
            more=exc.more,
        )
    if isinstance(exc, RegistryLifecycleError):
        return registry_error(
            409, exc.code, str(exc), stale=[REGISTRY_ROLE])
    raise exc


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def custom_registry_payload(
    revision: str,
    digest: str,
    name: str,
    row_count: int,
) -> Dict[str, Any]:
    """The public metadata of a custom mapping (never its content)."""
    return {
        "source": "custom",
        "revision": revision,
        "digest": digest,
        "name": name,
        "row_count": row_count,
        # A custom mapping is a source of chromosome identity, not a genome
        # assembly: it never reports an assembly identity (SPEC 5.1.1 §7).
        "assembly": None,
    }


def no_registry_payload() -> Dict[str, Any]:
    """The provenance of a run that normalized no chromosome names."""
    return {
        "source": "none",
        "revision": None,
        "digest": None,
        "name": None,
        "row_count": None,
        "assembly": None,
    }


def bundled_registry_payload(assembly_id: str, name: str) -> Dict[str, Any]:
    """The provenance of a run that normalized names with a bundled
    assembly."""
    return {
        "source": "bundled",
        "revision": None,
        "digest": None,
        "name": name,
        "row_count": None,
        "assembly": assembly_id,
    }


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


async def _read_mapping(file: UploadFile, *, max_bytes: int) -> bytes:
    """Read the uploaded mapping, refusing input above the byte limit.

    The limit is the registry's own resource limit (SPEC 5.1.1 §8), not the
    generic upload limit: an oversized mapping is refused before it is
    parsed, and the bytes are never held in memory beyond the limit.
    """
    chunks: List[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise registry_error(
                413,
                "registry_too_large",
                f"The custom chromosome mapping is larger than the "
                f"{max_bytes // (1024 * 1024)} MiB limit.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def upload_custom_registry(
    request: Request,
    file: UploadFile,
    session: Session,
    *,
    lifecycle: RegistryLifecycle,
    materialize: Callable[[Request, Session], Session],
    parse_limiter: Callable[[], CapacityLimiter],
    release_session: Optional[Callable[[Request, Session], None]] = None,
    wait_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """Validate, admit and commit a custom mapping for this session.

    The mapping is parsed by the lifecycle under the serialised parse slot
    and committed only if the session is still live and no later-started
    write has committed meanwhile. Identical content reuses the committed
    revision without parsing again.
    """
    # Arrival-order stamp (the issue #55 pattern): the stamp is taken
    # before the slow parse, so a write that started earlier can never
    # overwrite one that started later. An anonymous request owns no
    # session yet and cannot race with anything, so it is stamped when its
    # session is created.
    ticket = lifecycle.reserve_write(session.token) if session.token else None

    content = await _read_mapping(file, max_bytes=DEFAULT_MAX_BYTES)
    rows = count_custom_mapping_rows(content)
    if rows > DEFAULT_MAX_ROWS:
        raise registry_error(
            413,
            "registry_too_large",
            f"The custom chromosome mapping has {rows:,} rows; the limit is "
            f"{DEFAULT_MAX_ROWS:,} sequences.",
        )

    # First state write: the registry belongs to a session, so the session
    # is materialised here. The mapping is parsed inside the lifecycle (the
    # admission must be decided before a mapping is parsed), so a mapping
    # that is refused afterwards gives its session slot back below.
    created = not session.token
    session = materialize(request, session)

    def _register():
        return lifecycle.register(
            session.token,
            content,
            ticket=ticket,
            wait_seconds=(
                PARSE_WAIT_SECONDS if wait_seconds is None else wait_seconds),
        )

    try:
        # The parse is CPU- and memory-heavy: it runs on a worker thread
        # (borrowing from the parsing limiter, not from the default
        # thread-pool limiter) so the event loop keeps serving other
        # sessions while this mapping is parsed (issue #55).
        result = await anyio.to_thread.run_sync(
            _register, limiter=parse_limiter())
    except Exception as exc:
        if created and release_session is not None:
            # Nothing was stored: a refused write must not consume session
            # capacity (review finding N4).
            if lifecycle.current_revision(session.token) is None:
                release_session(request, session)
        raise translate_registry_error(exc) from None

    # A change of the mapping content invalidates every result derived from
    # the previous content (SPEC 5.1.1 §9). Identical content changes
    # nothing, so the result stays valid.
    invalidate_stale_results(session, current_revision=result.revision)
    return {
        "status": "success",
        "registry": custom_registry_payload(
            result.revision,
            result.digest,
            result.registry.name,
            len(result.registry),
        ),
        "reused": result.reused,
    }


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def current_registry(
    session: Session,
    *,
    lifecycle: RegistryLifecycle,
) -> Dict[str, Any]:
    """The session's registry metadata, or ``None`` when it has none.

    A read never allocates a session: an anonymous request is served by a
    throwaway session and simply sees no registry.
    """
    metadata = lifecycle.current_metadata(session.token)
    if metadata is None:
        return {"status": "success", "registry": None}
    return {
        "status": "success",
        "registry": custom_registry_payload(
            metadata.revision,
            metadata.digest,
            metadata.name,
            metadata.row_count,
        ),
    }


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------


def clear_custom_registry(
    session: Session,
    *,
    lifecycle: RegistryLifecycle,
    registry_rev: Optional[str] = None,
) -> Dict[str, Any]:
    """Remove the session's registry, for the revision the caller names.

    The revision contract mirrors the dataset clear: nothing stored and no
    revision named is a no-op, a stored registry without a named revision is
    refused with 428, and a stale revision is refused with 409 -- in both
    cases nothing is removed.
    """
    if not session.token:
        # An anonymous request owns no registry: a no-op removal is not a
        # write, so it allocates no session (review finding N4).
        return {"status": "success", "cleared": False, "registry": None}

    ticket = lifecycle.reserve_write(session.token)
    try:
        outcome = lifecycle.clear_for_revision(
            session.token, ticket=ticket, expected_revision=registry_rev)
    except Exception as exc:
        raise translate_registry_error(exc) from None

    if outcome.reason == "revision_required":
        raise registry_error(
            428,
            "revision_required",
            "registry_rev is required: state which custom chromosome "
            "mapping revision this request is for (returned when the "
            "mapping was uploaded).",
            stale=[REGISTRY_ROLE],
        )
    if outcome.reason == "revision_mismatch":
        raise registry_error(
            409,
            "revision_conflict",
            "Not cleared: the stored custom chromosome mapping is a newer "
            "revision (replaced in another tab of this browser session).",
            stale=[REGISTRY_ROLE],
        )

    # A result derived from the cleared mapping is stale the moment the
    # mapping is discarded (SPEC 5.1.1 §9). A result derived from anything
    # else is left alone.
    invalidate_stale_results(session, current_revision=None)
    return {"status": "success", "cleared": outcome.cleared, "registry": None}


# ---------------------------------------------------------------------------
# Result invalidation
# ---------------------------------------------------------------------------


def invalidate_stale_results(
    session: Session,
    *,
    current_revision: Optional[str],
) -> bool:
    """Drop a stored result that was derived from a *different* custom map.

    Only custom-registry results are affected: a bundled-assembly result or
    a keep-original-names result is unrelated to the session's custom
    mapping and stays valid. Returns whether a result was dropped.
    """
    with session.lock:
        result = session.data.get("result")
        if result is None:
            return False
        provenance = result.get("registry")
        if not provenance or provenance.get("source") != "custom":
            return False
        if provenance.get("revision") == current_revision:
            return False
        session.data.pop("result", None)
        return True


# ---------------------------------------------------------------------------
# Execution binding
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CustomRegistryBinding:
    """One execution's binding to a committed custom registry.

    The binding snapshots the registry's identity and holds a lease, so the
    registry's accounting survives until the run has finished even if
    another tab replaces or clears the mapping meanwhile.
    """

    token: str
    lease: RegistryLease
    revision: str
    digest: str
    name: str
    row_count: int

    @property
    def registry(self):
        """The immutable registry the run normalizes with."""
        return self.lease.registry

    def provenance(self) -> Dict[str, Any]:
        """The provenance recorded with the run's result."""
        return {
            "source": "custom",
            "revision": self.revision,
            "digest": self.digest,
            "name": self.name,
            "row_count": self.row_count,
            "assembly": None,
        }

    def release(self) -> None:
        """Release the lease (idempotent)."""
        self.lease.release()


def bind_custom_registry(
    lifecycle: RegistryLifecycle,
    token: str,
    registry_rev: str,
) -> CustomRegistryBinding:
    """Lease the session's custom registry for one execution.

    The lease is taken for exactly the revision the client named: a missing
    registry, a different revision or an expired session is refused, and the
    run never falls back to another registry source.
    """
    try:
        lease = lifecycle.acquire(token, expected_revision=registry_rev)
    except Exception as exc:
        raise translate_registry_error(exc) from None
    registry = lease.registry
    return CustomRegistryBinding(
        token=token,
        lease=lease,
        revision=lease.revision,
        digest=lease.digest,
        name=registry.name,
        row_count=len(registry),
    )


def binding_is_current(
    lifecycle: RegistryLifecycle,
    binding: CustomRegistryBinding,
) -> bool:
    """Whether the bound registry is still the session's committed one.

    Checked again before a result is stored: a mapping that was replaced or
    cleared while the run was executing makes the result stale, and a stale
    result is never stored.
    """
    return lifecycle.current_revision(binding.token) == binding.revision
