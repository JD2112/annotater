# Task 1 Agent Prompt — Reproducible Repository Baseline

You are working on **AnnotateR**, a Streamlit genomic-coordinate annotation application with Bedtools and Polars-Bio backends.

Your job is to implement **PLAN Task 1 only: Reproducible repository baseline**.

## Mandatory reading before editing

Read, in this order:

1. `AGENTS.md`
2. `SPEC.md`
3. `PLAN.md` — Task 1 and its acceptance criteria
4. `docs/architecture.md`
5. `docs/engine-contract.md`
6. `docs/references.md`
7. the existing tests and the relevant package/import files

Treat `SPEC.md` as normative. Existing code is historical evidence, not automatically the contract.

## Starting assumptions

- The working repository may still have the historical GitHub slug `annotator`; the product name is **AnnotateR** and the preferred repository slug is `annotater`.
- Repository renaming is administrative housekeeping and is **not part of this task**. Do not perform broad path/module renames just to change the brand spelling.
- The current feature work originated from `feature/polars-bio`. Create/use a dedicated Task 1 branch/worktree according to the local workflow rather than mixing unrelated work into another task branch.
- Bedtools is an external system dependency; pybedtools alone is not sufficient to execute Bedtools-backed tests.

## Objective

Make the existing repository reliably importable and testable from the repository root in a documented supported development environment **without changing annotation semantics**.

This task is deliberately infrastructure/baseline-only. It exists so later parity work starts from a trustworthy test harness.

## Required work

1. Reproduce the current baseline from the repository root before making changes.
   - Record the exact commands used.
   - Record test collection/runtime failures precisely.
   - Distinguish Python dependency failures, missing external binaries, import/package failures, and genuine test failures.

2. Fix package/import-path issues that make collection depend on an implicit working directory or `PYTHONPATH`.
   - Prefer correct package-relative imports where appropriate.
   - Do not add opaque global `sys.path` hacks if normal package imports solve the problem.
   - Check all `streamlit_app` subpackages for the same class of issue, not only the first failing import.

3. Establish one reproducible documented test command from repository root.
   - Keep the setup lightweight.
   - If the repository currently lacks enough developer setup documentation, update the most appropriate existing developer/quick-start documentation minimally.
   - Clearly separate Python packages from external system dependencies such as `bedtools`.

4. Add focused smoke tests that verify at minimum:
   - core AnnotateR modules can be imported from repository root;
   - `BedtoolsEngine` can be imported/constructed without performing an interval operation;
   - `PolarsBioEngine` can be imported/constructed without performing an interval operation.

5. Clean only obvious baseline-level import duplication or dead import noise encountered in the files you must touch, provided this cannot alter runtime semantics.

6. Run the relevant test suite after the changes.
   - Report exact pass/fail/skip counts.
   - If full execution is impossible because the environment lacks an external dependency, prove that collection/import succeeds and report the remaining environmental blocker accurately.
   - Do not skip or xfail tests merely to create a green report unless the skip expresses a genuine documented optional/system dependency and is justified by the existing project support policy.

## Explicit non-goals / prohibitions

Do **not** in Task 1:

- rewrite `PolarsBioEngine` output handling;
- change overlap, left-join, strand, `min_overlap`, contains, within, or closest semantics;
- redesign parser behavior;
- decouple parser/backend selection yet (that is a later task);
- change coordinate conversions or “fix” suspected off-by-one behavior;
- add the parity harness planned for Task 3;
- perform a broad dependency upgrade;
- redesign the Streamlit UI;
- benchmark Bedtools vs Polars-Bio;
- silently catch new errors or convert exceptions to empty DataFrames;
- mechanically rename every occurrence of `annotator` to `annotater`.

If you discover a scientific/semantic bug while doing Task 1, document it as a later-task finding and leave its behavior unchanged unless the bug prevents import/test baseline establishment. If it blocks Task 1, explain the conflict before making the smallest necessary change.

## Documentation discipline

For version-sensitive claims, consult primary references in `docs/references.md`.

In particular, do not infer Polars-Bio behavior from old comments or the bundled historical PDF when current official docs disagree. However, Task 1 should not modify Polars-Bio semantics anyway.

## Acceptance criteria

You are done only when all Task 1 criteria from `PLAN.md` are addressed:

1. pytest collection succeeds from repository root in the documented supported environment;
2. existing tests are passing, or pre-existing failures are precisely documented rather than hidden;
3. imports no longer depend on launching Python from inside `streamlit_app/`;
4. smoke tests cover core imports and construction of both engine classes;
5. required system dependencies are documented separately from Python packages;
6. the diff remains baseline-focused and contains no engine semantic refactor.

## Review loop

Before declaring completion:

1. inspect the full diff for scope creep;
2. re-read Task 1 acceptance criteria line by line;
3. run the full documented test command again;
4. review your own changes specifically for import behavior from repository root and accidental semantic changes;
5. fix any blocker/major issue you find;
6. keep later-task observations as concise findings rather than implementing them now.

If your environment/workflow supports a separate reviewer agent, request a review against `SPEC.md`, `PLAN.md` Task 1, and `AGENTS.md`; resolve blocking findings before finalizing.

## Final report format

Return a concise implementation report containing:

- branch/worktree and commit(s);
- files changed;
- baseline problem reproduced before changes;
- exact fixes made;
- tests added/modified;
- exact test commands and final results;
- system/environment dependencies or blockers;
- explicit confirmation that annotation semantics were not intentionally changed;
- Task 1 acceptance criteria status, one by one;
- later-task findings discovered but intentionally left untouched.

Do not begin Task 2.
