# Custom chromosome registries: the HTTP contract

**Status:** authoritative endpoint contract for M2.2b
**Scope:** the session-scoped custom chromosome mapping of the FastAPI
backend. The scientific contract (SPEC §5.1.1) is normative; this page
documents the HTTP surface built on the
[resource lifecycle](registry-resource-lifecycle.md).

A custom chromosome mapping is a **source of chromosome identity, not a
genome assembly**. It is validated structurally, never repaired, and it is
resolved and rendered by the same runtime resolver and normalizer as a
bundled registry: the normalization code never branches on where a registry
came from.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/registry` | upload and validate a custom mapping |
| `GET` | `/api/registry` | read the session's registry metadata |
| `DELETE` | `/api/registry` | remove the session's registry (revision-scoped) |

All three use the ordinary session cookie: the mapping belongs to the
session that uploaded it, is never shared between sessions, never persisted
and never written to the bundled registry data. A read allocates no
session. An anonymous write materialises its session only at the successful
commit: an invalid mapping, a 413/429 refusal, a superseded write or a
cancelled parse allocates no session, issues no cookie and cannot evict a
live session from the bounded store. A successful write materialises
exactly one session and issues its cookie.

### `POST /api/registry`

`multipart/form-data` with one required field, `file`: the mapping itself.
The file name carries no meaning.

The mapping must be a UTF-8 tab-separated file with exactly the header
`assembly<TAB>ucsc<TAB>ensembl<TAB>genbank<TAB>refseq`. One row is one
sequence; each cell is the name of that sequence in one naming system, or
empty. Every row must carry at least one name. Only a leading byte-order
mark, CRLF line endings and a missing final newline are tolerated; nothing
is trimmed, case-folded or inferred.

Response (`200`):

```json
{
  "status": "success",
  "registry": {
    "source": "custom",
    "revision": "…",
    "digest": "…",
    "name": "Custom chromosome mapping",
    "row_count": 1,
    "assembly": null
  },
  "reused": false
}
```

* `revision` — the server-issued revision of the committed mapping. It is
  what a later run and a later clear must name.
* `digest` — the SHA-256 of the uploaded content. Identical content
  reuses the committed revision without parsing again (`reused: true`); a
  different digest replaces the mapping.
* `row_count` — the number of sequences in the mapping.
* `assembly` — always `null`: a custom mapping has no assembly identity
  and never reports one (SPEC §5.1.1 item 7).
* `reused` — whether the committed revision was reused unchanged.

A different mapping **replaces** the session's mapping and invalidates
every result derived from the previous content (SPEC §5.1.1 item 9). A
result derived from a bundled assembly, or from keeping the names as
provided, is unrelated to the custom mapping and stays valid.

The invalidation is atomic with respect to the session's committed state:
the upload compares the stored result against the **current** committed
registry revision, read under the session lock in the same critical
section that removes the result. A delayed cleanup from an earlier write
therefore sees a newer registry and leaves a result produced with it
alone. Identical content reuses the revision, so a same-digest re-upload
never invalidates a valid result. `DELETE` uses the same rule.

### `GET /api/registry`

Response (`200`): the same `registry` object, or `null` when the session
has no custom mapping. The mapping's content is never returned — only its
identity. The endpoint allocates no session.

### `DELETE /api/registry`

Query parameter `registry_rev` (optional): the revision the client owns.

The revision contract mirrors the dataset clear:

| Situation | Answer |
|---|---|
| nothing stored, no revision named | `200`, `cleared: false` (a no-op removal is not a write) |
| a mapping is stored, no revision named | `428` `revision_required` |
| a mapping is stored, the named revision is current | `200`, `cleared: true` |
| a mapping is stored, the named revision is stale | `409` `revision_conflict` |

The decision and the removal are atomic, so a mapping committed between the
client's own check and the request can never be removed by a clear that did
not name it. A refused clear removes nothing.

## Errors

Every error body is `{"code", "message", "stale"}` — the shape the React
frontend already understands for revision conflicts — plus the extra
fields listed below.

| Status | `code` | When |
|---|---|---|
| `400` | `invalid_mapping` | the mapping is structurally invalid; `issues` lists the problems (`code`, `message`, `rows`, `columns`) and `more` counts the remaining ones |
| `400` | `registry_source_conflict` | a run named both a custom mapping and a bundled assembly |
| `409` | `revision_conflict` | the named revision is stale, absent, or superseded by a later-started write |
| `409` | `session_expired` | the session expired or was evicted before the write committed |
| `409` | `replacement_requires_clear` | the session's old and new mapping cannot coexist even in an empty budget; the caller must clear the mapping first (permanent, no `Retry-After`) |
| `413` | `registry_too_large` | the mapping exceeds the byte limit, the row limit, or the retained/transient/combined budget (permanent) |
| `428` | `revision_required` | a mapping is stored and the request did not name the revision it owns |
| `429` | `parse_busy` | the serialised custom-mapping parse slot is occupied; retry after the indicated delay |
| `429` | `capacity_unavailable` | the retained, transient or combined pool, or the live headroom, is temporarily unavailable; retry after the indicated delay |

`429` responses carry a `Retry-After` header. `413` and the permanent
`409` do not: they are not retryable.

The admission decisions themselves (the estimators, the budgets, the
sweep-before-retry and the 409/429 split) belong to the
[resource lifecycle](registry-resource-lifecycle.md) and are not restated
here.

## Running with a custom mapping

`POST /api/execute` accepts an optional `registry_rev`. It selects the
chromosome source of the run:

| Request | Chromosome source |
|---|---|
| `chr_naming` is null | none: the names are kept as provided, and no registry is claimed |
| `registry_rev` is set | the session's custom mapping, bound by revision |
| `assembly` is set | the bundled genome assembly |

Naming both `registry_rev` and `assembly` is refused with `400`
(`registry_source_conflict`): one run uses exactly one chromosome source
and never mixes the two. A run that keeps the names as provided
(`chr_naming` is null) normalizes nothing and therefore has no source to
mix: it claims no registry, whatever the request names.

A run bound to a custom mapping:

* requires the named revision to be the session's current one (otherwise
  `409 revision_conflict`);
* leases the mapping for the duration of the run, so a concurrent
  replacement cannot free its memory under the run;
* executes outside the session lock, like every other run;
* checks the mapping's identity again before the result is stored: a
  mapping that was replaced or cleared while the run was executing
  discards the result (`409 revision_conflict`) instead of storing a stale
  one.

The response and the stored result carry the run's provenance:

```json
"registry": {"source": "custom", "revision": "…", "digest": "…",
             "name": "Custom chromosome mapping", "row_count": 1,
             "assembly": null}
```

A bundled run reports `{"source": "bundled", "assembly": "<canonical id>",
...}` — the canonical assembly id, whatever spelling the client used — and
keeps the assembly provenance of the normalization report. A run that kept
the names as provided reports `{"source": "none", ...}` and claims no
registry at all.

Exports (`/api/export/{fmt}`) are unaffected by the source: they serve the
stored result, which is bound to its `result_rev` as before. A VCF export
of a run normalized with a custom mapping carries the contig declarations
normalized through that mapping.

## Limits

| Limit | Value | Source |
|---|---|---|
| mapping size | 64 MiB | SPEC §5.1.1 item 8 |
| sequences per mapping | 500,000 | SPEC §5.1.1 item 8 |
| retained / transient / combined pools | 768 / 1280 / 2048 MiB | [resource lifecycle](registry-resource-lifecycle.md) |
| concurrent custom-mapping parses | 1 | [resource lifecycle](registry-resource-lifecycle.md) |

The byte and row limits are refused before the mapping is parsed; the pool
limits are admission decisions and are never measurements of memory.

## Tests

The contract is pinned by `tests/test_registry_api.py`: valid and invalid
uploads, same-digest idempotency, replacement and clear, the 413/429/409
admission branches, an expired session, an in-flight upload superseded by
a clear, a registry replaced during a run, two tabs with stale revisions,
session isolation, the custom/bundled/keep-original runs on both engines,
the result provenance, the CSV/TSV/VCF export consistency and the absence
of accounting leaks after errors, cancellation and stale commits. The
lifecycle itself is pinned by `tests/test_registry_lifecycle.py`.
