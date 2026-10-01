"""
Test-support glue for the independent oracle (Task F / F19).

This module is the ONLY place where the oracle meets production code, and
it does so strictly as a *system under test* driver: it builds canonical
DataFrames from plain-dict fixtures, runs the real engines through the
real canonicalization adapter, and compares the resulting full rows to
the oracle's rows. It contains no relation logic of its own.
"""

from __future__ import annotations

import random

import pandas as pd

from streamlit_app.core import BedtoolsEngine, PolarsBioEngine
from streamlit_app.core.comparison import assert_canonical_equal
from tests.parity.comparator import run_and_canonicalize

from .reference import reference_pairs, reference_rows

ENGINES = {"bedtools": BedtoolsEngine, "polars-bio": PolarsBioEngine}


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

def to_frame(rows):
    """Plain dict rows -> canonical interval DataFrame (None -> pd.NA)."""
    data = {}
    for key in rows[0].keys():
        values = [row[key] for row in rows]
        if key in ("start", "end"):
            data[key] = [int(v) for v in values]
        else:
            data[key] = [pd.NA if v is None else v for v in values]
    return pd.DataFrame(data)


def make_fixture(seed):
    """
    Deterministic tiny random fixture for ``seed`` (``random.Random`` only;
    no clock, no hash-randomized iteration, no filesystem).

    1-8 queries, 1-10 annotations, chromosomes chr1/chr2 (queries may
    also use chr3, which never has annotations), starts in [0, 30),
    lengths in [1, 12], strands '+', '-', missing, and intentionally
    duplicated rows. The strand column is absent on one side in some
    seeds. Metadata (``name`` / ``feature``) identifies each row, except
    that in some seeds duplicates also copy the metadata value.
    """
    rng = random.Random(seed)
    n_query = rng.randint(1, 8)
    n_annot = rng.randint(1, 10)
    query_has_strand = rng.random() < 0.85
    annot_has_strand = rng.random() < 0.85
    dup_metadata = rng.random() < 0.5

    def table(n, chroms, has_strand, label):
        rows = []
        for i in range(n):
            if rows and rng.random() < 0.2:
                source = rng.choice(rows)  # intentional duplicate-valued row
                row = dict(source)
                if not dup_metadata:
                    row[label] = f"{label[0]}{i}"
            else:
                start = rng.randint(0, 29)
                row = {
                    "chr": rng.choice(chroms),
                    "start": start,
                    "end": start + rng.randint(1, 12),
                }
                if has_strand:
                    row["strand"] = rng.choice(["+", "-", None, "+", "-"])
                row[label] = f"{label[0]}{i}"
            rows.append(row)
        return rows

    queries = table(n_query, ["chr1", "chr1", "chr2", "chr3"], query_has_strand, "name")
    annotations = table(n_annot, ["chr1", "chr1", "chr2"], annot_has_strand, "feature")
    return queries, annotations


# --------------------------------------------------------------------------
# Comparison against the oracle
# --------------------------------------------------------------------------

def _plain(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return value.item()
    return value


def result_rows(result: pd.DataFrame):
    """Canonical result frame -> list of plain-Python row dicts."""
    return [
        {col: _plain(value) for col, value in record.items()}
        for record in result.astype(object).to_dict("records")
    ]


def describe(queries, annotations, config):
    return f"config={config}\n  queries={queries}\n  annotations={annotations}"


def diff_rows(expected, actual):
    """Return a human-readable difference, or None if rows match strictly."""
    if len(expected) != len(actual):
        return f"row count: oracle={len(expected)} backend={len(actual)}"
    for i, (e, a) in enumerate(zip(expected, actual)):
        if list(e.keys()) != list(a.keys()):
            return f"row {i} columns: oracle={list(e)} backend={list(a)}"
        for key in e:
            if e[key] != a[key] or type(e[key]) is not type(a[key]):
                return (f"row {i} column {key!r}: oracle={e[key]!r} "
                        f"({type(e[key]).__name__}) backend={a[key]!r} "
                        f"({type(a[key]).__name__})")
    return None


def run_canonical(engine_cls, queries, annotations, config, frames=None):
    """Run one engine; ``frames`` = (coord_df, annot_df) overrides the
    DataFrames built from the plain-dict rows (parser-integration tests
    pass the real parsed frames)."""
    mode = config["mode"]
    coord_df, annot_df = frames or (to_frame(queries), to_frame(annotations))
    return run_and_canonicalize(
        engine_cls, coord_df, annot_df,
        how=config["how"],
        extra_columns=("distance",) if mode == "closest" else (),
        mode=mode,
        use_strand=config["use_strand"],
        min_overlap=config.get("min_overlap"),
    )


def oracle_rows_for(queries, annotations, config, oracle=reference_pairs):
    pairs = oracle(
        queries, annotations, how=config["how"], mode=config["mode"],
        use_strand=config["use_strand"], min_overlap=config.get("min_overlap"),
    )
    return reference_rows(queries, annotations, pairs,
                          closest=config["mode"] == "closest")


def frame_rows(df: pd.DataFrame):
    """Interval DataFrame -> plain dict rows for the oracle."""
    return [
        {col: _plain(value) for col, value in record.items()}
        for record in df.astype(object).to_dict("records")
    ]


def check_fixture(queries, annotations, config, *, tag="",
                  oracle=reference_pairs, engines=ENGINES, frames=None):
    """
    Run every backend on one fixture and compare each to the oracle and to
    each other. Returns a list of failure descriptions (empty = pass); each
    names the tag (seed), the backend and the full fixture.
    """
    problems = []
    expected = oracle_rows_for(queries, annotations, config, oracle=oracle)
    canonical = {}
    for name, engine_cls in engines.items():
        try:
            result = run_canonical(engine_cls, queries, annotations, config,
                                    frames=frames)
        except Exception as exc:  # a backend failure is a failure, never "empty"
            problems.append(
                f"[{tag}] {name} raised {type(exc).__name__}: {exc}\n"
                + describe(queries, annotations, config))
            continue
        canonical[name] = result
        difference = diff_rows(expected, result_rows(result))
        if difference:
            problems.append(
                f"[{tag}] {name} != oracle: {difference}\n"
                + describe(queries, annotations, config)
                + f"\n  oracle_rows={expected}")
    if len(canonical) == 2:
        first, second = list(canonical)
        try:
            assert_canonical_equal(
                canonical[first], canonical[second],
                label=f"[{tag}] backend parity")
        except AssertionError as exc:
            problems.append(
                f"[{tag}] backends disagree: {exc}\n"
                + describe(queries, annotations, config))
    return problems
