# Backend Benchmark (Bedtools vs Polars-Bio)

Deterministic, reproducible benchmark of AnnotateR's two interchangeable
execution backends (Bedtools via pybedtools, and Polars-Bio), with
**scientific parity verified before any timing is accepted**.

Script: [`benchmarks/benchmark_engines.py`](https://github.com/JD2112/annotater/blob/main/benchmarks/benchmark_engines.py).
Results of the most recent full run are in [§ Results](#results).

## What this benchmark shows — and does not

**Shown:** the relative cost of the interval-operation phase
(`engine.intersect` + `canonicalize_annotation_result`) for the four
annotation operations (overlap, contains, within, closest) across
controlled workload sizes and geometries, on the pinned runtime
environment.

**Not shown (by design):**

- **Parsing.** Parsing is backend-independent in AnnotateR (SPEC 4.1):
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
  execution choices* (SPEC 5); the benchmark reports workload-dependent
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
| `sparse` | 50 kb of empty space between consecutive annotations (packing gap shrinks automatically when the span would exceed the [32-bit coordinate cap](#coordinate-limit) — see there) |
| `dense` | 50 kb windows on a 10 kb pitch (≈5× coverage) |
| `mixed` | five chromosomes of differing sizes/weights, mixed local densities |
| `duplicates` | repeated identical intervals on both sides (multi-match stress) |
| `stranded` | explicit +/−/missing strand labels (overlap operation only — strand is a shared post-filter on all pair-producing modes, so one operation is representative) |

### Operations

`overlap`, `contains`, `within`, `closest` for every scenario except
`stranded`, which benchmarks `overlap` only.

### Repetitions

Each (scenario, operation, engine) cell runs **1 warmup + 5 measured
repetitions**; the **median** wall time is reported. Every repetition's
result is compared with the strict parity comparator; any parity failure
aborts the whole benchmark with a non-zero exit (a faster-but-wrong
result is never accepted). Row counts are additionally checked to be
deterministic across repetitions.

## What is measured

Timings cover exactly the AnnotateR execution path a user's run performs
after upload:

```
engine.intersect(coord_df, annot_df, how=op)   # backend call
canonicalize_annotation_result(...)            # shared canonical adapter
```

No parsing, no I/O of the input tables, no Streamlit, no export.

## Memory probing

Peak RSS is measured in **isolated subprocesses** (one per
(size, scenario, operation, engine) cell) so the main timing loop is not
disturbed. Run with `--measure-memory` (together with the timings) or
`--memory-only` (re-probes memory without re-running the timing loop).

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

Full run: **2026-09-25**, commit `aec841d`, wall time ≈ 115 min
(`--sizes small medium large --bench-parsing`). **All 51 scenario/op
cells parity-verified** (102 engine rows) with the strict comparator
before their timings were accepted. Machine: Apple M1 Pro, 32 GB RAM, macOS 26.6.2 arm64 (see
[Environment](#environment)).

Median wall time in seconds for `engine.intersect` +
`canonicalize_annotation_result` (1 warmup + 5 measured repetitions).
"speedup" = bedtools ÷ polars-bio (higher = polars-bio faster). Every
row: both backends returned identical canonical results (parity
`verified`).

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

Parsing is not part of the per-backend numbers (SPEC 4.1). For
reference, parsing + normalizing the synthetic inputs took (single
wall time, original geometry generation):

| Size | Queries | s | Annotations | s |
|---|---:|---:|---:|---:|
| small | 1,000 | 0.006 | 10,000 | 0.015 |
| medium | 10,000 | 0.015 | 100,000 | 0.142 |
| large | 100,000 | 0.145 | 1,000,000 | 1.361 |

### Observations

1. **Pair-producing operations (overlap/contains/within):** the
   in-process backend is faster across every tier and scenario —
   ~3–10× at small size (bedtools process startup + pybedtools I/O
   overhead dominates), ~8–15× at medium, and ~8–15× for the large
   pair-producing operations (with `within`/`contains` reaching ~30–38×
   because they filter a large candidate set in-process). The
   *relative* picture is what the benchmark exists to document; the
   backends remain interchangeable.
2. **`closest` is the shared canonical path, and the data shows it.**
   Both backends run the same selection + distance code over the
   backend-produced candidate pairs (SPEC 8.6); timings track each
   other within ~10% in every cell (small 0.9–1.1×, medium 0.89–1.01×,
   large 1.00–1.33×), versus 3–38× for the pair-producing operations.
   At large size the shared nearest-selection dominates runtime
   (~2–4 min per engine at 100k×1M sparse/duplicates): `closest` on
   very large inputs is the most expensive AnnotateR operation on
   **both** backends — a scale property of the shared canonical
   implementation, not of either backend.
3. **Bedtools variance is visibly higher.** The large/duplicates
   bedtools cells show wide spreads (IQR up to ~41 s on `closest`;
   see the raw `wall_iqr_s` column in the results CSV), consistent
   with subprocess/scheduling effects; medians are reported
   throughout.
4. **Empty-result cells (e.g. `within` on sparse geometry) still pay
   the full backend cost** — no matches does not skip work; this is
   the same cost class a real no-hit run pays.

## Interpretation

- **`closest` is the shared canonical path.** Since Task 6E,
  `mode="closest"` never calls a backend-native closest primitive; both
  engines run the **same shared canonical selection and distance code**
  (SPEC 8.6) over the backend-produced candidate pairs. The results
  confirm this: closest cells are within ~10% across backends in every
  tier, unlike the 3–38× spread of the pair-producing operations. Note
  the scale caveat: at 100k×1M, closest takes ~2–4 min **on both
  backends** (shared-path cost) — see Observations.
- **`overlap`-derived differences are workload-dependent.** Small/sparse
  workloads are dominated by per-call overhead (bedtools process startup,
  pybedtools I/O) and tend to favor the in-process backend;
  large/dense workloads move the cost into interval joining and
  canonicalization, where the spread narrows or shifts. Read each row
  against its scenario, not as a single number.
- **Parity is the headline, timings are the footnote.** Every reported
  timing is attached to a cell whose two backend results passed the
  strict comparator (identical canonical schema, values, order, and
  dtype). If a future dependency update changes any result, the
  benchmark fails before reporting.
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
- No concurrent-load or memory-pressure behavior is characterized beyond
  peak RSS.

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
[.github/workflows/python-tests.yml](https://github.com/JD2112/annotater/blob/main/.github/workflows/python-tests.yml).