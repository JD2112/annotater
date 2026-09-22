Stay on `task-2.5-dependency-runtime-audit`.

Do not begin additional Task 3 implementation.

Artifact review found several inconsistencies that must be resolved before Task 2.5 is merge-ready.

## BLOCKER 1 — Docker/runtime baseline is inconsistent

The audited supported runtime is Python 3.12 and `pyproject.toml` declares:

`requires-python = ">=3.12"`

but the production Dockerfile still uses:

`FROM python:3.10-slim`

This contradicts the Task 2.5 goal and acceptance criteria.

Update the Docker runtime to the supported Python baseline.

Then actually build the image from scratch.

Verify inside the resulting container:

* Python version;
* `bedtools --version`;
* import of `pybedtools`;
* import of `polars`;
* import of `polars_bio`;
* import of AnnotateR core modules.

If practical, run the full test suite in a test-capable container or equivalent clean Docker environment. If the production image intentionally excludes test dependencies, document the exact verification performed.

Also inspect the existing Docker healthcheck and confirm every command it invokes is actually installed in the final image.

Do not claim Docker verification unless the build was actually executed successfully.

## MAJOR 2 — stale Python-version documentation

The README badge still advertises Python 3.10+.

Make user-facing documentation consistent with the supported runtime.

Also correct `docs/implementation-notes.md`: it currently states that `SPEC.md` requires "Python 3.10 or newer", but `SPEC.md` contains no such normative requirement.

Do not invent a SPEC requirement.

Document Python 3.12 as the currently tested/supported runtime established by Task 2.5.

## MAJOR 3 — xfail guardrails must be strict

The engine-deviation tests currently use:

`pytest.mark.xfail(strict=False, ...)`

These tests are intended as temporary executable specifications.

Change them to `strict=True`.

Rationale:

* current known deviations should remain XFAIL;
* when an engine fix makes one unexpectedly pass, CI must fail with XPASS;
* that forces the obsolete xfail marker to be reviewed and removed.

After this change, verify the suite still reports the expected XFAIL count.

Do not fix the engine behavior in this task.

## MAJOR 4 — dependency audit must disposition unused dependencies

The audit currently identifies packages such as `python-magic` and `validators` as not imported but retains them because removal was described as out of scope.

Dependency cleanup was explicitly part of Task 2.5.

Perform a repository-wide usage audit for at least:

* `python-magic`
* `validators`
* `pyranges`
* `altair`
* `openpyxl`

Include runtime code, tests, dynamic imports, export paths, documentation-supported workflows, and deployment requirements.

For every apparently unused package:

* remove it if there is no current justified role;
* or document concrete evidence for why it remains required.

Do not retain a dependency solely because it historically existed.

Regenerate/update the lockfile after dependency changes.

## MAJOR 5 — normative reference audit is not yet complete

`docs/references.md` now contains BED, GFF3, GTF, and VCF references, which is good.

Complete the reference contract:

1. choose and document an explicit VCF specification version used as the normative reference for AnnotateR;
2. link directly to that specification/version rather than only to the `hts-specs` repository root;
3. add an authoritative Polars-Bio release/version source such as PyPI and/or official GitHub releases/changelog;
4. state that online API documentation must be interpreted against AnnotateR's pinned Polars-Bio version.

Do not remove the current primary references.

## MAJOR 6 — report Task 3 scope honestly

`tests/test_engine_contract.py` already contains differential/parameterized contract tests for both BedtoolsEngine and PolarsBioEngine.

This is useful work and should not be removed.

However, it is partial Task 3 work.

Update the Task 2.5 documentation/report to state explicitly that the dependency audit opportunistically established an initial engine-contract baseline and captured five known deviations as strict xfails.

Do not add further Task 3 cases in this fix pass.

Task 3 should later expand this initial harness systematically.

## Final verification

After resolving the findings:

1. create a brand-new clean Python 3.12 environment;
2. install only from the committed dependency definitions;
3. run the full test suite;
4. report exact PASS / XFAIL / XPASS / FAIL / SKIP counts;
5. build Docker from scratch successfully;
6. verify Docker runtime and core imports;
7. verify `Dockerfile`, `pyproject.toml`, CI, README, and implementation notes agree on Python support;
8. verify all remaining runtime dependencies have a documented/current role;
9. verify VCF and Polars-Bio version references are explicit;
10. inspect the full diff for scientific behavior changes.

Do not change engine, parser, coordinate, or canonical scientific behavior.

Return a final review-resolution report and the new commit SHA.

Do not begin further Task 3 implementation.

---

Stay on `task-2.5-dependency-runtime-audit`.

Make one final documentation/metadata consistency pass only.

Do not change dependencies, tests, Docker behavior, engines, parsers, or scientific logic.

1. Remove incorrect claims in `requirements.txt` and `pyproject.toml` that exact dependency pinning is required by `SPEC.md`.

`SPEC.md` contains no such requirement.

Describe exact pinning accurately as the dependency/runtime policy established by Task 2.5 for the audited reproducible environment.

2. Make Python support wording consistent.

The project currently tests and supports Python 3.12 in CI and Docker.

Do not advertise untested Python versions as officially supported.

Use wording equivalent to:

`Python 3.12 is the currently tested and supported runtime.`

Change the README badge from `Python 3.12+` to `Python 3.12`.

For `requires-python`, use a compatibility range consistent with the pinned dependencies. Prefer:

`>=3.12,<3.15`

if the current pinned dependency set is installable under that range; otherwise use the narrowest justified range.

Make clear that Python 3.13/3.14 are not part of the tested CI matrix unless actually tested.

3. Re-run the full test suite to ensure metadata-only changes caused no regression.

Return:

* files changed;
* final `requires-python` value;
* exact pytest counts;
* confirmation that no runtime/scientific behavior changed.

Commit this as one tiny follow-up commit.

Do not begin Task 3.
