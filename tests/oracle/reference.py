"""
Independent brute-force reference ("oracle") for the AnnotateR canonical
interval contract (SPEC.md sections 7-8; docs/engine-contract.md).

Independence rules (Task F / audit finding F19):

- This module imports NOTHING from ``streamlit_app`` and nothing that
  implements interval logic (no pandas, polars, pybedtools, numpy, no
  interval trees, no vectorized math). It is plain Python over plain
  lists of dicts, with explicit nested loops and literal comparisons.
- Every formula is written out once, below, exactly as the contract
  states it, so a reviewer can verify it by hand.
- It is deliberately slow and obvious. Do not optimize it.

Inputs are already-canonical intervals: 0-based, half-open ``[start, end)``.
Each interval is a dict with ``chr``, ``start``, ``end`` and optionally
``strand`` (any value other than the strings ``"+"``/``"-"`` — including
``None`` or an absent key — is "missing").

``reference_pairs`` returns the expected canonical rows as
``(query_index, annotation_index_or_None, distance_or_None)`` tuples in
the contract order: query input order, then annotation input order among
that query's matches; an unmatched query (left mode) appears once at its
own query position with ``None`` annotation. ``distance`` is only
non-``None`` in closest mode.
"""

# --------------------------------------------------------------------------
# Contract formulas (module-level so the false-confidence guard can swap
# in deliberately wrong versions; see tests/oracle/test_false_confidence.py)
# --------------------------------------------------------------------------


def overlap_length(q_start, q_end, a_start, a_end):
    """Bases shared by the two intervals (may be <= 0 when disjoint)."""
    return min(q_end, a_end) - max(q_start, a_start)


def overlaps(q_start, q_end, a_start, a_end):
    """Ordinary overlap: positive-width intersection. Touching is NOT overlap."""
    return overlap_length(q_start, q_end, a_start, a_end) > 0


def meets_min_overlap(q_start, q_end, a_start, a_end, threshold):
    """overlap_length / query_length >= threshold, with positive overlap."""
    length = overlap_length(q_start, q_end, a_start, a_end)
    if length <= 0:
        return False
    query_length = q_end - q_start
    return length / query_length >= threshold


def query_contains_annotation(q_start, q_end, a_start, a_end):
    return q_start <= a_start and q_end >= a_end


def query_within_annotation(q_start, q_end, a_start, a_end):
    return a_start <= q_start and a_end >= q_end


def gap_distance(q_start, q_end, a_start, a_end):
    """max(0, a_start - q_end, q_start - a_end): bases in the gap."""
    return max(0, a_start - q_end, q_start - a_end)


def strands_match(q_strand, a_strand):
    """Both explicit ('+' or '-') and equal. Missing is never a wildcard."""
    if q_strand not in ("+", "-"):
        return False
    if a_strand not in ("+", "-"):
        return False
    return q_strand == a_strand


# --------------------------------------------------------------------------
# Brute-force join
# --------------------------------------------------------------------------


def _strand_ok(query, annotation, use_strand):
    if not use_strand:
        return True
    return strands_match(query.get("strand"), annotation.get("strand"))


def _relation_holds(query, annotation, mode, min_overlap):
    q_start, q_end = query["start"], query["end"]
    a_start, a_end = annotation["start"], annotation["end"]
    if mode == "overlap":
        if not overlaps(q_start, q_end, a_start, a_end):
            return False
        if min_overlap is not None:
            return meets_min_overlap(q_start, q_end, a_start, a_end, min_overlap)
        return True
    if mode == "contains":
        # A contained annotation necessarily overlaps (intervals have
        # positive width), so no separate overlap test is needed.
        return query_contains_annotation(q_start, q_end, a_start, a_end)
    if mode == "within":
        return query_within_annotation(q_start, q_end, a_start, a_end)
    raise ValueError(f"unsupported mode {mode!r}")


def reference_pairs(queries, annotations, *, how="inner", mode="overlap",
                    use_strand=False, min_overlap=None):
    """Expected ``(qi, ai_or_None, distance_or_None)`` rows, contract order."""
    if how not in ("inner", "left"):
        raise ValueError(f"unsupported how {how!r}")
    rows = []
    for qi, query in enumerate(queries):
        matches = []  # (annotation index, distance or None)

        if mode == "closest":
            # Eligible candidates: same chromosome, strand rule applied
            # BEFORE choosing the nearest.
            eligible = []
            for ai, annotation in enumerate(annotations):
                if annotation["chr"] != query["chr"]:
                    continue
                if not _strand_ok(query, annotation, use_strand):
                    continue
                d = gap_distance(query["start"], query["end"],
                                 annotation["start"], annotation["end"])
                eligible.append((ai, d))
            if eligible:
                best = eligible[0][1]
                for _, d in eligible:
                    if d < best:
                        best = d
                # ALL ties, in annotation input order.
                matches = [(ai, d) for ai, d in eligible if d == best]
        else:
            for ai, annotation in enumerate(annotations):
                if annotation["chr"] != query["chr"]:
                    continue
                if not _strand_ok(query, annotation, use_strand):
                    continue
                if _relation_holds(query, annotation, mode, min_overlap):
                    matches.append((ai, None))

        if matches:
            for ai, d in matches:
                rows.append((qi, ai, d))
        elif how == "left":
            rows.append((qi, None, None))
    return rows


# --------------------------------------------------------------------------
# Canonical row materialization (plain Python)
# --------------------------------------------------------------------------

_INTERVAL_KEYS = ("chr", "start", "end")


def reference_rows(queries, annotations, pairs, *, closest=False):
    """
    Materialize oracle pairs as full canonical result rows (dicts keyed
    like the public result: ``coord_*``, ``annot_*``, ``has_overlap`` and,
    in closest mode, ``distance``). Missing values are ``None``.

    Every key of an input dict other than ``chr``/``start``/``end`` is
    metadata and is carried through under the same prefix (``strand`` is
    ordinary metadata for this purpose). ``annotation_keys`` /
    ``query_keys`` come from the first row of each table; tables here are
    rectangular.
    """
    q_keys = list(queries[0].keys()) if queries else list(_INTERVAL_KEYS)
    a_keys = list(annotations[0].keys()) if annotations else list(_INTERVAL_KEYS)
    out = []
    for qi, ai, distance in pairs:
        row = {}
        for key in q_keys:
            row["coord_" + key] = queries[qi][key]
        for key in a_keys:
            row["annot_" + key] = None if ai is None else annotations[ai][key]
        row["has_overlap"] = ai is not None
        if closest:
            row["distance"] = distance
        out.append(row)
    return out
