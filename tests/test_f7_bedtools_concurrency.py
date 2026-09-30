"""
Task B / F7 regression: Bedtools backend concurrency safety.

BedtoolsEngine uses pybedtools, whose temp-file lifecycle is managed in
a single PROCESS-GLOBAL temp area: each intersect writes its temp BED
files there and the ``finally`` clause calls ``pybedtools.cleanup()``,
which deletes the shared temp area for the WHOLE process. Without a
lock, two threads running intersects at the same time interfere:
thread B's ``cleanup()`` deletes thread A's live temp files while
thread A's bedtools subprocess is still using them, corrupting or
failing an in-flight operation.

The fix serializes exactly the temp-file-lifecycle span (temp file
creation, bedtools subprocess, ``pybedtools.cleanup()``) with a
module-level ``threading.Lock``; result adaptation and post-filtering
run outside the lock.

This test runs several threads through REAL intersect calls (the
bedtools binary must be installed) and asserts that:

1. no exception escapes any concurrent run, and
2. every concurrent result is identical to the single-thread
   reference result (same rows, same canonical order).

The Polars-Bio engine is deliberately not exercised here: it is a
pure in-memory operation with no temp files and no process-global
state, so it needs no lock.
"""

from __future__ import annotations

import shutil
import threading

import numpy as np
import pandas as pd
import pytest

pybedtools = pytest.importorskip("pybedtools")
pytestmark = pytest.mark.skipif(
    shutil.which("bedtools") is None, reason="bedtools binary not installed"
)

from streamlit_app.core.annotator import BedtoolsEngine  # noqa: E402


def _canonical_frames(n_query: int, n_annot: int, seed: int = 7):
    rng = np.random.default_rng(seed)
    q_chrs = rng.choice(["chr1", "chr2", "chrX"], size=n_query)
    q_starts = np.sort(rng.integers(0, 1_000_000, size=n_query))
    q_ends = q_starts + rng.integers(1, 500, size=n_query)
    a_chrs = rng.choice(["chr1", "chr2", "chrX"], size=n_annot)
    a_starts = np.sort(rng.integers(0, 1_000_000, size=n_annot))
    a_ends = a_starts + rng.integers(1, 500, size=n_annot)
    coord_df = pd.DataFrame({
        "chr": q_chrs.astype(str),
        "start": q_starts.astype("int64"),
        "end": q_ends.astype("int64"),
        "gene": [f"q{i}" for i in range(n_query)],
    })
    annot_df = pd.DataFrame({
        "chr": a_chrs.astype(str),
        "start": a_starts.astype("int64"),
        "end": a_ends.astype("int64"),
        "gene": [f"a{i}" for i in range(n_annot)],
    })
    return coord_df, annot_df


_COMBOS = (("overlap", "inner"), ("overlap", "left"), ("contains", "left"))
N_THREADS = 4
N_ITERS = 4


def test_concurrent_bedtools_intersects_are_safe_and_deterministic():
    coord_df, annot_df = _canonical_frames(20_000, 30_000)

    # Single-thread reference results.
    reference = {}
    for mode, how in _COMBOS:
        engine = BedtoolsEngine(mode=mode)
        reference[(mode, how)] = engine.intersect(
            coord_df, annot_df, how=how
        ).reset_index(drop=True)

    errors: list[BaseException] = []
    mismatches: list[str] = []
    lock = threading.Lock()

    def worker():
        for iteration in range(N_ITERS):
            for mode, how in _COMBOS:
                engine = BedtoolsEngine(mode=mode)
                try:
                    result = engine.intersect(
                        coord_df, annot_df, how=how
                    ).reset_index(drop=True)
                except BaseException as exc:  # noqa: BLE001 - report it
                    with lock:
                        errors.append(exc)
                    continue
                expected = reference[(mode, how)]
                if not result.equals(expected):
                    with lock:
                        mismatches.append(
                            f"iter={iteration} mode={mode} how={how}: "
                            f"got {len(result)} rows, expected {len(expected)}"
                        )

    threads = [
        threading.Thread(target=worker, name=f"bt-{i}") for i in range(N_THREADS)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, (
        f"{len(errors)} concurrent bedtools run(s) raised an exception; "
        f"first: {errors[0]!r}"
    )
    assert not mismatches, "; ".join(mismatches[:5])