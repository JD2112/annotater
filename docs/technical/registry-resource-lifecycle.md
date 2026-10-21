# Custom-registry resource lifecycle

**Status:** authoritative design contract for M2.2a  
**Scope:** session-scoped custom chromosome mappings only. Bundled registries
are immutable, shared process-wide and do not use these budgets.

This document records the approved M2.1c estimator contract and the admission,
replacement, lease and expiry semantics implemented in
`streamlit_app/core/chrom_registry/lifecycle.py`. The numbers here are
*accounting estimates for admission*, never measurements of RSS.

## Approved estimators

For a mapping with `rows` data rows and `bytes` input bytes:

```text
retained = ceil((1 MiB + rows * 1.4 KiB + bytes) / 1 MiB)
parse    = ceil((8 MiB + rows * 2.25 KiB + 2 * bytes) / 1 MiB)
```

The implementation evaluates the fractional row terms as exact integer ratios
(`1.4 KiB = 7/5 KiB`, `2.25 KiB = 9/4 KiB`) and performs a single ceiling to a
whole MiB. It never rounds down. `rows` is the pre-parse newline count minus
the header, so comment and blank lines are deliberately over-counted until the
loader enforces the real row limit.

Pinned vectors (MiB):

| Rows | Input | Retained | Parse | Total |
|---:|---:|---:|---:|---:|
| 1,000 | 100 KiB | 3 | 11 | 14 |
| 10,000 | 1 MiB | 16 | 32 | 48 |
| 100,000 | 16 MiB | 154 | 260 | 414 |
| 500,000 | 64 MiB | 749 | 1235 | 1984 |
| 100,000 | 64 MiB | 202 | 356 | 558 |
| 500,000 | 25 MiB | 710 | 1157 | 1867 |

## Budgets and their meaning

| Pool | Default | Meaning |
|---|---:|---|
| Retained | 768 MiB | Registries that are reachable or still referenced by an execution lease. |
| Transient | 1280 MiB | Temporary peak of custom-mapping parses. |
| Combined | 2048 MiB | Retained + reserved retained + transient, deliberately conservative. |
| Parse concurrency | 1 | Number of custom mappings that may be parsed at once. |
| Headroom reserve | 128 MiB | Extra live-memory reserve required by the best-effort cgroup/host probe. |

A new parse reserves the parse slot, its transient charge and its eventual
retained charge atomically. The old registry of a replacement stays charged
throughout the parse, so a replacement can never exceed the retained or
combined pools on paper.

## Admission semantics

Admission is decided before parsing and never mutates existing registries:

- **413 `registry_too_large`** — the estimate cannot fit even on an empty
  budget in at least one pool. This is permanent and has no `Retry-After`.
- **429 `parse_busy`** — the serialised parse slot is occupied. Admission
  waits up to the bounded wait (2 s by default) before refusing, and the
  refusal carries a `Retry-After`.
- **429 `capacity_unavailable`** — retained, transient, combined or live
  headroom is temporarily unavailable. It carries a `Retry-After`.
- **409 `replacement_requires_clear`** — the session's own old and new
  registry charges cannot coexist even in an otherwise empty budget. See below.

The 409/429 split depends on *whose* capacity is in the way:

| Situation | Outcome |
|---|---|
| The session's old and new charges cannot coexist with no other session and no other reservation | 409 `replacement_requires_clear`, permanent, no `Retry-After` |
| Another live session holds the pool | 429 `capacity_unavailable` with `Retry-After` |
| Another parse holds the transient pool | 429 `capacity_unavailable` (or `parse_busy`) with `Retry-After` |
| An expired session still holds its charge (cleanup pending) | 429 `capacity_unavailable` with `Retry-After`, then swept and retried once |
| A retired registry whose lease is still active holds its charge | 429 `capacity_unavailable` with `Retry-After` until the lease is released |

Before a capacity 429 is returned, the lifecycle performs one safe liveness
sweep and retries admission once. The sweep drops only sessions that the
injected liveness authority reports as not live (expired or evicted); it never
evicts a live session to free budget. This releases accounting even when the
session store does not call its eviction callback. A busy parse slot, a
permanent 409 and a permanent 413 are re-raised unchanged: neither waiting nor
sweeping can help them, and neither triggers a sweep.

The parse slot is checked before capacity. A request that arrives while another
parse is running therefore waits for the slot and re-evaluates capacity after
the in-flight transient charge is released, instead of immediately reporting a
misleading capacity refusal. A permanently impossible request (413) is still
refused before any waiting.

## Replacement semantics

A different digest for an existing session is a replacement. The old registry
remains charged until the new reservation commits and the old registry is
retired; an active execution lease keeps the old charge until the lease is
released.

If the new estimate is admissible on its own but the session's old and new
registry charges cannot coexist inside the retained/combined budget *even with
no other session and no other reservation*, the replacement is refused with
**409 `replacement_requires_clear`**. The refusal is non-retryable while the
old registry exists. The old registry, revision, results and accounting are
all preserved. The caller must explicitly clear the registry and retry the
upload; retrying the replacement unchanged can never succeed.

Capacity that is in use *elsewhere* — another live session, another parse, the
accounting of an expired session awaiting cleanup, or a retired registry whose
lease is still active — does **not** make the replacement permanently
impossible. Such a replacement is refused with a retryable **429
`capacity_unavailable`** carrying a `Retry-After`, and it succeeds unchanged
once that capacity is released. The classification never depends on the
current accounting, only on the session's own two charges.

Smaller replacements that fit beside the old registry proceed atomically: the
new reservation commits first, then the old entry is retired and released when
its last lease ends.

## Lease lifecycle

An execution takes a lease before using a committed registry. Acquiring
requires the session to still be live and the revision to match when one is
stated. Leases are idempotently released.

Replacement, clear and session eviction *retire* an entry but do not release
its retained charge while leases remain. The charge is released exactly when
the final lease is released. Double releases raise instead of silently
clamping accounting to zero, so an accounting bug is visible in tests.

Session liveness is re-checked at commit and on `clear`, `acquire` and the
identical-digest fast path. A write that finishes after its session expired or
was evicted commits nothing and cannot recreate a lifecycle slot.

An anonymous write owns no session yet, so it has no liveness to re-check at
commit. It supplies the narrow commit-time `materialize` callback instead
(below): the session is created inside the successful commit, after the
mapping was admitted and parsed. A refused or superseded write never reaches
the callback, and a cancellation observed before the commit aborts the write,
so neither allocates a session slot or evicts a live session. (A cancellation
that arrives only after the commit has already succeeded is a completed
write whose response was lost, not a refused one.)

## Session expiry cleanup

Slots are released by:

1. the session store's `drop`/expiry/LRU eviction callback, immediately;
2. a liveness sweep at a temporary capacity refusal, before a retry;
3. `reserve_write`, which refuses invalid tokens without creating a slot and
   removes any stale slot for them.

The store invokes eviction callbacks outside its own lock. The lifecycle lock
may call the store's side-effect-free `contains` probe, but the store never
calls the lifecycle while holding its lock, so a re-entrant callback cannot
deadlock.

## Linux measurements from M2.1c

M2.1c recorded whole-process peak RSS for the 500,000-row / 64 MiB synthetic
mapping of about **1016 MiB on Linux arm64** and **888 MiB on Linux amd64**,
against an approximately **228 MiB** idle baseline. The incremental process
memory implied by those peaks is roughly 788 MiB and 660 MiB respectively.

These figures are context, not estimator inputs. The approved formulas charge
749 MiB retained and 1235 MiB transient (1984 MiB combined) for that input,
which is intentionally conservative relative to the measured process peaks.
The measurements were taken on the Linux deployment target; macOS and
workstation numbers are not substituted for them.

## Limitations

- The estimates are accounting bounds, not RSS predictions or per-registry
  measurements. The synthetic 500k-row mapping is a worst-case fixture, not a
  representative workload.
- The pre-parse row count includes comment and blank lines, so a valid mapping
  near the row or byte limit can be refused conservatively.
- The live headroom probe is best-effort. It reads the nearest finite cgroup v2
  `memory.max` (not the smallest limit across ancestors) and does not read
  `memory.high`; when no source is readable it reports "unknown" and admission
  proceeds.
- Measurements are process-wide peaks, not isolated registry allocations. Do
  not compare them directly with a single pooled charge.
- The accounting is in-process only. The deployment remains single-worker;
  running multiple workers would partition rather than share these budgets.
- CI exercises the formulas and lifecycle deterministically with injected
  clocks, probes and small synthetic registries. It does not reproduce the
  Linux RSS measurements on every run.

## Tests

The contract is pinned by `tests/test_registry_lifecycle.py`: estimator
vectors, transient/combined boundaries, 413 versus 429 versus 409, bounded
parse-slot waiting, replacement preservation, lease-protected retirement,
expiry/LRU cleanup, unknown-token slot growth, store notification behavior,
double-release guards, re-entrant eviction callbacks and same-digest
in-flight reuse. The 409/429 split is pinned by the replacement-classification
tests: expired-session cleanup, cross-session exhaustion, self-capacity
impossibility, refusal preservation and lease-retained charges.

The HTTP surface built on this lifecycle is documented in
[Custom chromosome registries: the HTTP contract](registry-api.md) and
pinned by `tests/test_registry_api.py`.

## Additions in M2.2b

The HTTP layer needed three primitives that the M2.2a contract did not have
to express. All are additive; no existing behaviour changed.

* **`RegistryLifecycle.current_metadata(token)`** returns the committed
  registry's identity (revision, content digest, display name, sequence
  count) without its content, so a client can bind a later request to
  exactly that registry. It is a pure read: it allocates nothing, changes
  no accounting and returns `None` for a session that is not live.
* **`RegistryLifecycle.clear_for_revision(token, expected_revision=...)`**
  is the atomic revision-scoped clear. The decision ("is there a registry,
  and is it the one the caller names?") and the removal happen under one
  lock, so a mapping committed between a caller's own check and the clear
  can never be removed by a clear that did not name it. It reports
  `revision_required` (a mapping exists and the caller named no revision)
  and `revision_mismatch` (the named revision is not the committed one)
  without removing anything, and it leaves the same tombstone as
  `clear`, so an in-flight write that arrived earlier cannot resurrect a
  mapping afterwards. The original `clear` is unchanged.
* **`RegistryLifecycle.register(..., materialize=...)`** is the
  commit-time materialisation primitive for an anonymous write. It is
  called exactly once, under the lifecycle lock, immediately before the
  successful commit, and must store the session and return its token. It is
  mutually exclusive with a non-empty token. Because admission, parsing and
  every refusal happen first, a write that stores nothing never creates a
  session; because the callback runs before the commit, a successful write
  materialises exactly one session. This is not a create-then-drop
  strategy: no session exists to drop on any ordinary refusal path, and a
  dropped session is always the request's own new one, never a victim.

