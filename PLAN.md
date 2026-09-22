# AnnotateR Polars-Bio Parity Plan

**Status:** Active  
**Branch at planning time:** `feature/polars-bio`  
**Last updated:** 2026-09-21

This is the living implementation plan for making Bedtools and Polars-Bio interchangeable AnnotateR backends. `SPEC.md` is normative; this file defines sequencing and acceptance criteria.

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

Key requirement: every query row survives; unmatched rows appear exactly once with missing annotation fields and `has_overlap=False`.

Do not equate Polars-Bio `overlap_output="left"` with a genomic left outer join without testing: its documented mode returns only left rows that overlap.

Acceptance criterion: matched multiplicity, unmatched rows, duplicates, missing values, and ordering are identical after canonicalization.

## Task 6 — Extended interval semantics

Implement and lock down, one subtask/PR at a time if necessary:

- `min_overlap` semantics;
- strand-aware overlap;
- `contains`;
- `within`;
- `closest` / nearest.

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
