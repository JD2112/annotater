# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Modern React + Tailwind CSS frontend interface with real-time progress indicators, interactive statistics visualizations, gene frequency charting, and one-click data previews.
- FastAPI backend service (`streamlit_app.api_server`) exposing annotation endpoints, sample dataset inspection, and progress tracking.
- Automated frontend linting and build validation step (`oxlint` + `vite build`) in GitHub Actions CI workflow (`python-tests.yml`).
- Multi-stage Docker build producing an optimized production container image with embedded frontend assets and non-root user execution (`appuser:appgroup`).
- Restored the "Charts and gene list" results panel from the original Streamlit application: a top-10 gene/feature bar chart and gene-list export (`.txt` / comma-separated `.csv`) for external enrichment tools (g:Profiler, Enrichr, DAVID, STRING), served by the new `GET /api/results/gene-list` endpoint and the `gene_list` field of the execute response.
- `POST /api/dataset/clear` endpoint that discards one role's stored dataset together with any result derived from it, without allocating a session (it is a state removal, not a write).
- Frontend behavioral test suite (dev-only `vitest` + `jsdom` + Testing Library, `frontend/src/app.behavior.test.jsx`, run by `npm test`) covering the two final-gate races in the real component: coordinate-system change invalidating a loaded dataset (N2), and a superseded in-flight `/api/execute` response being discarded while all inputs stay locked (N3).

### Changed
- Result statistics report match coverage as query-row-identity matches (`matched_query_count`), and the React results header and summary use it instead of result-row counts.
- Annotated VCF export is only offered for VCF queries, in the React UI and enforced at the HTTP boundary, matching the Streamlit application.
- The results table is cleared whenever the dataset or any execution configuration changes, so a stale result can no longer be displayed as if it belonged to a new run.
- Single-position queries (no end column) now map to one-base intervals via an explicit "None (single positions)" end-column sentinel instead of silently using a positional column.
- Changing the declared coordinate system of an already-loaded file now invalidates that side's dataset (locally, server-side, and the file picker) and requires a re-upload under the new declaration, instead of silently re-running the stale, already-normalized table (final-gate finding N2).
- The coordinate-system selectors, file pickers, column-mapping controls, sample loader and run button are locked while an upload or column mapping is in flight, and each side (query/annotation, tracked independently) carries a dataset generation: an upload or mapping response parsed under a superseded declaration is discarded and its possibly-stored server copy cleared, so it can no longer silently (re)populate a side with off-by-one coordinates. An upload or mapping that fails with a network error now drops that side on both client and server, since the server outcome is unknown (final-gate finding N2-R). Server-side, `POST /api/apply-mapping` now commits only if the stored query is still the table it read: a clear or re-upload that lands while the mapping runs yields HTTP 409 instead of a 500 (`KeyError`) or a silent overwrite of the newly uploaded table with the superseded one. Behavioral tests cover first upload, re-upload/slow parse, mapping, failures, and the annotation-side declaration (N7).
- While an annotation run is in flight all configuration controls are locked, and a superseded run's response can no longer land in the UI: an `/api/execute` response is applied only if no invalidating event happened after the run started (final-gate finding N3). The results header now states the operation mode and join the run actually used.
- `docs/deployment.md` now states what the React/FastAPI image actually reads: `PORT`, `FORWARDED_ALLOW_IPS`, `MAX_FILE_SIZE_MB`, and the new `ANNOTATER_CORS_ORIGINS`; the upload's temporary parsing copy lives under the system temp directory (`tempfile.mkdtemp`) and is deleted immediately, not under `TEMP_DIR` (which, with `CLEANUP_AFTER_HOURS`, belongs to the Streamlit-generation helpers only); the session-cookie section documents the `__Host-` prefixed HTTPS cookie name (final-gate finding N5).

- Tabs of one browser share one server session; each stored dataset and result now carries an opaque server-issued revision. `POST /api/execute` requires `query_rev`/`annot_rev`, `POST /api/apply-mapping` requires `query_rev`, and `GET /api/results/data`, `/api/results/gene-list` and `/api/export/{fmt}` require `result_rev` (returned as `revision` / `result_revision` by upload, load-sample, mapping and execute). A missing revision is refused with 428 and a stale one with 409 `revision_conflict`, never answered with another tab's datasets or result; execute and mapping commit only if their datasets were not replaced while they ran. The React UI sends these revisions, fetches exports with the displayed result revision, and shows "Changed in another tab" on a conflict instead of silently running on or exporting another tab's analysis (release-gate finding F1).

### Fixed
- `POST /api/dataset/clear` now follows the same revision contract as every other state-changing endpoint: a clear that names no revision while a dataset is stored is refused with 428 instead of silently discarding whatever is stored, and a rejected clear (409/428) commits nothing and does not advance the write-order high-water mark. Clearing a dataset now discards only a result bound to the cleared revision, leaving a result derived from any other revision alone (#51, #52). The React UI never sends a revision-less clear: on an unknown-outcome network error it clears only the last revision the tab owned (or nothing, when it owned none), a superseded successful response clears only the revision it reported, and a superseded failure sends no clear. An opt-in real-browser test proves one tab's clean-up cannot wipe a newer dataset another tab of the same session stored.
- Single-position (end-column-less) queries no longer depend on which column happens to be third in the input table.
- `POST /api/upload` no longer parses on the event loop: format detection, parsing and normalization now run in a worker thread (`anyio.to_thread.run_sync`), so a large upload can no longer freeze the single Uvicorn worker's loop and stall every other session's request and the `GET /health` readiness probe for the duration of the parse (#55). The upload's session commit remains a single locked critical section, so a concurrent clear or replacement still cannot expose a dataset and revision that do not match.
- Parsing now borrows from a limiter dedicated to uploads (default 2 concurrent, `ANNOTATER_MAX_CONCURRENT_PARSES`) instead of AnyIO's shared default threadpool, so a burst of uploads can no longer exhaust the pool that synchronous endpoints such as `GET /health` run on and starve them (#55). Waiting uploads await a token on the event loop and never block it.
- Same-session writes are ordered by request arrival: if an upload or sample load is superseded by a newer upload, sample load or clear that commits while the older request is still parsing, the older request is refused with `409 revision_conflict` and stores nothing, instead of silently overwriting the newer dataset — even across tabs of one browser session (#55). Clears carry the same ordering, so an in-flight upload cannot resurrect a side that was just cleared.
- A `409 revision_conflict` on an upload or sample load now drops the superseded side(s) in the React UI, clears dependent results and shows the "Changed in another tab" warning with Run disabled, instead of leaving the tab's previous dataset displayed as loaded with Run enabled (#58). Sample loading now carries the same per-side request-generation guard as uploads, so a stale sample-load response (success or conflict) can no longer overwrite a newer dataset. Behavioral tests cover both sides, sample loading, the stale-response case and the success paths; an opt-in real-browser test drives the recovery path in Chrome.

### Security
- `GET /api/results/data` page size is bounded to 10,000 rows per request.
- Unauthenticated read requests are served by throwaway sessions: they consume no session capacity, receive no session cookie, and can no longer evict a real user's state from the bounded session store.
- Session capacity is now consumed lazily on the first state write: anonymous or forged-cookie requests — including failed writes such as oversized or invalid uploads — allocate no session slot and can no longer exhaust the store or evict a real user's session (final-gate finding N4).
- Over HTTPS the session cookie is issued and honoured only under the `__Host-` prefixed name `__Host-annotater_session` (Secure, `Path=/`, no `Domain`), scoped to the exact issuing host: an unprefixed `annotater_session` cookie — even one carrying a live token planted by a sibling subdomain — is ignored over TLS, closing the session-fixation path (final-gate finding N1). Plain-HTTP local development keeps the unprefixed name.
- The session cookie is now read byte-exactly from the raw `Cookie` header instead of Starlette's parsed cookies, which strip Unicode whitespace from names: a sibling-settable `\xa0__Host-annotater_session` (or `\x85…`) cookie was being honoured as the `__Host-` cookie and could fixate a victim's session and expose their data. A cookie name that is not the byte-exact `__Host-annotater_session` (or, over plain HTTP, `annotater_session`) is ignored; only the byte-exact session cookie presented more than once is rejected with HTTP 400 as genuinely ambiguous (final-gate finding N1-R).
- Alias cookie names that AnnotateR can never issue are ignored rather than rejected: the previous fail-closed 400 closed the N1-R fixation path but let a sibling subdomain plant the alias on the parent domain and deny service to the whole browser until its cookies were cleared. Honouring only the byte-exact name closes fixation without that availability regression; a genuinely ambiguous duplicate session cookie is still refused (#53).
- CORS no longer reflects arbitrary request origins; cross-origin access requires an explicit allowlist via the `ANNOTATER_CORS_ORIGINS` environment variable (default: none). A bare `*` entry is rejected because, with credentialed CORS, it would reflect every request origin (final-gate finding N6).

## [0.1.0-rc2] - 2026-10-02

### Added
- Assembly-aware chromosome normalization architecture supporting standard assemblies (GRCh38, GRCh37, GRCm39, etc.) and custom coordinate registries.
- Strict parity verification harness between Bedtools and Polars-Bio backends across overlap, closest, and strand-aware modes.
- End-to-end container health smoke checks and deterministic benchmark harness in CI.
- Comprehensive documentation covering deployment, architecture, engine contracts, and reproducibility.

### Changed
- Streamlit application unified backend selection allowing dynamic engine switching with guaranteed schema parity.
- License formalized as BSD-3-Clause across codebase, packaging, and metadata.

## [0.1.0-rc1] - 2026-09-28

### Added
- Initial release candidate for AnnotateR on SciLifeLab Serve.
- Core genomic coordinate annotation pipeline with interchangeable Bedtools and Polars-Bio execution engines.
- Basic Streamlit UI for coordinate upload (BED, VCF), annotation files (BED, GFF, GTF), and tabular exports.
