"""
F-NEW-01 regression: Polars-Bio backend concurrency safety.

polars-bio 0.35.1 routes DataFrame range operations through ONE
process-global DataFusion session context and registers the two inputs
under the fixed table names ``s1`` / ``s2``. Two interleaved
``pb.overlap`` calls (e.g. two Streamlit sessions) therefore overwrite or
deregister each other's tables, which silently returns another session's
rows or raises (including PyO3 panics, i.e. ``BaseException``).

The fix serializes the complete ``pb.overlap`` call with a module-level
lock (``_POLARS_BIO_LOCK``) that is independent of the Bedtools lock.

These tests assert, with disjoint per-thread inputs (``alice_*`` /
``bob_*`` / ...):

1. no concurrent call raises (``BaseException`` included);
2. every concurrent result is strictly identical (rows, multiplicity,
   order, dtypes) to that thread's own single-thread reference;
3. no cell of a result carries another thread's metadata;
4. the unsafe section is never entered by two threads at once;
5. the Polars-Bio and Bedtools locks are distinct objects.

The stress test cannot assert that the race occurs without the lock (it
is probabilistic); it is sized so that removing the lock fails it with
very high probability while it is deterministic with the lock.
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("polars_bio")

from streamlit_app.core import annotator  # noqa: E402
from streamlit_app.core.annotator import PolarsBioEngine  # noqa: E402

OWNERS = ("alice", "bob", "carol", "dave")
N_ITERS = 12
N_QUERY = 3_000
N_ANNOT = 4_000
COMBOS = (
    ("overlap", "inner"),
    ("overlap", "left"),
    ("contains", "inner"),
    ("contains", "left"),
    ("within", "inner"),
    ("within", "left"),
)


def _frames(owner: str, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Disjoint-per-owner canonical frames (own chromosomes + metadata)."""
    rng = np.random.default_rng(seed)
    chroms = [f"{owner}_chr{i}" for i in (1, 2)]

    def build(n: int, kind: str, max_len: int) -> pd.DataFrame:
        starts = np.sort(rng.integers(0, 200_000, size=n))
        ends = starts + rng.integers(1, max_len, size=n)
        return pd.DataFrame({
            "chr": rng.choice(chroms, size=n).astype(str),
            "start": starts.astype("int64"),
            "end": ends.astype("int64"),
            "gene": [f"{owner}_{kind}{i}" for i in range(n)],
        })

    # Annotations are longer than queries so contains/within both match.
    return build(N_QUERY, "q", 400), build(N_ANNOT, "a", 3_000)


def _run(owner: str, coord, annot, mode: str, how: str) -> pd.DataFrame:
    return PolarsBioEngine(mode=mode).intersect(
        coord, annot, how=how
    ).reset_index(drop=True)


def _foreign_cells(result: pd.DataFrame, owner: str) -> list[str]:
    bad = []
    for col in result.columns:
        if not (
            pd.api.types.is_object_dtype(result[col])
            or pd.api.types.is_string_dtype(result[col])
        ):
            continue
        for v in result[col].dropna().unique():
            if isinstance(v, str) and ("_" in v) and not v.startswith(owner):
                bad.append(f"{col}={v!r}")
    return bad


def test_concurrent_polars_bio_sessions_do_not_contaminate_each_other():
    data = {o: _frames(o, seed=100 + i) for i, o in enumerate(OWNERS)}

    # Single-thread reference per (owner, mode, how).
    reference = {}
    for owner, (coord, annot) in data.items():
        for mode, how in COMBOS:
            ref = _run(owner, coord, annot, mode, how)
            assert len(ref) > 0, f"degenerate fixture: {owner} {mode} {how}"
            reference[(owner, mode, how)] = ref

    failures: list[str] = []
    guard = threading.Lock()
    start_gate = threading.Barrier(len(OWNERS))

    def worker(owner: str) -> None:
        coord, annot = data[owner]
        start_gate.wait()
        for iteration in range(N_ITERS):
            for mode, how in COMBOS:
                tag = f"{owner} iter={iteration} {mode}/{how}"
                try:
                    result = _run(owner, coord, annot, mode, how)
                except BaseException as exc:  # noqa: BLE001 - PyO3 panics
                    with guard:
                        failures.append(f"{tag}: raised {exc!r}")
                    continue
                foreign = _foreign_cells(result, owner)
                if foreign:
                    with guard:
                        failures.append(f"{tag}: foreign metadata {foreign[:3]}")
                elif not result.equals(reference[(owner, mode, how)]):
                    with guard:
                        failures.append(
                            f"{tag}: {len(result)} rows != "
                            f"{len(reference[(owner, mode, how)])} reference"
                        )

    threads = [
        threading.Thread(target=worker, args=(o,), name=f"pb-{o}") for o in OWNERS
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not failures, f"{len(failures)} failure(s); first: {failures[:5]}"


def test_polars_bio_overlap_calls_are_mutually_exclusive(monkeypatch):
    """Deterministic: two threads are never inside ``pb.overlap`` together."""
    import polars_bio as pb

    real = pb.overlap
    state = {"active": 0, "max": 0, "calls": 0}
    guard = threading.Lock()

    def probe(*args, **kwargs):
        with guard:
            state["active"] += 1
            state["calls"] += 1
            state["max"] = max(state["max"], state["active"])
        try:
            time.sleep(0.02)  # widen the window for any overlap
            return real(*args, **kwargs)
        finally:
            with guard:
                state["active"] -= 1

    monkeypatch.setattr(pb, "overlap", probe)

    coord = pd.DataFrame(
        {"chr": ["chr1"], "start": [10], "end": [20], "gene": ["q"]}
    )
    annot = pd.DataFrame(
        {"chr": ["chr1"], "start": [15], "end": [30], "gene": ["a"]}
    )
    errors: list[BaseException] = []

    def worker(mode: str) -> None:
        try:
            for _ in range(5):
                PolarsBioEngine(mode=mode).intersect(coord, annot, how="inner")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(m,))
        for m in ("overlap", "contains", "within", "overlap")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert state["calls"] == 20
    assert state["max"] == 1


def test_polars_bio_and_bedtools_locks_are_independent():
    assert annotator._POLARS_BIO_LOCK is not annotator._BEDTOOLS_TEMP_LOCK


def test_closest_does_not_take_the_polars_bio_lock():
    """closest is backend-independent (no pb call), so it needs no lock."""
    coord = pd.DataFrame(
        {"chr": ["chr1"], "start": [10], "end": [20], "gene": ["q"]}
    )
    annot = pd.DataFrame(
        {"chr": ["chr1"], "start": [50], "end": [60], "gene": ["a"]}
    )
    with annotator._POLARS_BIO_LOCK:
        out: list[pd.DataFrame] = []
        t = threading.Thread(
            target=lambda: out.append(
                PolarsBioEngine(mode="closest").intersect(coord, annot)
            )
        )
        t.start()
        t.join(timeout=30)
        assert not t.is_alive(), "closest blocked on the Polars-Bio lock"
    assert len(out) == 1 and len(out[0]) == 1
