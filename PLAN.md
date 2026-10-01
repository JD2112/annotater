# AnnotateR Polars-Bio Parity Plan

**Status:** Completed — retained for provenance  
**Branch at planning time:** `feature/polars-bio` (historical; merged to `main`)  
**Last updated:** 2026-09-21

> **Note (0.1.0-rc2 preparation):** the Polars-Bio parity implementation described below was completed before `0.1.0-rc2`. This file is kept unchanged as a historical record of sequencing and acceptance criteria; it is no longer an active roadmap. `SPEC.md` remains the normative contract.

This was the implementation plan for making Bedtools and Polars-Bio interchangeable AnnotateR backends. `SPEC.md` is normative; this file defines sequencing and acceptance criteria.

## Working rules

- One scoped task per branch/PR.
- Do not combine cleanup, scientific-semantic changes, UI redesign, and performance work in one PR.
- Tests that encode a discovered contract belong in the same PR as the contract change or before the implementation change.
- Prefer small synthetic genomic fixtures over large real datasets.
- Do not weaken or delete a failing parity test merely to make a backend pass.
- Do not treat Bedtools output formatting as the public API; compare canonical results.
- Consult `docs/references.md` before relying on backend-specific behavior.

## M0 — Repository contract and planning

**Status:** prepared

Artifacts:

- `SPEC.md`
- `PLAN.md`
- `AGENTS.md`
- `docs/architecture.md`
- `docs/engine-contract.md`
- `docs/references.md`

M0 contains documentation only. It establishes the target architecture and task boundaries.

## Task 1 — Reproducible repository baseline

**Goal:** make the existing repository reliably installable/testable from its root without changing annotation semantics.

Scope:

- fix package-relative/import-path problems that currently make test collection environment-dependent;
- establish one documented Python test invocation from repository root;
- rationalize obviously duplicated imports and test-only path hacks only where needed for reproducibility;
- identify runtime/system dependencies required by Bedtools and Polars-Bio;
- add small smoke tests for importing the core package and constructing both engine classes;
- document the observed baseline and any tests that cannot run because an external binary/dependency is unavailable;
- preserve current scientific behavior.

Explicit non-goals:

- no Polars-Bio output rewrite;
- no parser redesign;
- no coordinate-semantic changes;
- no UI redesign;
- no contains/within/closest implementation;
- no broad dependency upgrades unless required to make the declared environment reproducible.

Acceptance criteria:

1. `pytest` collection succeeds from repository root in the documented supported environment.
2. Existing tests are either passing or any pre-existing failures are precisely documented; Task 1 MUST NOT hide them.
3. Imports do not depend on launching Python from inside `streamlit_app/`.
4. New smoke tests validate importability of core modules and both engine classes.
5. Documentation records required system dependencies (notably bedtools) separately from Python packages.
6. Diff remains baseline-focused and contains no engine semantic refactor.

## Task 2 — Canonical schemas and backend-independent normalization

**Goal:** introduce explicit canonical input and output contracts without yet rewriting every backend operation.

Expected work:

- define canonical interval dataframe requirements;
- centralize/clarify format-to-canonical coordinate conversion;
- preserve metadata provenance;
- define deterministic canonical result columns, missing values, and sorting;
- decouple parser selection from backend selection;
- add unit tests for normalization and one-base boundary cases.

Acceptance criterion: the same source input is normalized identically regardless of selected engine.

## Task 3 — Overlap parity harness

**Goal:** create differential tests for ordinary overlap before changing Polars-Bio implementation.

Expected work:

- add `tests/parity/` and tiny fixtures;
- parameterize shared engine contract tests where practical;
- compare canonicalized Bedtools and Polars-Bio results;
- capture exact currently failing cases rather than papering over them.

Acceptance criterion: failures diagnose semantic/schema differences precisely enough to drive Task 4.

## Task 4 — Polars-Bio overlap parity

**Status:** implementation complete (2026-09-22) — P1–P4 resolved, 262 passed / 5 xfailed (B1–B5 only); see docs/implementation-notes.md

**Goal:** make Polars-Bio pass the ordinary overlap contract.

Expected work:

- use current documented Polars-Bio API explicitly (`cols1`, `cols2`, suffixes/output shape as appropriate);
- remove suffix guessing;
- remove unnecessary Pandas↔Polars round trips where safe;
- preserve duplicates and metadata provenance;
- stop swallowing backend failures as empty scientific results;
- implement canonical post-processing.

Acceptance criterion: all ordinary-overlap parity tests pass for both engines.

## Task 5 — Left-join parity

**Goal:** implement the canonical left-overlap contract for both engines.

**Status: complete (2026-09-22) — see `docs/implementation-notes.md` (Task 5 section).** All 5 remaining Bedtools deviations (B1–B5) resolved via the identity-only `BedtoolsEngine` adapter rewrite; the 5 strict xfails were retired and replaced by passing tests. `use_strand`, `min_overlap`, and `contains`/`within` semantics remain Task 6 scope (behavior unchanged).

Key requirement: every query row survives; unmatched rows appear exactly once with missing annotation fields and `has_overlap=False`.

Do not equate Polars-Bio `overlap_output="left"` with a genomic left outer join without testing: its documented mode returns only left rows that overlap.

Acceptance criterion: matched multiplicity, unmatched rows, duplicates, missing values, and ordering are identical after canonicalization.

## Task 6 — Extended interval semantics

**Status: 6a + 6b + 6c + 6d + 6e complete (2026-09-24) — see `docs/implementation-notes.md` (Task 6A, Task 6B, Task 6C, Task 6D, and Task 6E sections).** `min_overlap` has one normative backend-independent meaning (SPEC 8.2, fixed in 6a). `use_strand` now has one normative backend-independent meaning (SPEC 8.3, fixed in 6b: `use_strand=False` ignores strand; `use_strand=True` requires both rows to carry explicit equal `+`/`-` strands — missing/unknown strand is not a wildcard; missing strand column ⇒ no stranded matches, identical for both engines; composes with `min_overlap` by logical AND; enforced by a shared canonical post-filter on both engines, protected by 29 per-engine contract cases, 15 differential cases, 1 `.` end-to-end case, and validation tests). `contains` now has one normative backend-independent meaning (SPEC 8.4, fixed in 6c: query interval fully contains the annotation interval, `q_start <= a_start AND q_end >= a_end`; equality and shared boundaries qualify; annotation-contains-query/partial/touching do not; `contains` is explicitly not `min_overlap = 1.0` and `min_overlap` is not applied in contains mode; strand composes by logical AND; left mode reconstructs zero-qualifying queries exactly once; enforced by a shared canonical post-filter over ordinary overlap candidates on both engines, protected by 34 per-engine contract cases, 21 differential cases, and focused regression tests). `within` now has one normative backend-independent meaning (SPEC 8.5, fixed in 6d: the query interval is fully contained within the annotation interval, `a_start <= q_start AND a_end >= q_end`; the directional inverse of `contains`; equality satisfies both; partial overlaps and touching do not qualify; `within` is explicitly not `min_overlap` and `min_overlap` is not applied in within mode; strand composes by logical AND; left mode reconstructs zero-qualifying queries exactly once; the old bedtools `-F 1.0` placeholder, which expressed the opposite direction, was removed in favour of a shared canonical `within_keep_mask` post-filter over ordinary overlap candidates on both engines, protected by 39 per-engine contract cases, 23 differential cases, and focused regression tests). `closest` now has one normative backend-independent meaning (SPEC 8.6, fixed in 6e: canonical integer distance `max(0, a_start - q_end, q_start - a_end)` — the exact number of bases in the gap; overlapping and touching (bookended) intervals have distance 0, a one-base gap has distance 1, a larger gap is the exact base count; same-chromosome candidates only; strand eligibility applied BEFORE nearest selection when `use_strand=True` with missing/unknown strand never a wildcard; ALL tied-nearest annotations returned in annotation input order, overall order query input order; `min_overlap`/contains/within do not participate; `how="left"` gives unmatched queries canonical-missing annotation fields and `pd.NA` distance; the result carries a nullable-Int64 `distance` column; the 76-vs-75 backend discrepancy is resolved canonically to 75 on both engines; enforced by the shared canonical selection `canonical_closest` used by both engines with NO backend-native closest/nearest call, protected by 32 per-engine contract fixtures with explicit expected distances, 18 differential cases, and focused regression tests). Remaining subtasks:

- `min_overlap` semantics — **done (6a)**;
- strand-aware overlap — **done (6b)**;
- `contains` — **done (6c)**;
- `within` — **done (6d)**;
- `closest` / nearest — **done (6e)**.

Each operation requires an explicit contract and backend parity tests before being considered supported.

## Task 7 — Streamlit integration

**Goal:** backend choice changes only the execution engine.

Expected work:

- remove parser/backend coupling;
- add Streamlit `AppTest` smoke/integration coverage for backend selection;
- ensure equivalent user-visible results for parity-protected fixtures;
- expose explicit errors for unsupported/invalid combinations.

## Task 8 — Deployment, documentation, and benchmark

**Goal:** prepare the tool for SciLifeLab Serve and publication-quality reproducibility.

Expected work:

- refresh Docker/deployment configuration;
- verify SciLifeLab Serve requirements against current documentation;
- document supported versions;
- benchmark Bedtools vs Polars-Bio on representative datasets only after parity;
- update README/QUICKSTART and citation metadata;
- record limitations and supported annotation semantics.

## Deferred ideas

- Polars-Bio-native parsing as an optimization;
- streaming/lazy execution for very large files;
- richer CLI;
- additional interval backends;
- publication figures/benchmark suite;
- formal ADRs if architectural choices accumulate enough alternatives to justify them.
