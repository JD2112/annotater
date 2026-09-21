# AGENTS.md

## Agent skills

### Issue tracker

Issues and specs live in GitHub Issues for `pyrevo/annotater` (use the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`), label strings equal to the role names. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` at the repo root plus `docs/adr/`. See `docs/agents/domain.md`.

# Agent Instructions for AnnotateR

This repository uses coding agents for scoped implementation and review. Read this file, `SPEC.md`, the active task in `PLAN.md`, and relevant files under `docs/` before editing code.

## Source of truth

Priority order:

1. `SPEC.md` — normative product/scientific contract.
2. active task in `PLAN.md` — current scope and acceptance criteria.
3. `docs/engine-contract.md` and `docs/architecture.md` — detailed design constraints.
4. `docs/references.md` — external primary manuals for version-sensitive behavior.
5. existing implementation — evidence of historical behavior, not automatically normative.

If these conflict, stop and report the conflict rather than silently choosing whichever implementation is easiest.

## General working rules

- Work only on the active task.
- Preserve scientific semantics outside task scope.
- Prefer tests before or alongside behavior changes.
- Use minimal synthetic genomic fixtures for edge cases.
- Do not weaken tests to make an implementation pass.
- Do not claim parity from similar row counts or visual inspection.
- Do not introduce broad dependency upgrades without need.
- Keep backend-specific behavior behind the engine/result-adapter boundary.
- Do not couple parser selection to backend selection.
- Propagate backend failures explicitly; a backend exception is not a valid empty result.
- Never commit credentials, API tokens, SciLifeLab endpoint secrets, or user data.

## External documentation

Before changing Bedtools, pybedtools, Polars-Bio, Streamlit testing, Paseo-related repository configuration, or deployment behavior, consult the corresponding current official manual linked in `docs/references.md`.

Do not assume historical Polars-Bio column suffixes or output shapes.

## Testing

For each task:

1. run the narrowest relevant tests while developing;
2. run the documented full test command before completion;
3. report exact pass/fail/skip counts;
4. distinguish new failures from pre-existing baseline failures;
5. if a system dependency is absent, report it explicitly rather than bypassing the test silently.

## Git / PR discipline

- One task per branch/PR.
- Keep commits scoped and reviewable.
- Do not merge until acceptance criteria are satisfied and review findings are resolved.
- Do not force-push or rewrite shared history unless explicitly instructed.
- Do not include unrelated formatting churn.

## Definition of an acceptable task report

A completion report must state:

- files changed;
- behavior changed (or explicitly unchanged);
- tests added/modified;
- exact test commands and results;
- known limitations;
- whether every active task acceptance criterion is satisfied;
- any deviations from `SPEC.md` or external documentation.

## Repository/product naming

The product name is **AnnotateR**. The preferred repository slug is `annotater`.

Do not mechanically rename generic programming concepts containing the English noun “annotator” (for example `annotator.py` or `ProgressiveAnnotator`) unless a task specifically requires it.
