# Backend Benchmark (Bedtools vs Polars-Bio)

Deterministic, reproducible benchmark of AnnotateR's two interchangeable
execution backends (Bedtools via pybedtools, and Polars-Bio). A strict
canonical parity check is applied to each cell's final result, and a
mismatch aborts the run before any result is reported.

Script: [`benchmarks/benchmark_engines.py`](https://github.com/pyrevo/annotater/blob/main/benchmarks/benchmark_engines.py).
Results of the most recent full run are in [§ Results](#results).

## What this benchmark shows — and does not

**Shown:** the relative cost of the interval-operation phase
(`engine.intersect` + `canonicalize_annotation_result`) for the four
annotation operations (overlap, contains, within, closest) across
controlled workload sizes and geometries, on the pinned runtime
environment.

**Not shown (by design):**

- **Parsing.** Parsing is backend-independent in AnnotateR (SPEC §4, invariant 1):
  both backends consume the same canonical coordinate/annotation
  DataFrames. Parsing cost is recorded separately as reference data
  (`benchmark_parsing_*.csv`), never inside per-backend timings.
- **UI / Streamlit rendering, export, and network.** The benchmark
  exercises the engine path only.
- **Absolute portability.** Numbers are from one machine (see
  [Environment](#environment)). The production Docker image runs
  `linux/amd64`; relative behavior is expected to hold, but do not
  transfer absolute numbers across machines.
- **A performance ranking as such.** The two backends are *interchangeable
  execution choices* (SPEC §1 and §4); the benchmark reports workload-dependent
  differences, not a "winner".

## Workloads

Deterministic synthetic genomic tables (fixed seed `20260925`; geometry
and table contents are reproducible bit-for-bit).

### Size tiers

| Tier | Queries | Annotations |
|---|---:|---:|
| small | 1,000 | 10,000 |
| medium | 10,000 | 100,000 |
| large | 100,000 | 1,000,000 |

### Scenarios (geometry)

| Scenario | Geometry |
|---|---|
| `sparse` | nominally 50 kb of empty space between consecutive annotations. The packing gap shrinks automatically when the span would exceed the [32-bit coordinate cap](#coordinate-limit), so at the larger tiers the layout is **denser than the nominal 50 kb gap implies** (for example, the 100,000 × 1,000,000 `sparse` overlap run returns ≈2.6 million rows). Read `sparse` as the scenario's name, not as a density guarantee at every scale |
| `dense` | 50 kb windows on a 10 kb pitch (≈5× coverage) |
| `mixed` | five chromosomes of differing sizes/weights, mixed local densities |
| `duplicates` | repeated identical intervals on both sides (multi-match stress) |
| `stranded` | explicit +/−/missing strand labels (overlap operation only — strand is a shared post-filter on all pair-producing modes, so one operation is representative) |

### Operations

`overlap`, `contains`, `within`, `closest` for every scenario except
`stranded`, which benchmarks `overlap` only.

### Repetitions

Each (scenario, operation, engine) cell runs **1 warmup + 5 measured
repetitions**; the **median** wall time is reported. Two checks apply:

- **Row counts** are checked to be identical across the measured
  repetitions of each engine; a difference aborts the benchmark.
- **Strict canonical parity** (the same comparator as the parity test
  suite) is performed **once per cell, on the final result of each
  engine** — not on every repetition. Any parity failure aborts the
  whole benchmark with a non-zero exit, so a faster-but-wrong result is
  not reported.

## What is measured

Timings cover exactly the AnnotateR execution path a user's run performs
after upload:

```
engine.intersect(coord_df, annot_df, how=op)   # backend call
canonicalize_annotation_result(...)            # shared canonical adapter
```

No parsing, no I/O of the input tables, no Streamlit, no export.

## Memory probing

The script can probe peak RSS in **isolated subprocesses** (one per
(size, scenario, operation, engine) cell) so the main timing loop is not
disturbed, using `--measure-memory` (together with the timings) or
`--memory-only`. The probe reads `RUSAGE_SELF` of the worker process, so
it reflects that Python process only and **does not include the memory
of the `bedtools` child process** started by the Bedtools engine. No
memory values are published on this page, and memory should not be
compared between the two backends on the basis of this probe.

## Coordinate limit

The Bedtools backend runs bedtools **via pybedtools**, whose Cython
iterator packs record positions into a 32-bit `CHRPOS` field: coordinates
≥ 2³¹ (2,147,483,647) raise `OverflowError`. This is a hard input limit
of `BedtoolsEngine` as implemented (discovered empirically when the first
benchmark attempt generated a 10 Gb synthetic chromosome; the bedtools
CLI itself is not limited this way). Benchmark geometry therefore adapts
its packing to stay below the cap, and a defensive assertion rejects any
generated coordinate at/above it. Every natural chromosome is far below
this bound (human chr1 ≈ 250 Mb), so real genomic data is unaffected.
See [docs/references.md](references.md) (pybedtools).

## Environment

- Apple M1 Pro, 32 GB RAM, macOS 26.6.2 (arm64)
- Python 3.12.14
- pandas 3.0.6, numpy 2.5.3
- polars 1.44.2, polars-bio 0.35.1 (pinned)
- pybedtools 0.12.1, bedtools 2.31.1 (Homebrew, arm64-native)

Timings were taken on the local (arm64) environment, not inside the
`linux/amd64` Docker image; see Interpretation.

## Results

Full run: **2026-09-25**, wall time ≈ 115 min
(`--sizes small medium large --bench-parsing`). **All 51 scenario/op
cells passed the strict canonical parity check** (102 engine rows),
applied to each cell's final result. Machine: Apple M1 Pro, 32 GB RAM, macOS 26.6.2 arm64 (see
[Environment](#environment)).

Median wall time in seconds for `engine.intersect` +
`canonicalize_annotation_result` (1 warmup + 5 measured repetitions).
"speedup" = bedtools ÷ polars-bio (higher = polars-bio faster). Every
row: both backends returned identical canonical results (parity
`verified`).

**Provenance.** The run was made from a working tree based on commit
`aec841d`. That commit does not itself contain the benchmark script
(`benchmarks/benchmark_engines.py` was added later, in `999955f`), so
the numbers below are **not tied to a clean, immutable commit**. They
have not been regenerated since the later input, VCF-export and
UI-state changes (Tasks A–C); they characterize the engine path as it
was at the time of the run.

**Reading the tables.** Cells with `within` or `contains` that return
0–12 result rows (marked by the *Result rows* column) time a run whose
output is empty or nearly empty; their large speedups say nothing about
the cost of producing pairs and should not be generalized.

### small — 1,000 queries × 10,000 annotations

| Scenario | Op | Result rows | bedtools | polars-bio | speedup |
|---|---|---:|---:|---:|---:|
| sparse | overlap | 1,096 | 0.057 | 0.011 | 5.0× |
| sparse | contains | 897 | 0.052 | 0.009 | 5.5× |
| sparse | within | 0 | 0.047 | 0.013 | 3.6× |
| sparse | closest | 1,096 | 0.037 | 0.037 | 1.0× |
| dense | overlap | 9,899 | 0.095 | 0.014 | 6.6× |
| dense | contains | 0 | 0.090 | 0.009 | 10.2× |
| dense | within | 0 | 0.093 | 0.012 | 7.7× |
| dense | closest | 9,899 | 0.054 | 0.058 | 0.9× |
| mixed | overlap | 562 | 0.045 | 0.011 | 4.3× |
| mixed | contains | 458 | 0.046 | 0.011 | 4.4× |
| mixed | within | 0 | 0.046 | 0.009 | 5.3× |
| mixed | closest | 1,055 | 0.023 | 0.022 | 1.0× |
| duplicates | overlap | 1,329 | 0.066 | 0.011 | 5.8× |
| duplicates | contains | 1,079 | 0.060 | 0.010 | 5.7× |
| duplicates | within | 0 | 0.056 | 0.010 | 5.8× |
| duplicates | closest | 1,329 | 0.047 | 0.044 | 1.1× |
| stranded | overlap | 176 | 0.052 | 0.016 | 3.3× |

### medium — 10,000 queries × 100,000 annotations

| Scenario | Op | Result rows | bedtools | polars-bio | speedup |
|---|---|---:|---:|---:|---:|
| sparse | overlap | 25,613 | 0.425 | 0.030 | 14.1× |
| sparse | contains | 20,940 | 0.410 | 0.030 | 13.5× |
| sparse | within | 0 | 0.431 | 0.022 | 19.6× |
| sparse | closest | 25,616 | 1.72 | 1.84 | 0.94× |
| dense | overlap | 99,919 | 0.876 | 0.080 | 11.0× |
| dense | contains | 3 | 0.868 | 0.029 | 30.1× |
| dense | within | 3 | 0.892 | 0.024 | 36.7× |
| dense | closest | 99,925 | 0.61 | 0.60 | 1.01× |
| mixed | overlap | 5,466 | 0.268 | 0.021 | 13.0× |
| mixed | contains | 4,477 | 0.290 | 0.025 | 11.8× |
| mixed | within | 0 | 0.285 | 0.015 | 18.5× |
| mixed | closest | 10,495 | 0.39 | 0.41 | 0.94× |
| duplicates | overlap | 30,983 | 0.524 | 0.034 | 15.4× |
| duplicates | contains | 25,315 | 0.544 | 0.041 | 13.4× |
| duplicates | within | 0 | 0.496 | 0.022 | 23.0× |
| duplicates | closest | 30,986 | 1.96 | 2.21 | 0.89× |
| stranded | overlap | 1,884 | 0.264 | 0.029 | 9.1× |

### large — 100,000 queries × 1,000,000 annotations

| Scenario | Op | Result rows | bedtools | polars-bio | speedup |
|---|---|---:|---:|---:|---:|
| sparse | overlap | 2,564,226 | 18.2 | 1.84 | 9.9× |
| sparse | contains | 2,093,502 | 17.9 | 1.83 | 9.8× |
| sparse | within | 0 | 17.5 | 0.46 | 38.2× |
| sparse | closest | 2,564,315 | 194 | 192 | 1.01× |
| dense | overlap | 999,899 | 8.71 | 0.77 | 11.3× |
| dense | contains | 12 | 8.42 | 0.27 | 30.7× |
| dense | within | 12 | 8.02 | 0.24 | 33.6× |
| dense | closest | 999,923 | 11.8 | 11.0 | 1.08× |
| mixed | overlap | 511,977 | 5.46 | 0.43 | 12.7× |
| mixed | contains | 418,008 | 5.42 | 0.40 | 13.5× |
| mixed | within | 0 | 5.53 | 0.17 | 32.5× |
| mixed | closest | 512,003 | 37.2 | 37.1 | 1.00× |
| duplicates | overlap | 3,102,598 | 28.2 | 3.48 | 8.1× |
| duplicates | contains | 2,532,505 | 28.9 | 3.35 | 8.6× |
| duplicates | within | 0 | 26.3 | 0.81 | 32.5× |
| duplicates | closest | 3,102,708 | 250 | 188 | 1.33× |
| stranded | overlap | 164,200 | 5.26 | 0.35 | 15.2× |

### Parsing (backend-independent, reference only)

Parsing is not part of the per-backend numbers (SPEC §4, invariant 1). For
reference, parsing + normalizing the synthetic inputs took (single
wall time, original geometry generation):

| Size | Queries | s | Annotations | s |
|---|---:|---:|---:|---:|
| small | 1,000 | 0.006 | 10,000 | 0.015 |
| medium | 10,000 | 0.015 | 100,000 | 0.142 |
| large | 100,000 | 0.145 | 1,000,000 | 1.361 |

### Observations

1. **Pair-producing operations (overlap/contains/within):** on these
   workloads the in-process backend was faster in every cell. Speedups
   (bedtools ÷ polars-bio) were 3.3–10.2× at small size (where bedtools
   process startup and pybedtools I/O overhead is a large share of the
   time), 9.1–36.7× at medium, and 8.1–38.2× at large. For `overlap`
   alone the range is 4.3–6.6× (small, excluding `stranded`), 11.0–15.4×
   (medium) and 8.1–12.7× (large). The `contains`/`within` cells at the
   top of these ranges are largely cells whose output is empty or nearly
   empty (see the note under *Results*), so they are not representative
   of pair-producing cost. The backends remain interchangeable.
2. **`closest` is the shared canonical path, and the data is consistent
   with that.** `mode="closest"` makes no backend call: both engines run
   the same shared canonical selection and distance code (SPEC §8.6).
   Timings are within about 10% of each other in every cell except
   large/duplicates (1.33×): small 0.9–1.1×, medium 0.89–1.01×, large
   1.00–1.33×, versus the much larger differences for the
   pair-producing operations. At large size `closest` took about 3–4
   minutes per engine on 100k×1M sparse and duplicates workloads, the
   slowest cells in the table: on these inputs it is the most expensive
   operation on **both** backends — a property of the shared canonical
   implementation, not of either backend.
3. **Bedtools variance is higher in some cells.** The large/duplicates
   bedtools cells showed wide spreads in the original run (the raw
   `wall_iqr_s` column of the results CSV, which is not committed to the
   repository); medians are reported throughout. No cause was
   established.
4. **Empty-result cells (e.g. `within` on sparse geometry) still pay
   the backend cost** — no matches does not skip work. Their timings
   should be read as the cost of a no-hit run, not as a measure of
   pair-producing work.

## Interpretation

- **`closest` is the shared canonical path.** Since Task 6E,
  `mode="closest"` makes no backend call and uses no backend-native
  closest primitive; both engines run the **same shared canonical
  selection and distance code** (SPEC §8.6). The two engines'
  `closest` timings therefore mostly measure that shared code. Note the
  scale caveat: at 100k×1M, `closest` took about 3–4 minutes **on both
  backends** — see Observations.
- **`overlap`-derived differences are workload-dependent.** Small
  workloads include a large share of per-call overhead (bedtools process
  startup, pybedtools I/O); at larger sizes more of the cost is interval
  joining and canonicalization, and the ratio varies by scenario
  without a monotonic trend across tiers. Read each row against its
  scenario, not as a single number.
- **Parity is the headline, timings are the footnote.** Every reported
  cell's final result passed the strict comparator for both backends
  (identical canonical schema, values, order, and dtype); individual
  repetitions are checked for row-count determinism only. If a future
  dependency update changes a final result, the benchmark fails before
  reporting.
- **Single-platform, single-machine data.** No cross-platform
  comparison is made. The production image (`linux/amd64`) was smoke-
  verified for parity (CI `docker-smoke` job), not re-timed.

## Limitations

- **32-bit coordinate cap on the Bedtools backend** (see
  [Coordinate limit](#coordinate-limit)); unreachable with real genomic
  chromosomes.
- Synthetic workloads, not real genomics files: real GFF/BED files have
  different duplicate/strand/multi-chromosome structure; the scenario
  matrix approximates but does not reproduce production data shapes.
- No end-to-end (parse→annotate→export) timing; see
  [What this benchmark shows](#what-this-benchmark-shows-and-does-not).
- No concurrent-load or memory-pressure behavior is characterized, and
  no memory results are published (the optional RSS probe excludes the
  `bedtools` child process).
- Results are from a working tree that cannot be identified with a
  clean commit (see *Provenance* under Results).

## Reproducing

From the repository root (with `bedtools` on `PATH`):

```bash
# Fast CI-style smoke: small/sparse/overlap, 2 reps + parsing reference.
# Its parity gate is what CI runs in the production image.
.venv/bin/python benchmarks/benchmark_engines.py --quick

# Full benchmark (all sizes/scenarios/operations; memory probe optional).
.venv/bin/python benchmarks/benchmark_engines.py \
  --sizes small medium large --bench-parsing --measure-memory

# Memory probes only (skips the timing loop).
.venv/bin/python benchmarks/benchmark_engines.py --memory-only
```

Geometry and result tables are fully deterministic under the default
seed; **timings are not** (machine load, thermals). Results are written
to `benchmarks/results/` (git-ignored). The full run is deliberately
**not** a CI gate — see
[.github/workflows/python-tests.yml](https://github.com/pyrevo/annotater/blob/main/.github/workflows/python-tests.yml).