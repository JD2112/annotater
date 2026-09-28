You are working on **AnnotateR**.

Tasks 1–7 are complete and merged.

Implement **PLAN Task 8 only: Deployment, documentation, and benchmark**.

Task 8 is the final planned engineering task before manual GUI acceptance/release review.

The scientific contract is complete and must not change.

---

# Goal

Prepare AnnotateR for:

1. deployment on **SciLifeLab Serve**;
2. reproducible local/container execution;
3. publication-quality documentation of supported behavior;
4. a fair, parity-preserving **Bedtools vs Polars-Bio benchmark**;
5. release-readiness review.

Task 8 must answer:

```text
Can another person deploy AnnotateR,
understand exactly what it supports,
reproduce its environment,
and interpret the Bedtools-vs-Polars benchmark correctly?
```

---

# Start state

Start from the current clean `main` after Task 7 has been merged and CI has passed.

Before editing:

1. `git fetch origin`
2. fast-forward local `main`
3. verify `main == origin/main`
4. verify working tree clean
5. create:

`task-8-deployment-docs-benchmark`

Do not work directly on `main`.

---

# Mandatory reading

Read in this order:

1. `AGENTS.md`
2. `SPEC.md`
3. `PLAN.md` — Task 8
4. `docs/architecture.md`
5. `docs/engine-contract.md`
6. `docs/references.md`
7. `docs/implementation-notes.md`
8. `README.md`
9. `QUICKSTART.md`
10. Docker / deployment files
11. `pyproject.toml`
12. requirements files
13. CI workflows
14. Streamlit entry point and configuration
15. complete parity test suite
16. Task 7 Streamlit/AppTest tests

Use primary/current documentation when verifying deployment requirements.

Do not rely solely on remembered SciLifeLab Serve behavior.

---

# Current environment baseline

Preserve the validated environment unless evidence requires otherwise:

* Python 3.12 supported/tested
* `requires-python >=3.12,<3.15`
* bedtools 2.31.1
* pybedtools 0.12.1
* Polars 1.44.2
* Polars-Bio 0.35.1
* pandas 3.0.6
* numpy 2.5.3
* Streamlit 1.64.0
* pytest 9.1.1
* openpyxl 3.1.5

Current production Docker target is `linux/amd64` because the pinned Polars-Bio release does not provide the required Linux ARM64 wheel.

Re-verify this constraint rather than assuming it remains true.

---

# 1. Verify current SciLifeLab Serve requirements

Consult the current official SciLifeLab Serve documentation.

Verify at minimum:

* supported deployment mechanism;
* container expectations;
* exposed port requirements;
* health-check expectations;
* architecture/platform expectations;
* persistent vs ephemeral filesystem behavior if relevant;
* resource configuration;
* environment variable handling;
* public/private app settings if relevant;
* repository/image workflow;
* any Streamlit-specific deployment guidance.

Record the exact documentation links in `docs/references.md`.

Do not build deployment behavior from old memory.

---

# 2. Refresh Docker configuration

Audit the Dockerfile from first principles.

Verify:

* supported Python version;
* Bedtools installation;
* pinned Python environment;
* Streamlit startup;
* working directory;
* non-interactive installation;
* required system libraries;
* health check;
* port exposure;
* production command;
* `.dockerignore`;
* cache behavior;
* absence of development/runtime junk.

Build the image locally.

Preferred verification:

```text
docker build --platform linux/amd64 ...
```

Then start the container and verify:

* app starts;
* health check succeeds;
* Streamlit endpoint responds;
* core imports succeed;
* both engines initialize;
* canonical smoke annotation completes.

Do not merely prove `docker build` succeeds.

---

# 3. Dependency reproducibility

Verify that the dependency definitions agree across:

* `pyproject.toml`;
* requirements files;
* `uv.lock`;
* Docker;
* CI;
* README / QUICKSTART.

Do not perform broad dependency upgrades merely because Task 8 is a release task.

Only change versions when there is a concrete compatibility/security/deployment reason and the entire contract suite is revalidated.

Document:

```text
supported/tested runtime
install-compatible runtime range
exact pinned production dependencies
system dependency requirements
```

---

# 4. SciLifeLab Serve deployment documentation

Create or update deployment documentation so that a project maintainer can deploy AnnotateR without reverse-engineering the repository.

Prefer a focused file such as:

```text
docs/deployment.md
```

unless repository convention indicates another location.

Document:

* prerequisites;
* architecture/platform;
* container build;
* local container test;
* required port;
* health check;
* SciLifeLab Serve setup;
* environment/configuration;
* expected startup;
* deployment verification;
* common failure modes.

Do not include secrets or real credentials.

Use placeholders where credentials/project identifiers would be needed.

---

# 5. Benchmark purpose

The benchmark is NOT:

> prove Polars-Bio is faster.

The benchmark is:

> measure the performance characteristics of two semantically equivalent AnnotateR backends under representative controlled workloads.

Do not design the benchmark to favor either implementation.

Scientific parity is already established and remains mandatory.

---

# 6. Benchmark the AnnotateR execution path

Measure the real engine path used by AnnotateR, not isolated toy library calls that bypass adapters/canonicalization.

The benchmark should represent:

```text
canonical input
→ AnnotateR engine call
→ canonical result
```

Do not include Streamlit rendering.

Parsing may be benchmarked separately if useful, but backend comparison must not accidentally include different parser paths because parsing is backend-independent.

---

# 7. Benchmark datasets

Use synthetic deterministic datasets so the benchmark is:

* reproducible;
* distributable;
* free from private/user data;
* configurable;
* capable of scaling predictably.

Include representative sizes, for example:

```text
small
medium
large
```

Select actual row counts based on what can be executed reliably in the environment.

A sensible starting range might be approximately:

```text
queries        annotations
1k             10k
10k            100k
100k           1M
```

but do NOT force those values if they make the benchmark impractical in CI/local hardware.

Choose defensible sizes and document why.

---

# 8. Dataset characteristics

Do not benchmark only one easy distribution.

Generate deterministic scenarios that exercise different interval structures.

At minimum consider:

## Sparse

Few overlaps.

## Dense

Many query/annotation overlaps.

## Mixed chromosome distribution

Multiple chromosomes.

## Duplicate intervals

Some duplicated queries/annotations.

Optionally include:

## Stranded workload

If runtime permits.

Do not make benchmark generation excessively complex.

---

# 9. Benchmark operations

At minimum benchmark:

```text
overlap
```

because it is the core backend operation.

If runtime remains practical, also benchmark:

```text
contains
within
closest
```

However, remember that Tasks 6A–6E moved some semantics into shared canonical Python logic.

Be explicit about what each benchmark actually measures.

For example, closest may now use the shared canonical implementation and therefore may show little/no backend difference.

That is scientifically meaningful and must not be hidden.

---

# 10. Benchmark metrics

Measure at least:

* wall-clock runtime;
* result row count as a correctness checksum.

If practical and reliable, also record:

* peak memory / RSS.

Do not invent precision the environment cannot support.

Do not report CPU-time microbenchmarks as if they were full application latency.

---

# 11. Benchmark methodology

Use repeated runs.

Separate warm-up from measured runs where applicable.

Document:

* machine/environment;
* CPU architecture;
* Python version;
* dependency versions;
* Bedtools version;
* number of repetitions;
* dataset seed;
* dataset size;
* operation/options;
* whether timing includes canonicalization;
* whether file I/O is included.

Prefer a reproducible script such as:

```text
benchmarks/benchmark_engines.py
```

with deterministic CLI options.

---

# 12. Correctness during benchmarking

Every benchmark scenario must verify result equivalence before performance numbers are accepted.

At minimum compare:

* canonical row count;
* canonical frame equality using the existing strict comparator or equivalent contract logic.

A faster wrong result is not a valid benchmark result.

Benchmark execution should fail loudly if backend parity fails.

---

# 13. Statistical reporting

Do not report a single lucky timing.

For each scenario/backend report something like:

```text
median
min/max or spread
N repetitions
```

Optionally use IQR if convenient.

Avoid overcomplicated statistical analysis.

The goal is reproducibility, not a performance paper.

---

# 14. Benchmark output

Produce machine-readable benchmark output, for example:

```text
benchmarks/results/*.csv
```

or a single documented result table.

Do not commit huge generated datasets.

Synthetic benchmark inputs should be generated on demand.

If committing benchmark result files, make clear:

* date;
* environment;
* hardware;
* commit;
* versions.

---

# 15. Benchmark interpretation

Do not reduce the findings to:

```text
Polars-Bio is X times faster
```

without context.

Discuss:

* workload dependence;
* dataset size;
* density;
* startup/serialization overhead;
* shared canonical post-processing;
* where backend differences matter;
* where they do not.

If Bedtools wins some workloads, report it.

If Polars-Bio wins some workloads, report it.

If they are effectively equal somewhere, report that.

---

# 16. UI performance wording

Task 7 deliberately avoided unverified performance claims.

Only after benchmark results exist may you decide whether wording such as:

```text
Polars-Bio — high-performance implementation
```

is justified.

Do not add it automatically.

Preferred approach:

* keep neutral UI wording unless benchmark evidence is strong and representative;
* report benchmark results in documentation instead.

UI labels should remain concise and stable.

---

# 17. Benchmark reproducibility documentation

Add a focused document such as:

```text
docs/benchmark.md
```

Document:

* purpose;
* methodology;
* synthetic data generation;
* commands;
* environment;
* results;
* interpretation;
* limitations.

Anyone cloning the repository should be able to reproduce the benchmark.

---

# 18. README refresh

Update README so it accurately reflects the completed project.

It should clearly communicate:

* what AnnotateR does;
* supported inputs;
* canonical coordinate behavior at a user-appropriate level;
* available operations:

  * overlap
  * minimum query overlap
  * strand-aware matching
  * contains
  * within
  * closest
* Bedtools and Polars-Bio backends;
* parity guarantee on supported semantics;
* quick installation/run;
* Docker;
* testing status;
* documentation links;
* citation information;
* deployment link/instructions where appropriate.

Avoid implementation-detail overload in the opening sections.

---

# 19. QUICKSTART refresh

QUICKSTART should allow a new user to go from clone/install to running the app quickly.

Keep it concise.

Cover:

```text
install
run
upload
configure
annotate
download
```

Do not duplicate the entire README.

---

# 20. Supported-semantics table

Add a clear table somewhere appropriate, preferably README or engine-contract docs:

```text
Operation        Bedtools   Polars-Bio   Canonical semantics
Overlap          ✓          ✓            positive half-open overlap
min_overlap      ✓          ✓            query-relative fraction
Strand           ✓          ✓            same explicit strand
Contains         ✓          ✓            query contains annotation
Within           ✓          ✓            query within annotation
Closest          ✓          ✓            canonical gap distance/all ties
```

Do not imply that native backend implementations themselves necessarily provide these semantics.

AnnotateR provides them.

---

# 21. Limitations

Create one honest limitations section.

Potential items include:

* currently supported file formats;
* canonical coordinate assumptions;
* supported Python/runtime;
* Docker architecture constraint if still applicable;
* very large-file memory behavior;
* Streamlit/UI limitations;
* no streaming/lazy execution yet;
* no `k > 1` nearest ranking;
* no signed/upstream/downstream nearest mode.

Do not list resolved historical bugs as current limitations.

---

# 22. Citation metadata

Audit existing citation metadata.

If the repository already has:

```text
CITATION.cff
```

update it.

If absent and appropriate, create it.

Include only confirmed metadata:

* software title;
* authors/contributors according to repository/project records;
* repository URL;
* license;
* version if one exists;
* preferred citation fields where known.

Do NOT invent:

* DOI;
* journal;
* publication title;
* author identifiers;
* affiliation details.

If no software release/version has been formally chosen, handle that conservatively.

---

# 23. Release/versioning audit

Inspect whether AnnotateR currently has:

* semantic version;
* GitHub release tags;
* package version;
* Docker tag convention.

Do not arbitrarily publish a release or bump to `1.0.0`.

Document the current state and recommend an appropriate release step after manual acceptance.

Actual release creation is outside scope unless repository workflow explicitly places it in Task 8.

---

# 24. Repository hygiene

Before declaring Task 8 complete, inspect for:

* stale branch-specific docs;
* old experimental labels;
* stale TODOs that are actually resolved;
* tracked runtime files;
* `.pi` artifacts;
* benchmark temporary files;
* local result artifacts;
* large files;
* secrets;
* obsolete dependency references.

Do not perform unrelated refactoring.

---

# 25. CI deployment/reproducibility checks

Audit whether CI should include:

* full pytest suite;
* Docker build;
* lightweight benchmark smoke test;
* benchmark correctness check.

Do NOT put the full performance benchmark into normal PR CI if it is expensive or noisy.

A small benchmark smoke test is preferable.

Performance numbers should not act as hard CI thresholds unless a robust reason exists.

Avoid flaky performance gates.

---

# 26. Docker smoke test

Add an automated/lightweight verification if practical that checks the built container can:

* import AnnotateR;
* import both engines;
* find Bedtools;
* start Streamlit or pass an HTTP health check.

Keep CI duration reasonable.

---

# 27. Documentation consistency

Audit all user-facing docs for consistency with final semantics.

Search specifically for stale wording around:

```text
experimental
results may differ
contains placeholder
within placeholder
closest non-normative
Polars-Bio parser
native distance
Bedtools-only
```

Remove/update stale claims.

---

# 28. Do not change scientific behavior

Task 8 MUST NOT redefine:

* overlap;
* min_overlap;
* strand;
* contains;
* within;
* closest;
* canonical coordinates;
* canonical output schema;
* tie behavior;
* distance.

If benchmark/deployment work uncovers a scientific contract bug, report it separately.

Do not silently fix/redefine it inside Task 8.

---

# 29. Review loop

Use independent reviewers if available.

## Reviewer 1 — deployment/reproducibility

Check:

* Docker;
* SciLifeLab Serve requirements;
* runtime/dependency consistency;
* deployment docs;
* reproducibility;
* CI;
* architecture constraint;
* no secrets.

## Reviewer 2 — benchmark/scientific reporting

Check:

* benchmark fairness;
* deterministic data;
* parity assertion before timing;
* repeated measurements;
* honest interpretation;
* no cherry-picking;
* no unsupported performance claims;
* documentation consistency.

Optional Reviewer 3 if available:

## Documentation/release quality

Check:

* README;
* QUICKSTART;
* semantics table;
* limitations;
* citation metadata;
* stale claims.

Resolve all BLOCKER/MAJOR findings.

---

# Acceptance criteria

Task 8 is complete only when:

1. current SciLifeLab Serve requirements have been checked against official documentation;
2. primary deployment references recorded;
3. Docker image builds for the intended production platform;
4. container starts successfully;
5. health/startup verification succeeds;
6. both engines function in the container;
7. dependency definitions are internally consistent;
8. supported/tested versions documented;
9. deployment guide exists and is reproducible;
10. benchmark script is deterministic and reproducible;
11. benchmark uses the real AnnotateR engine path;
12. benchmark verifies parity before accepting timings;
13. representative workloads are included;
14. repeated timings are used;
15. benchmark methodology is documented;
16. benchmark environment/hardware is recorded;
17. benchmark results are machine-readable or clearly tabulated;
18. interpretation is neutral and workload-aware;
19. no unsupported UI performance claim is introduced;
20. README accurately reflects final capabilities;
21. QUICKSTART is current;
22. supported-semantics table exists;
23. current limitations are documented;
24. citation metadata is audited/updated;
25. repository hygiene audit is complete;
26. no secrets/runtime artifacts are committed;
27. CI remains green;
28. Docker/reproducibility smoke checks exist where practical;
29. no scientific semantics changed;
30. full parity suite remains green;
31. full repository suite has zero unexpected FAIL/XPASS;
32. independent reviewers report no unresolved BLOCKER/MAJOR findings.

---

# Benchmark final report requirements

Report actual results without advocacy.

For every benchmark scenario include:

* dataset size;
* dataset characteristics;
* operation;
* engine;
* repetitions;
* median wall time;
* timing spread;
* result row count;
* parity status.

If peak memory is measured, include it separately.

Then summarize observed patterns without declaring an overall winner unless a very narrow factual statement is clearly supported by the measured workloads.

---

# Final verification

Before completion:

1. inspect full diff vs `origin/main`;
2. run full test suite;
3. run parity suite;
4. run Streamlit/AppTest suite;
5. build production Docker image;
6. run Docker smoke test;
7. verify both engines inside container;
8. run benchmark correctness smoke test;
9. run full selected benchmark;
10. inspect benchmark outputs;
11. independently verify at least a sample of reported timing calculations;
12. verify SciLifeLab Serve docs/links are current;
13. inspect README/QUICKSTART;
14. inspect citation metadata;
15. inspect repo for secrets/temp files;
16. run full repository suite again after documentation/deployment changes;
17. report exact PASS/XFAIL/XPASS/FAIL/SKIP.

---

# Git discipline

Use:

`task-8-deployment-docs-benchmark`

Prefer logical commits, for example:

```text
build: refresh production container and deployment checks
bench: add reproducible backend benchmark
docs: document deployment benchmark and final semantics
docs: refresh citation and user documentation
ci: add deployment reproducibility smoke checks
```

Do not manufacture commits unnecessarily.

Open the PR only after reviewer findings are resolved.

Do not merge automatically unless that is the established repository workflow.

Do not create a release/tag unless explicitly required by the repository workflow.

---

# Final report

Return:

* branch;
* base commit;
* commits;
* files changed;
* SciLifeLab Serve requirements verified;
* Docker strategy;
* target platform/architecture;
* container smoke results;
* exact supported/tested runtime versions;
* dependency consistency audit;
* deployment documentation summary;
* benchmark methodology;
* synthetic dataset strategy;
* benchmark operations/scenarios;
* exact benchmark results;
* parity verification strategy;
* benchmark interpretation;
* memory results if measured;
* UI performance wording decision and rationale;
* README/QUICKSTART changes;
* supported-semantics documentation;
* limitations;
* citation metadata changes;
* release/versioning recommendation;
* CI changes;
* repository hygiene findings;
* exact parity test counts;
* exact Streamlit/AppTest counts;
* exact repository-wide PASS/XFAIL/XPASS/FAIL/SKIP;
* reviewer findings and resolutions;
* acceptance criteria status one by one;
* remaining deferred ideas from PLAN;
* explicit confirmation that scientific semantics were not changed.

Do not start deferred work after Task 8.
