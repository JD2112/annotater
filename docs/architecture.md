# AnnotateR Architecture

**Status:** target architecture for the Polars-Bio parity refactor  
**Last updated:** 2026-10-20

## 1. Current problem

AnnotateR already has the right high-level abstraction: an `AnnotationEngine` with Bedtools and Polars-Bio implementations. However, backend choice currently affects more than interval execution. Parsing paths, backend-native schemas, output renaming, left-join behavior, and incomplete operation implementations are mixed together.

That makes a simple question — “do both engines produce the same annotation?” — difficult to answer because multiple transformations differ at once.

## 2. Target data flow

```text
uploaded/source file
        |
        v
+--------------------+
| format parser      |
| BED/GFF/GTF/VCF... |
+--------------------+
        |
        v
+-------------------------+
| normalization           |
| - chromosome IDs        |
| - coordinate convention |
| - dtypes/validation     |
| - metadata provenance   |
+-------------------------+
        |
        v
 canonical query/annotation DataFrames
        |
        +---------------------+
        |                     |
        v                     v
+------------------+   +------------------+
| BedtoolsEngine   |   | PolarsBioEngine |
+------------------+   +------------------+
        |                     |
        +----------+----------+
                   |
                   v
        backend-native result
                   |
                   v
+--------------------------------+
| canonical result adapter       |
| coord_* / annot_* / overlap    |
| missing values / ordering      |
+--------------------------------+
                   |
                   v
+--------------------------------+
| Streamlit presentation/export  |
+--------------------------------+
```

## 3. Boundaries

### Parser layer

Responsibilities:

- read a declared/supported file format;
- retain source metadata;
- identify source coordinate convention;
- report malformed input.

The parser layer MUST NOT decide which annotation backend will run.

The implemented parsers (`streamlit_app/core/parsers.py`) are explicit
and line-oriented, and emit **source-level** coordinates; conversion to
the canonical model happens in the normalization layer:

- **BED** — line-based, variable-width (3 to 12+ columns). Optional
  fields (`name`, `score`, `strand`) are missing per row where absent.
  Structurally invalid lines raise `MalformedFileError` with the
  offending physical line number; records are never silently dropped.
- **GFF/GTF** — fixed 9-column TSV layout; attributes parsed from the
  attribute column.
- **VCF** — the first eight tab-separated fields (CHROM POS ID REF ALT
  QUAL FILTER INFO) are parsed as text, which is complete per the VCF
  specification because tabs inside INFO values are escaped. Each
  variant becomes the interval occupied by its reference sequence,
  `[POS, POS + max(1, len(REF)) - 1]`, or `[POS, END]` (both 1-based
  inclusive) when `INFO/END` is present. Source metadata is preserved:
  the raw INFO field is kept as an `info` metadata column (VCF `.` →
  canonical missing), and when the `#CHROM` header declares `FORMAT` and
  sample columns, `format` plus one column per sample (named from the
  header, in source order) are kept with `.` → canonical missing; FORMAT
  sub-fields are not expanded. `FILTER` distinguishes the three spec
  meanings — `PASS`, a semicolon-separated failed-filter list, and
  MISSING (`.` = filters not applied → canonical missing, never
  converted to `PASS`). A sample name colliding with a parser/core
  column is renamed to `sample_<name>`; duplicate sample IDs and
  header/record field-count mismatches fail explicitly.

VCF parsing deliberately has no external VCF-library dependency: the
pinned pysam build in this environment does not expose `INFO/END`
through its record API, and an explicit parser keeps the coordinate
conversion deterministic and version-independent.

### Normalization layer

Responsibilities:

- map chromosome identifiers where requested;
- convert coordinates to the canonical interval model;
- normalize core data types;
- validate interval invariants;
- preserve row identity when needed for left joins and duplicate-safe operations.

This is the semantic boundary shared by both engines.

The implemented boundary is `streamlit_app/core/normalization.py`.
`parse_and_normalize` is the single entry point through which every
backend's source files enter canonical space, and it takes **no
backend/engine argument by design**. Per-format coordinate systems are
fixed by `FORMAT_COORDINATE_SYSTEMS` (BED: 0-based; GFF/GTF: 1-based;
VCF: 1-based); a user-declared system applies only to custom tables, exactly
once at the canonical boundary — to query tables after explicit column
mapping, and to annotation tables that already use the canonical
`chr`/`start`/`end` column names (default 0-based, the historical
effective behavior). `normalize_intervals` enforces the invariants in
`core/schema.py` and returns deterministic column order:
`chr, start, end, [strand], <metadata in source order>`.

### Engine layer

Responsibilities:

- perform interval operations;
- respect requested operation options;
- return enough provenance to reconstruct canonical results;
- propagate execution failures rather than disguising them as empty valid results.

The engine layer MAY use backend-native dataframe representations internally.

### Result adapter

Responsibilities:

- map backend-native output into the public contract;
- preserve query/annotation provenance;
- normalize missing values;
- add `has_overlap` where applicable;
- enforce deterministic column and row ordering.

Backend-specific suffix conventions belong here or inside the backend implementation, never in UI code.

The contract machinery lives in `streamlit_app/core/schema.py`.
`canonicalize_annotation_result` enforces the exact canonical column
set, boolean `has_overlap`, integer coordinate dtypes, canonical
missing (`pd.NA`) in every `annot_*` field of unmatched rows, and the
deterministic column order. Malformed query intervals (any row) and
malformed matched annotation coordinates — non-numeric or non-integer
coordinates, missing annotation chromosome, zero-width or reversed
intervals — are rejected with `CanonicalSchemaError` rather than coerced
to missing, which would fabricate a valid-looking row. The
`coord_`/`annot_` prefixes are
reserved — source metadata may not use them — and any backend-suffixed
leakage (`_1`, `_2`, `_right`) is rejected because the expected column
set is exact. Operation-specific additions (e.g. `distance` for closest
mode) must be explicitly declared; anything undeclared is rejected.
Row order is preserved exactly as the engine emits it; duplicated rows
are never collapsed. Task 4/5 implements the per-engine adapters that
map backend output into this contract.

### UI/export layer

Responsibilities:

- collect user inputs/options;
- select an engine;
- display/export canonical results;
- report actionable errors.

The UI MUST NOT contain backend-specific scientific semantics.

### Session state and revisions (React/FastAPI)

The FastAPI backend keeps parsed datasets and the last result in an
in-memory session addressed by the session cookie. Every tab of one browser
sends the same cookie, so tabs share that server state while each keeps its
own UI state. To keep what a tab shows, runs and exports scientifically
consistent, every stored state carries an opaque server-issued **revision**
(128-bit random, `api_sessions.new_revision`), and clients state which
revision they act on:

| State | Issued by (response field) | Required by |
|---|---|---|
| query dataset | `POST /api/upload` (`revision`), `POST /api/load-sample` (`query.revision`), `POST /api/apply-mapping` (`revision`, a new one) | `POST /api/execute` (`query_rev`), `POST /api/apply-mapping` (`query_rev`), `POST /api/dataset/clear` (`revision`, required when a dataset is stored) |
| annotation dataset | `POST /api/upload` (`revision`), `POST /api/load-sample` (`annot.revision`) | `POST /api/execute` (`annot_rev`), `POST /api/dataset/clear` (`revision`, required when stored) |
| result | `POST /api/execute` (`result_revision`; also echoes `query_revision`/`annot_revision`) | `GET /api/results/data`, `GET /api/results/gene-list`, `GET /api/export/{fmt}` (`result_rev` query parameter) |

Revision contract: nothing stored and no revision stated → 400/404 as
before; state stored but no revision stated → **428**; a stated revision
that is absent or different → **409** with
`{"detail": {"code": "revision_conflict", "message": …, "stale": ["query" | "annot" | "result", …]}}`.
The server never falls back to "whatever is stored now". This is the
*revision* check, where the client names a revision it had seen. Write
endpoints can return a 409 even when the client names no revision, because
they are also ordered by arrival (below).

Lifecycle: a dataset revision is replaced on every upload, sample load or
mapping of that side and disappears when the side is cleared or the session
expires. A result revision is created per successful execute; clearing a
dataset discards the result derived from it (and only a result bound to the
cleared revision, issue #52). A clear binds only the revision it names: a
request that names a stale revision, or that names none while a dataset is
stored, is refused without committing, so it cannot discard a newer dataset
another tab stored — nor advance the write-order high-water mark and make an
in-flight upload look superseded (issue #51). Revision checks and the state
transitions they guard run under the session's lock; execute and mapping run
the expensive work outside the lock and commit only if the datasets they
read are still the stored ones (otherwise 409, nothing stored).

Every write to a dataset side — upload, sample load, clear and applied column
mapping — is also ordered by request **arrival** per `(session, query|annot)`
(issues #55, #60). Arrival order is not commit order: each writer takes a
stamp when its request arrives, before its expensive work, and the side's
high-water mark records the highest stamp that actually **committed**. A
writer whose stamp is below that mark was superseded by a later-started write
and is refused (409 `revision_conflict`) without storing anything. If several
writes commit, the latest-arrived one wins regardless of which request
finished first. A later-started write that fails or is itself superseded
records nothing, so it never strands an earlier in-flight write.

- **Upload** (`POST /api/upload`) stamps only the requested `query` or
  `annot` side and commits that side only if no later-started write to it has
  committed. A superseded upload stores nothing and answers with `stale`
  containing its role.
- **Sample load** (`POST /api/load-sample`) stamps both sides at arrival and
  commits the query and annotation pair atomically. If a later-started write
  to either side has committed, the whole load is refused, nothing is stored
  and `stale` names both `query` and `annot`.
- **Clear** (`POST /api/dataset/clear`) checks arrival order before the
  revision contract. A later-started write that already committed wins, so a
  clear cannot delete it. A clear that removes a stored dataset is itself a
  committed write and advances the side's mark; a clear that finds nothing
  stored is a 200 no-op that removes and records nothing, so it cannot advance
  the mark either (issue #64). Stale or revision-less clears of stored data
  are still refused (409/428) without committing.
- **Apply mapping** (`POST /api/apply-mapping`) is a write to `query`. It
  checks the stated `query_rev` before the possibly slow mapping and confirms
  after it that the query entry is still the same and that no later-started
  query write committed; otherwise it stores nothing and answers 409. Query
  and annotation ordering remain independent.

A mapping therefore counts as a write to `query`, and an upload that arrived
before a mapping but finishes parsing after it committed cannot overwrite the
mapped table.

Revisions are not credentials: they never grant access beyond the session
cookie, and another session's revisions name nothing in yours. A refused
operation stores, runs or serves nothing. When a 409 reaches the React UI, it
drops the side(s) named in `stale`, clears any dependent result and shows a
"Changed in another tab" warning; Run stays unavailable until the user
re-uploads the affected file, reloads the sample or re-runs in that tab.
Exports are fetched with the displayed `result_rev`, so a superseded result is
never downloaded.

#### What invalidates a stored result (and what deliberately does not)

A result is identified by its own `result_rev`, not by the datasets that
produced it. Two different events therefore have deliberately different
effects on a stored result:

- **A dataset *clear*** drops the result derived from exactly the cleared
  revision. The result of another revision is left alone.
- **A dataset *replacement*** (an upload, a sample load or an applied
  mapping that stores a new table for a side) does **not** drop a stored
  result. The result belongs to the run that produced it, and a tab that
  still displays that run keeps displaying it and keeps being able to
  export it.

This asymmetry is intentional and is pinned by
`tests/test_multi_tab_revisions.py`. It is safe because the two halves of
the contract fit together:

- The UI withdraws its own displayed result on **every** invalidating
  event — a new upload, a sample load, an applied mapping, a coordinate
  declaration change, a change of engine, operation, join, chromosome
  source or naming target. A tab therefore never shows an old result
  beside a newly uploaded dataset, and never exports one as if it
  belonged to the new dataset.
- The server binds every read and export to the `result_rev` the client
  displays. A tab whose result was superseded by *another tab's run* gets
  a 409 conflict, never another tab's rows.

The remaining server-side case is a tab that keeps displaying a result
whose dataset another tab has since replaced. That tab's export contains
the rows of **its own** displayed run — not the other tab's data — and its
next run is refused with a 409 because its dataset revision no longer
matches. No result is ever attributed to a dataset it was not derived
from.

### Parsing concurrency (React/FastAPI)

Upload parsing is CPU- and memory-heavy. `POST /api/upload` runs detection,
parsing and normalization on a worker thread through
`anyio.to_thread.run_sync`, but borrows from a limiter dedicated to parsing
(`api_server._parse_limiter`, sized by `Settings.MAX_CONCURRENT_PARSES`,
default `2`) rather than AnyIO's shared default thread-pool limiter.
Starlette runs synchronous endpoints — `/health`, `/api/meta`, sample load and
clear — on that shared default limiter, so a burst of uploads cannot occupy
its tokens and starve them. Uploads waiting for a parse slot wait on the event
loop and do not block it. The limiter is per running event loop; production
has one loop (single Uvicorn worker) and therefore one limiter. This limit
covers uploads only: the bundled sample loader parses on the default pool.
Configuration values and the memory trade-off are documented in
[Deployment](deployment.md#parsing-concurrency).

### Custom-registry resource lifecycle (M2.2a)

Session-scoped custom chromosome mappings have their own accounting: the
approved M2.1c retained/transient estimators, retained/transient/combined
budgets, serialised parse admission, explicit replacement semantics,
execution leases and expiry cleanup. The authoritative contract, including
the formulas, error semantics, M2.1c Linux measurements and limitations, is
[Custom-registry resource lifecycle](technical/registry-resource-lifecycle.md).

### Custom chromosome registries over HTTP (M2.2b)

The FastAPI backend exposes the lifecycle as three session-scoped
endpoints — `POST /api/registry` (upload and validate), `GET
/api/registry` (metadata; never the content) and `DELETE /api/registry`
(revision-scoped clear) — and binds a run to a mapping with the optional
`registry_rev` of `POST /api/execute`. A run uses exactly one chromosome
source: the session's custom mapping, a bundled assembly, or none at all
when the names are kept as provided. The endpoint contract, the error
semantics and the result provenance are documented in
[Custom chromosome registries: the HTTP contract](technical/registry-api.md).
The React frontend does not use these endpoints yet.

## 4. Coordinate model

The target internal interval convention is 0-based, half-open `[start, end)`. Format-specific conversion belongs before backend execution. This model is compatible with BED/bedtools conventions and makes one-base boundary behavior explicit.

Because Polars-Bio can carry coordinate-system metadata when using its own I/O, direct DataFrame paths MUST NOT assume that automatic detection will fix unnormalized application DataFrames. AnnotateR owns its canonical coordinate contract.

Implemented per-format conversion (Task 2):

| Source  | Source convention        | Canonical conversion |
|---------|--------------------------|----------------------|
| BED     | 0-based half-open        | unchanged            |
| GFF/GTF | 1-based inclusive        | `start := start - 1`; `end` unchanged |
| VCF     | `POS` 1-based            | span `[POS, POS + max(1, len(REF)) - 1]`, or `[POS, END]` when `INFO/END` is present (1-based inclusive), then `start := start - 1` |

VCF span limitation (Task 2): the occupied interval is derived from REF
length or `INFO/END` only. Broader structural-variant interpretation
(e.g. ALT-only complex events) is intentionally not performed; variants
are represented by the interval their reference sequence occupies.

## 5. Row identity

Stable row identity is required whenever value equality is insufficient, especially:

- duplicated query rows;
- duplicated annotation rows;
- reconstruction of unmatched queries in left mode;
- deterministic sorting after backend execution.

Temporary row IDs MAY be added internally and MUST NOT leak into public output unless explicitly documented.

## 6. Error model

There is an important distinction between:

- a valid annotation run with zero overlaps;
- invalid input;
- unsupported requested semantics;
- backend execution failure;
- missing system dependency.

These states MUST NOT all collapse to an empty DataFrame.

## 7. Testing layers

```text
unit tests
  parser / normalization / coordinate boundaries
        |
        v
engine contract tests
  same operation semantics for each backend
        |
        v
parity tests
  Bedtools canonical result == Polars-Bio canonical result
        |
        v
Streamlit integration tests
  engine selection does not change scientific result
```

Large benchmark datasets are not substitutes for the minimal edge-case fixtures needed to catch semantic errors.

## 8. Deployment boundary

SciLifeLab Serve is a deployment target, not part of interval semantics. Container/deployment configuration should consume the tested application rather than influence how coordinates are interpreted.

See `docs/references.md` for current Serve and Streamlit documentation.
