You are working on **AnnotateR**.

Task 1 and Task 2 are complete. Do **Task 2.5 only: dependency/runtime/reference audit**.

Do not begin Task 3.

Start from the current clean `main`, then create a dedicated branch:

`task-2.5-dependency-runtime-audit`

## Mandatory reading

Read:

1. `AGENTS.md`
2. `SPEC.md`
3. `PLAN.md`
4. `docs/architecture.md`
5. `docs/engine-contract.md`
6. `docs/references.md`
7. `requirements.txt`
8. `Dockerfile`
9. `docker-compose.yml`
10. CI/workflow files if present
11. relevant imports across `streamlit_app/` and `tests/`

Use primary sources from `docs/references.md`. For version-sensitive claims, verify current official release/documentation rather than relying on model memory.

## Goal

Establish one coherent, tested dependency/runtime baseline for AnnotateR before Task 3 parity work begins.

The repository was started roughly a year ago and may contain:

* stale minimum-version constraints;
* unused dependencies;
* Python-version drift between development and Docker;
* Polars-Bio versions much older than current documentation;
* mismatches between documented APIs and actually installed versions;
* incomplete normative references.

This task must audit and resolve those issues without changing scientific behavior.

## Required work

### 1. Audit Python/runtime support

Determine the currently intended Python version(s) from:

* Docker;
* CI;
* local/dev docs;
* dependency compatibility;
* current Polars-Bio requirements.

Identify inconsistencies.

Choose and document a supported Python baseline appropriate for the current project.

Do not choose merely because it is newest. Justify the choice based on current dependency compatibility and deployment practicality.

Update Docker/CI/docs only as needed to make the supported runtime coherent.

### 2. Audit every declared Python dependency

For each package in `requirements.txt`:

* determine whether it is actually imported/used by runtime code, tests, build/deployment, or documented workflows;
* identify its currently installed/resolved version in a fresh environment;
* identify its current upstream stable release;
* inspect compatibility constraints relevant to AnnotateR;
* classify it as:

  * required runtime dependency;
  * required test/development dependency;
  * optional dependency;
  * apparently unused/stale.

Do not remove a package based only on a superficial grep if it may be used dynamically or by tooling.

If a dependency is demonstrated to be unused, remove it unless there is a documented reason to retain it.

### 3. Audit Polars-Bio specifically

This is high priority.

Determine:

* the Polars-Bio version currently resolved by the project;
* the current stable Polars-Bio release;
* supported Python versions;
* relevant Polars compatibility constraints;
* whether AnnotateR currently uses APIs whose behavior/signature has changed across versions;
* whether the Docker image can install the intended Polars-Bio version.

Select and document a tested Polars-Bio baseline for future Task 3/4 work.

Do not modify engine semantics in this task.

If modern Polars-Bio requires changes to the engine implementation, record them as Task 4 findings rather than implementing them now, unless a change is strictly necessary for installation/import compatibility.

### 4. Audit Bedtools / pybedtools compatibility

Determine and document:

* supported/observed Bedtools version;
* pybedtools version;
* whether the current pair works in the supported environment;
* how Bedtools is installed in Docker and local development;
* whether any version-sensitive behavior matters for the operations used by AnnotateR.

Run at least one minimal pybedtools ↔ bedtools integration check.

Do not change overlap semantics.

### 5. Decide dependency constraint strategy

The current project may use broad lower bounds such as:

`package>=old_version`

Evaluate whether that is sufficient for reproducibility.

Choose a clear strategy, for example:

* bounded compatibility ranges;
* pinned runtime requirements;
* separate direct requirements vs lock/constraints file;
* another simple reproducible approach appropriate to the project.

Do not overengineer dependency management.

The result should allow a fresh environment today to reproduce the tested dependency set and should reduce the risk that a future incompatible major release is silently installed.

Document the policy.

### 6. Separate runtime and development/test dependencies if useful

If the current `requirements.txt` mixes runtime packages with tools such as:

* pytest
* pytest-cov
* black
* ruff

consider splitting them cleanly, for example:

* `requirements.txt`
* `requirements-dev.txt`

or another lightweight documented structure.

Only do this if it clearly improves reproducibility and maintenance.

Update commands/docs accordingly.

### 7. Fresh-install verification

Create a clean environment from scratch using the project's documented setup.

Do not rely on the existing Task 1/2 virtualenv.

Verify:

* all required dependencies install cleanly;
* core package imports succeed;
* Bedtools integration works;
* Polars-Bio imports successfully;
* full test suite passes.

Record exact resolved versions for important packages.

### 8. Docker verification

Build the Docker image from scratch.

Verify at minimum:

* build completes;
* supported Python version matches the documented baseline;
* Bedtools is available;
* Polars-Bio imports;
* core AnnotateR imports;
* test suite can run in an equivalent container environment, or explain precisely why tests are intentionally not part of the production image.

Fix runtime/dependency mismatches discovered by the Docker build.

Do not redesign deployment.

### 9. Audit normative references

Review `docs/references.md` systematically.

Ensure it contains primary/current references for at least:

#### File formats

* BED
* GFF3
* GTF
* VCF, with an explicit supported/reference VCF specification version

#### Engines/libraries

* Bedtools main documentation
* `intersect`
* `closest`
* pybedtools
* Polars-Bio documentation
* Polars-Bio operations/API documentation
* Polars-Bio releases/version source
* Polars
* pandas

#### Application/testing

* Streamlit
* Streamlit AppTest
* pytest

#### Deployment/tooling where relevant

* SciLifeLab Serve documentation
* Paseo only if it remains relevant to project documentation
* GitHub repository/development references if already normative

For each version-sensitive library, prefer a source that lets future agents verify current release/version compatibility.

Do not add random tutorials, blog posts, Stack Overflow answers, or secondary summaries when primary documentation exists.

### 10. Make version/reference usage explicit for future agents

Update `AGENTS.md` or `docs/references.md` with a short rule equivalent to:

* authoritative format semantics come from the linked specifications;
* version-sensitive library behavior must be checked against the project-supported version;
* do not assume latest online docs match the installed version;
* do not rely solely on model memory for BED/GFF/GTF/VCF or Polars-Bio semantics.

Keep this concise.

## Explicit non-goals

Do NOT:

* implement the Task 3 parity harness;
* rewrite PolarsBioEngine behavior;
* fix overlap/left/contains/within/closest parity;
* redesign parsers unless required purely for compatibility/import;
* change canonical scientific semantics from Task 2;
* redesign the Streamlit UI;
* benchmark engine performance;
* add large dependency-management frameworks unless clearly necessary;
* blindly upgrade every package to latest;
* retain stale packages merely because they were historically present.

## Testing

At minimum run:

* focused import tests;
* pybedtools/bedtools integration smoke test;
* Polars-Bio import/smoke test;
* full pytest suite;
* fresh-environment install verification;
* Docker build verification.

If changing dependency versions reveals a regression, determine whether it is:

* project code incompatibility;
* dependency incompatibility;
* version-specific behavior;
* test assumption failure.

Do not hide failures with skips unless the dependency is genuinely optional and that optionality is explicitly documented.

## Review loop

Use independent Pi subagents if available.

Have reviewers inspect specifically for:

* untested dependency upgrades;
* accidental scientific behavior changes;
* Docker/local Python mismatch;
* stale dependencies left behind;
* dependencies removed despite real usage;
* unbounded major-version risks;
* current Polars-Bio docs being used against an older installed version;
* incomplete BED/GFF/GTF/VCF normative references;
* Task 3 scope creep.

Resolve all BLOCKER and MAJOR findings.

## Acceptance criteria

Task 2.5 is complete only when:

1. supported Python runtime is explicit and coherent across dev/Docker/CI;
2. every declared dependency has a justified role;
3. unused/stale dependencies are removed or explicitly justified;
4. Polars-Bio supported version is explicit and tested;
5. Polars/Polars-Bio compatibility is verified;
6. Bedtools/pybedtools compatibility is verified;
7. fresh install succeeds;
8. full tests pass in the fresh environment;
9. Docker builds successfully with the intended runtime;
10. dependency constraint policy is documented;
11. `docs/references.md` includes authoritative BED, GFF3, GTF, VCF and tool references;
12. VCF reference version is explicit;
13. agents are instructed to use version-matched primary documentation;
14. no Task 3/4 scientific implementation was started.

## Final report

Return:

* branch;
* base commit;
* commits;
* supported Python version(s);
* dependency audit table:

  * package
  * previous constraint
  * resolved version before
  * chosen constraint/version
  * role
  * action/reason;
* removed dependencies and evidence;
* Polars-Bio audit findings;
* Bedtools/pybedtools audit findings;
* fresh-install commands/results;
* Docker build/result;
* final pytest counts;
* documentation/reference changes;
* independent review findings and resolutions;
* acceptance criteria status one by one;
* later-task findings intentionally deferred.

Do not begin Task 3.
