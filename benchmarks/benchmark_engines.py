#!/usr/bin/env python3
"""
AnnotateR backend benchmark (PLAN Task 8).

Purpose
-------
Measure the performance characteristics of the two semantically equivalent
AnnotateR backends (BedtoolsEngine and PolarsBioEngine) under
representative, controlled, fully synthetic workloads.  This benchmark is
NOT a claim that either backend is better in general; it characterizes the
real AnnotateR execution path:

    canonical interval table
        -> engine.intersect(...)          (the exact engine call the app makes)
        -> canonicalize_annotation_result (the exact result adapter the app uses)

Parsing is backend-independent (SPEC 4.1) and is benchmarked separately as
informational reference data, never inside the per-backend timings.

Correctness gate
----------------
For every (size, scenario, operation) the canonical results of both engines
are compared with the SAME strict comparator the parity suite uses
(same strict comparator the parity suite uses, now shared via
``streamlit_app/core/comparison.py`` and re-exported by
``tests/parity/comparator.py``).  If parity fails,
the benchmark aborts with a non-zero exit code: a faster wrong result is not
a valid benchmark result.  The per-scenario result row count is recorded as
a correctness checksum.

``mode="closest"`` is benchmarked like the others, but both engines
delegate it to the shared canonical implementation (SPEC 8.6; Task 6E
removed all backend-native closest/nearest calls).  Its numbers therefore
measure the shared path plus per-engine input validation and are expected
to be nearly identical; that is the scientifically meaningful result, not
an artifact to hide.

Determinism
-----------
All datasets are generated from a fixed seed (``--seed``, default 20260925)
with ``numpy.random.default_rng``.  Datasets are generated in memory on
demand; nothing large is written to disk except the result CSV/JSON in
``--output``.

Run (from the repository root; see docs/benchmark.md for the full
methodology):

    python benchmarks/benchmark_engines.py                      # small+medium
    python benchmarks/benchmark_engines.py --sizes small medium large
    python benchmarks/benchmark_engines.py --quick              # CI smoke
    python benchmarks/benchmark_engines.py --measure-memory     # + peak RSS
"""

from __future__ import annotations

import argparse
import json

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# Make the repository root importable regardless of the caller's cwd.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd

from streamlit_app.core.annotator import BedtoolsEngine, PolarsBioEngine
from streamlit_app.core.comparison import assert_canonical_equal
from streamlit_app.core.normalization import parse_and_normalize
from streamlit_app.core.schema import canonicalize_annotation_result

# ---------------------------------------------------------------------------
# Scenario configuration
# ---------------------------------------------------------------------------

#: (n_queries, n_annotations) per size tier.  Chosen so the largest tier
#: (100k x 1M) runs in a couple of minutes per scenario on a modern laptop
#: with ~32 GB RAM while still exercising the 1M-annotation regime.  See
#: docs/benchmark.md for the rationale.
SIZES = {
    "small": (1_000, 10_000),
    "medium": (10_000, 100_000),
    "large": (100_000, 1_000_000),
}

SCENARIOS = ("sparse", "dense", "mixed", "duplicates", "stranded")

OPERATIONS = ("overlap", "contains", "within", "closest")

#: The stranded scenario only benchmarks overlap: it exists to exercise
#: strand filtering, and SPEC 8.3 strand qualification is a shared
#: post-filter on all pair-producing modes, so one operation is
#: representative without multiplying runtime.
STRANDED_OPERATIONS = ("overlap",)

DEFAULT_SEED = 20260925

#: sparse/mixed geometry: 50 kb of empty space between consecutive
#: annotations on a chromosome -> low overlap probability.
_SPARSE_GAP = 50_000
#: dense geometry: 50 kb windows on a 10 kb pitch -> ~5x coverage.
_DENSE_LENGTH = 50_000
_DENSE_STEP = 10_000

#: Maximum representable coordinate (exclusive): 2**31 - 1.
#
#: The Bedtools backend goes through pybedtools, whose Cython iterator
#: packs positions into a 32-bit ``CHRPOS`` field; coordinates >= 2**31
#: raise ``OverflowError`` (verified empirically during Task 8).  The
#: bedtools CLI itself is not limited this way, but AnnotateR's
#: BedtoolsEngine is (see docs/benchmark.md, Limitations).  Every natural
#: chromosome is far below this bound (human chr1 ~= 250 Mb), so the cap
#: does not change what AnnotateR can run on real genomic data.
_MAX_COORD = 2**31 - 1
#: Headroom kept below the cap for query lengths.
_COORD_MARGIN = 50_000


def _fit_gap(n: int, desired: int = _SPARSE_GAP) -> int:
    """Largest packing gap <= ``desired`` that keeps ``n * gap`` within the
    32-bit coordinate limit (plus margin).  Returns ``desired`` unchanged
    when the span already fits."""
    max_span = _MAX_COORD - _COORD_MARGIN
    if n * desired <= max_span:
        return desired
    return max(1, max_span // n)
#: mixed scenario: five chromosomes with different sizes/weights.
_MIXED_CHROMS = (
    ("chr1", 0.40),
    ("chr2", 0.25),
    ("chr3", 0.15),
    ("chr4", 0.12),
    ("chrM", 0.08),
)


def _uniform_lengths(rng: np.random.Generator, n: int, lo: int, hi: int) -> np.ndarray:
    return rng.integers(lo, hi + 1, size=n, dtype=np.int64)


def _sparse_table(rng: np.random.Generator, n: int, id_prefix: str,
                  meta_prefix: str, gap: int = _SPARSE_GAP) -> pd.DataFrame:
    """One chromosome, annotations packed with ``gap`` bp between them."""
    starts = np.arange(n, dtype=np.int64) * gap
    ends = starts + _uniform_lengths(rng, n, 100, 10_000)
    return pd.DataFrame({
        "chr": np.full(n, "chr1", dtype=object),
        "start": starts,
        "end": ends,
        f"{meta_prefix}": [f"{id_prefix}{i}" for i in range(n)],
    })


def _dense_table(rng: np.random.Generator, n: int, id_prefix: str,
                 meta_prefix: str) -> pd.DataFrame:
    """25 synthetic chromosomes tiled with 50 kb windows on a 10 kb pitch."""
    n_chroms = 25
    per = [n // n_chroms] * n_chroms
    for i in range(n % n_chroms):
        per[i] += 1
    rows = []
    idx = 0
    for c in range(n_chroms):
        count = per[c]
        starts = np.arange(count, dtype=np.int64) * _DENSE_STEP
        rows.append(pd.DataFrame({
            "chr": np.full(count, f"chr{c + 1}", dtype=object),
            "start": starts,
            "end": starts + _DENSE_LENGTH,
            f"{meta_prefix}": [f"{id_prefix}{idx + i}" for i in range(count)],
        }))
        idx += count
    return pd.concat(rows, ignore_index=True)


def _mixed_table(rng: np.random.Generator, n: int, id_prefix: str,
                 meta_prefix: str, with_strand: bool) -> pd.DataFrame:
    """Sparse packing distributed across five chromosomes of different
    relative sizes (weight = share of the annotation rows).  Each
    chromosome's gap is adapted by ``_fit_gap`` so the span stays within
    the 32-bit coordinate limit."""
    counts = [int(round(n * w)) for _, w in _MIXED_CHROMS]
    counts[0] += n - sum(counts)  # absorb rounding
    rows = []
    idx = 0
    for (chrom, _), count in zip(_MIXED_CHROMS, counts):
        gap = _fit_gap(count)
        starts = np.arange(count, dtype=np.int64) * gap
        rows.append(pd.DataFrame({
            "chr": np.full(count, chrom, dtype=object),
            "start": starts,
            "end": starts + _uniform_lengths(rng, count, 100, 10_000),
            f"{meta_prefix}": [f"{id_prefix}{idx + i}" for i in range(count)],
        }))
        idx += count
    table = pd.concat(rows, ignore_index=True)
    if with_strand:
        # ~80% explicit strand, ~20% canonical missing (never a wildcard,
        # SPEC 8.3): deterministic mix from the same rng stream.
        explicit = rng.random(n) < 0.8
        strands = rng.choice(["+", "-"], size=n)
        table["strand"] = pd.Series(
            [strands[i] if explicit[i] else pd.NA for i in range(n)],
            dtype=object,
        )
    return table


def _add_duplicates(rng: np.random.Generator, table: pd.DataFrame,
                    frac: float = 0.10) -> pd.DataFrame:
    """Append exact copies of ~10% of the rows, then deterministically
    interleave (SPEC 6: duplicated input rows must not be collapsed)."""
    n = len(table)
    k = int(n * frac)
    if k:
        idx = rng.choice(n, size=k, replace=False)
        table = pd.concat([table, table.iloc[idx]], ignore_index=True)
    order = rng.permutation(len(table))
    return table.iloc[order].reset_index(drop=True)


def _query_table(rng: np.random.Generator, n: int, chrom_names, span,
                 length: int, with_strand: bool) -> pd.DataFrame:
    """Queries placed uniformly over the scenario span on the scenario's
    chromosomes; a fixed query length keeps the expected per-query overlap
    count controlled by the scenario geometry alone."""
    c = rng.integers(0, len(chrom_names), size=n)
    pos = rng.integers(0, span, size=n, dtype=np.int64)
    strands = None
    if with_strand:
        explicit = rng.random(n) < 0.8
        s = rng.choice(["+", "-"], size=n)
        strands = [s[i] if explicit[i] else pd.NA for i in range(n)]
    df = pd.DataFrame({
        "chr": [chrom_names[i] for i in c],
        "start": pos,
        "end": pos + length,
        "name": [f"q{i}" for i in range(n)],
    })
    if with_strand:
        df["strand"] = pd.Series(strands, dtype=object)
    return df


def generate_scenario(scenario: str, n_queries: int, n_annotations: int,
                      seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Deterministic canonical (0-based half-open) query/annotation tables."""
    rng = np.random.default_rng(seed)
    with_strand = scenario == "stranded"
    query_length = _DENSE_LENGTH if scenario == "dense" else 50_000

    if scenario in ("sparse", "duplicates"):
        gap = _fit_gap(n_annotations)
        annot = _sparse_table(rng, n_annotations, "a", "feature", gap=gap)
        span = n_annotations * gap + query_length
        queries = _query_table(rng, n_queries, ("chr1",), span,
                               query_length, with_strand)
        if scenario == "duplicates":
            queries = _add_duplicates(rng, queries)
            annot = _add_duplicates(rng, annot)
    elif scenario == "dense":
        annot = _dense_table(rng, n_annotations, "a", "feature")
        span = (n_annotations // 25 + 1) * _DENSE_STEP
        queries = _query_table(rng, n_queries,
                               tuple(f"chr{c + 1}" for c in range(25)),
                               span, query_length, with_strand)
    elif scenario in ("mixed", "stranded"):
        annot = _mixed_table(rng, n_annotations, "a", "feature",
                             with_strand)
        per_chrom = {chrom: int(round(n_annotations * w))
                     for chrom, w in _MIXED_CHROMS}
        span = max(_fit_gap(count) * count for count in per_chrom.values())
        queries = _query_table(
            rng, n_queries, tuple(c for c, _ in _MIXED_CHROMS),
            span, query_length, with_strand)
    else:
        raise ValueError(f"unknown scenario {scenario!r}")
    # Guard: the 32-bit pybedtools CHRPOS limit is a hard input constraint
    # of the Bedtools backend (see _MAX_COORD).
    max_end = max(int(queries["end"].max()), int(annot["end"].max()))
    if max_end >= _MAX_COORD:
        raise AssertionError(
            f"generated coordinate {max_end} exceeds the 32-bit bedtools "
            f"limit {_MAX_COORD}; scenario geometry is misconfigured"
        )
    return queries, annot


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

#: The exact AnnotateR execution path after parsing (SPEC 4.1/4.2):
#: engine call, then the canonical result adapter.
def run_engine_path(engine, coord_df, annot_df, how: str) -> pd.DataFrame:
    raw = engine.intersect(coord_df, annot_df, how=how)
    extra = ("distance",) if engine.mode == "closest" else ()
    return canonicalize_annotation_result(
        raw, coord_df, annot_df, extra_columns=extra
    )


def make_engine(engine_key: str, mode: str, use_strand: bool):
    cls = {"bedtools": BedtoolsEngine, "polars-bio": PolarsBioEngine}[engine_key]
    return cls(use_strand=use_strand, mode=mode)


def measure_engine(engine_key: str, coord_df, annot_df, *, mode, use_strand,
                   how, repetitions, warmup):
    """Warm-up + measured repetitions of the full engine path.

    Returns (wall_times_s, result, row_counts) where result is the last
    measured run's canonical frame.  Row counts across all measured
    repetitions must be identical (determinism, SPEC 4.6); a mismatch is a
    benchmark failure, not a warning.  Any engine exception propagates
    (backend failure is never an empty result, SPEC 9).
    """
    engine = make_engine(engine_key, mode, use_strand)
    times = []
    row_counts = []
    result = None
    for _ in range(warmup + repetitions):
        t0 = time.perf_counter()
        result = run_engine_path(engine, coord_df, annot_df, how)
        times.append(time.perf_counter() - t0)
        row_counts.append(len(result))
    measured = times[warmup:]
    measured_rows = row_counts[warmup:]
    if len(set(measured_rows)) != 1:
        raise AssertionError(
            f"non-deterministic row count for {engine_key}/{mode}: "
            f"{measured_rows}")
    return measured, result, row_counts[-1]


def run_one(size, scenario, operation, how, seed, engines,
            repetitions, warmup):
    """Benchmark one (size, scenario, operation) across the requested
    engines; verify canonical parity before accepting the timings."""
    n_queries, n_annotations = SIZES[size]
    use_strand = scenario == "stranded"
    coord_df, annot_df = generate_scenario(scenario, n_queries, n_annotations,
                                           seed)
    rows = []
    results = {}
    for engine_key in engines:
        times, result, _ = measure_engine(
            engine_key, coord_df, annot_df, mode=operation,
            use_strand=use_strand, how=how,
            repetitions=repetitions, warmup=warmup,
        )
        results[engine_key] = result
        rows.append({
            "size": size,
            "scenario": scenario,
            "operation": operation,
            "how": how,
            "engine": engine_key,
            "n_queries": len(coord_df),
            "n_annotations": len(annot_df),
            "seed": seed,
            "repetitions": repetitions,
            "warmup": warmup,
            "wall_times_s": ";".join(f"{t:.6f}" for t in times),
            "wall_median_s": f"{float(np.median(times)):.6f}",
            "wall_min_s": f"{min(times):.6f}",
            "wall_max_s": f"{max(times):.6f}",
            "wall_iqr_s": f"{float(np.subtract(*np.percentile(times, [75, 25]))):.6f}",
            "result_rows": len(result),
        })
    if len(engines) == 2:
        a, b = engines
        # Parity is verified BEFORE timings are accepted; a mismatch fails
        # the whole benchmark loudly (never a skipped or softened check).
        assert_canonical_equal(results[a], results[b],
                               label=f"{size}/{scenario}/{operation}")
        for row in rows:
            row["parity"] = "verified"
    else:
        for row in rows:
            row["parity"] = "not_applicable_single_engine"
    return rows


def run_memory_probe(size, scenario, operation, how, seed, engine_key):
    """Peak RSS for one engine/scenario in an isolated subprocess.

    ``resource.getrusage`` only exposes the process high-water mark, so an
    in-process per-repetition delta is not possible; the subprocess
    measures the honest peak (interpreter + imports + run).  The wall time
    reported here is for that single run and is NOT part of the timing
    statistics above.
    """
    spec = json.dumps({
        "size": size, "scenario": scenario, "operation": operation,
        "how": how, "seed": seed, "engine": engine_key,
    })
    out = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--_memory-worker", spec],
        capture_output=True, text=True, check=True, cwd=REPO_ROOT,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def _memory_worker(spec: dict) -> None:
    """Subprocess entry point: generate, run once, report wall time +
    peak RSS, print one JSON line."""
    import resource

    size = spec["size"]
    n_queries, n_annotations = SIZES[size]
    coord_df, annot_df = generate_scenario(
        spec["scenario"], n_queries, n_annotations, spec["seed"])
    use_strand = spec["scenario"] == "stranded"
    engine = make_engine(spec["engine"], spec["operation"], use_strand)
    t0 = time.perf_counter()
    result = run_engine_path(engine, coord_df, annot_df, spec["how"])
    wall = time.perf_counter() - t0
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":  # macOS reports bytes
        peak = peak / 1024.0
    else:  # Linux reports KiB
        peak = float(peak)
    print(json.dumps({
        "engine": spec["engine"],
        "size": size,
        "scenario": spec["scenario"],
        "operation": spec["operation"],
        "how": spec["how"],
        "seed": spec["seed"],
        "wall_s": round(wall, 6),
        "peak_rss_kb": round(peak, 1),
        "result_rows": len(result),
    }))


# ---------------------------------------------------------------------------
# Parsing reference (backend-independent, informational only)
# ---------------------------------------------------------------------------

def _to_bed_text(df: pd.DataFrame) -> str:
    """Vectorized BED rendering (BED coordinates are already canonical
    0-based half-open, so no conversion is involved)."""
    cols = ["chr", "start", "end"]
    if "strand" in df.columns:
        cols.append("strand")
    cols += [c for c in df.columns if c not in cols]
    parts = []
    for c in cols:
        values = df[c]
        if values.dtype == object:
            parts.append(values.map(
                lambda v: "." if _isna_safe(v) else str(v)
            ).to_numpy())
        else:
            parts.append(values.astype(str).to_numpy())
    return "\n".join("\t".join(row) for row in zip(*parts)) + "\n"


def _isna_safe(v) -> bool:
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def benchmark_parsing(sizes, seed):
    """Time the shared parser+normalizer (BED text -> canonical table) per
    size.  Parsing is backend-independent (SPEC 4.1) so this is recorded
    once, not per engine, and is never included in backend timings."""
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for size in sizes:
            n_queries, n_annotations = SIZES[size]
            coord_df, annot_df = generate_scenario(
                "sparse", n_queries, n_annotations, seed)
            entries = []
            for label, df in (("queries", coord_df), ("annotations", annot_df)):
                path = Path(tmp) / f"{size}_{label}.bed"
                path.write_text(_to_bed_text(df))
                t0 = time.perf_counter()
                canonical = parse_and_normalize(str(path), fmt="bed")
                wall = time.perf_counter() - t0
                entries.append({
                    "size": size, "input": label, "rows": len(df),
                    "seed": seed,
                    "parse_wall_s": f"{wall:.6f}",
                    "canonical_rows": len(canonical),
                })
            rows.extend(entries)
    return rows


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def environment_metadata() -> dict:
    import pybedtools
    import polars
    import polars_bio

    bedtools = shutil.which("bedtools")
    bedtools_version = None
    if bedtools:
        try:
            proc = subprocess.run([bedtools, "--version"], capture_output=True,
                                  text=True, check=True)
            bedtools_version = proc.stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            bedtools_version = "unavailable"
    commit = None
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                              capture_output=True, text=True, check=True)
        commit = proc.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    return {
        "date_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": commit,
        "host": platform.node(),
        "os": platform.platform(),
        "cpu_arch": platform.machine(),
        "cpu": (
            os.environ.get("CPUTYPE")
            or _try_brand()
            or platform.processor()
        ),
        "python": platform.python_version(),
        "versions": {
            "pybedtools": pybedtools.__version__,
            "polars": polars.__version__,
            "polars-bio": getattr(polars_bio, "__version__", "unknown"),
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "bedtools": bedtools_version,
        },
    }


def _try_brand() -> str:
    try:
        out = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip()
        return out or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="AnnotateR Bedtools vs Polars-Bio backend benchmark "
                    "(see docs/benchmark.md)")
    parser.add_argument("--sizes", nargs="+", choices=sorted(SIZES),
                        default=["small", "medium"],
                        help="size tiers to run (default: small medium)")
    parser.add_argument("--scenarios", nargs="+", choices=list(SCENARIOS),
                        default=list(SCENARIOS),
                        help="scenarios to run (default: all)")
    parser.add_argument("--operations", nargs="+", choices=list(OPERATIONS),
                        default=list(OPERATIONS),
                        help="operations to run (default: all)")
    parser.add_argument("--how", choices=["inner", "left"], default="inner")
    parser.add_argument("--repetitions", type=int, default=5,
                        help="measured repetitions per engine (default 5)")
    parser.add_argument("--warmup", type=int, default=1,
                        help="unmeasured warm-up runs per engine (default 1)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--engines", nargs="+",
                        choices=["bedtools", "polars-bio"],
                        default=["bedtools", "polars-bio"])
    parser.add_argument("--output", default=str(Path(__file__).parent / "results"),
                        help="directory for result files (default: benchmarks/results)")
    parser.add_argument("--measure-memory", action="store_true",
                        help="add isolated subprocess peak-RSS probes per "
                             "engine/scenario/operation (same run as the "
                             "benchmarks)")
    parser.add_argument("--memory-only", action="store_true",
                        help="run only the isolated subprocess peak-RSS "
                             "probes (no benchmark timings)")
    parser.add_argument("--quick", action="store_true",
                        help="CI smoke preset: small/sparse/overlap, 2 reps, "
                             "no warmup, no memory")
    parser.add_argument("--bench-parsing", action="store_true",
                        help="also record the backend-independent "
                             "parser/normalizer timing (reference only)")
    parser.add_argument("--_memory-worker", metavar="SPEC",
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args._memory_worker:
        _memory_worker(json.loads(args._memory_worker))
        return 0

    if args.quick:
        args.sizes = ["small"]
        args.scenarios = ["sparse"]
        args.operations = ["overlap"]
        args.repetitions = 2
        args.warmup = 0
        args.measure_memory = False

    if min(args.repetitions, args.warmup) < 0:
        parser.error("repetitions and warmup must be >= 0")
    if args.repetitions == 0:
        parser.error("repetitions must be >= 1 (a timing benchmark needs a "
                     "measured run)")

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = environment_metadata()
    meta["repetitions"] = args.repetitions
    meta["warmup"] = args.warmup
    meta["how"] = args.how
    meta["engines"] = args.engines
    meta["sizes"] = args.sizes
    meta["scenarios"] = args.scenarios
    meta["operations"] = args.operations
    meta["seed"] = args.seed

    # Timestamped stamp: re-running on the same day must not clobber a
    # previous day's canonical results file.
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    all_rows = []
    t_total = time.perf_counter()
    if args.memory_only:
        for size in args.sizes:
            for scenario in args.scenarios:
                for operation in args.operations:
                    if scenario == "stranded" and operation not in STRANDED_OPERATIONS:
                        continue
                    for engine_key in args.engines:
                        print(f"[mem] {size:6s} / {scenario:10s} / "
                              f"{operation:9s} / {engine_key}", flush=True)
                        probe = run_memory_probe(size, scenario, operation,
                                                 args.how, args.seed,
                                                 engine_key)
                        all_rows.append({
                            **probe, "note": (
                                "isolated subprocess; peak_rss_kb is the "
                                "process high-water mark (interpreter + "
                                "imports + one run); wall_s is a single "
                                "non-statistical run")
                        })
    else:
        for size in args.sizes:
            for scenario in args.scenarios:
                for operation in args.operations:
                    if scenario == "stranded" and operation not in STRANDED_OPERATIONS:
                        continue
                    t0 = time.perf_counter()
                    print(f"[bench] {size:6s} / {scenario:10s} / {operation:9s} ",
                          flush=True)
                    rows = run_one(size, scenario, operation, args.how, args.seed,
                                   args.engines, args.repetitions, args.warmup)
                    all_rows.extend(rows)
                    summary = ", ".join(
                        f"{r['engine']}={r['result_rows']} rows "
                        f"(median {r['wall_median_s']}s)"
                        for r in rows)
                    print(f"    done in {time.perf_counter() - t0:.1f}s ({summary})",
                          flush=True)
                    if args.measure_memory:
                        for engine_key in args.engines:
                            probe = run_memory_probe(size, scenario, operation,
                                                     args.how, args.seed, engine_key)
                            all_rows.append({
                                **probe,
                                "operation": operation,
                                "size": size,
                                "scenario": scenario,
                                "seed": args.seed,
                                "how": args.how,
                                "note": "isolated subprocess peak RSS; wall_s is a "
                                        "single non-statistical run",
                            })

    parse_rows = []
    if not args.memory_only and (args.bench_parsing or args.quick):
        print("[bench] parsing (backend-independent reference)", flush=True)
        parse_rows = benchmark_parsing(args.sizes, args.seed)

    df = pd.DataFrame(all_rows)
    if not df.empty:
        df.insert(0, "generated_utc", meta["date_utc"])
    csv_path = (out_dir / f"benchmark_memory_{stamp}_{args.how}.csv"
                if args.memory_only
                else out_dir / f"benchmark_{stamp}_{args.how}.csv")
    df.to_csv(csv_path, index=False)
    parse_path = None
    if parse_rows:
        p_df = pd.DataFrame(parse_rows)
        p_df.insert(0, "generated_utc", meta["date_utc"])
        parse_path = out_dir / f"benchmark_parsing_{stamp}.csv"
        p_df.to_csv(parse_path, index=False)
    meta_path = out_dir / f"benchmark_{stamp}_{args.how}.json"
    meta["result_csv"] = str(csv_path.name)
    if parse_path is not None:
        meta["parsing_csv"] = str(parse_path.name)
    meta["total_wall_s"] = round(time.perf_counter() - t_total, 1)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")

    with pd.option_context("display.width", 200, "display.max_columns", 30):
        cols = [c for c in (
            "size", "scenario", "operation", "engine", "n_queries",
            "n_annotations", "result_rows", "wall_median_s", "wall_min_s",
            "wall_max_s", "wall_iqr_s", "repetitions", "parity",
            "peak_rss_kb") if c in df.columns]
        print("\n=== benchmark summary ===")
        print(df[cols].to_string(index=False) if not df.empty else "(no rows)")
    if parse_path is not None:
        print("\n=== parsing (backend-independent, reference only) ===")
        print(p_df.to_string(index=False))
    print(f"\nresults: {csv_path}\nmetadata: {meta_path}")
    print("NOTE: timings cover engine.intersect + canonicalization only; "
          "parsing is backend-independent and excluded (see "
          "docs/benchmark.md).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())