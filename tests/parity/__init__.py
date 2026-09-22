"""
Systematic Bedtools <-> Polars-Bio parity harness (PLAN Task 3).

The harness defines an executable differential contract for the two
annotation engines. For identical canonical query/annotation tables it
determines, per case, whether each engine satisfies the AnnotateR
semantic contract (SPEC.md) and whether the two engines agree after
canonical result normalization.

Oracle strategy (three layers of evidence):

1. **Explicit expected fixtures** derived from SPEC.md and
   ``docs/engine-contract.md`` — the primary semantic oracle. Each case
   encodes its expected rows directly from genomic interval semantics
   (0-based half-open ``[start, end)``, ``max(starts) < min(ends)``),
   never from whichever backend currently produces them.
2. **Per-engine contract tests** — each engine is independently
   compared against the same expected fixtures.
3. **Differential comparison** — Bedtools canonical result vs
   Polars-Bio canonical result, in addition to (2), so that a regression
   in *either* engine is visible even when both share a bug.

Parity means semantic equivalence *after* canonical result
normalization (``canonicalize_annotation_result``). It does NOT mean
identical raw backend columns, row order before adaptation, or internal
representation.

Known current deviations are captured as ``xfail(strict=True)`` tests
whose reasons name the exact root cause; a strict XPASS fails CI until
the marker is reviewed. See ``docs/implementation-notes.md`` (Task 3
deviation inventory).
"""