# Strand information

The **strand** of a genomic interval is the DNA strand it sits on:
`+` (forward/sense) or `-` (reverse/antisense). Strand is metadata that
AnnotateR carries through to the result (`coord_strand`, `annot_strand`
columns when present), and — when you turn on strand matching — it
becomes part of the matching rule itself
([Strand-aware annotation](../operations/strand-aware.md)).

## Where strand comes from, per format

| Format | Strand source | Result |
|---|---|---|
| BED | column 6 | `+`/`-` kept; `.` or empty → **missing** |
| GFF3 | column 7 | `+`/`-` kept; `.` or `?` → **missing**; any other value is rejected with an error |
| GTF | column 7 | `+`/`-` kept; `.` or `?` → **missing**; any other value is rejected with an error |
| VCF | *none* | **always missing** — the VCF format has no strand field |
| Custom table | an unmapped column named exactly `strand` (optional) | `+`/`-` kept; `.` or empty → **missing**; any other value is rejected with an error |

Missing strand is a real, preserved state — it is *not* converted to a
guess and it is *not* dropped.

## The decisive rule (read this before enabling strand matching)

When strand matching is **on**, a query/annotation pair qualifies only
if:

1. both rows carry an **explicit** strand (`+` or `-`), **and**
2. the two strands are **equal**.

Consequences:

- `+` matches `+`; `-` matches `-`.
- `+` vs `-` does **not** match.
- Any row with **missing strand** can never form a stranded match —
  **missing is not a wildcard**, and two missing-strand rows do *not*
  match each other either.

So enabling strand matching can only *remove* qualifying pairs, never
add them. If your annotation file (or VCF query) lacks strand, strand
matching will return nothing — which is correct, not a bug
([Troubleshooting](../troubleshooting.md#zero-matches)).

## What strand does **not** do in v0.1.0

- It does not flip or reverse-complement anything; intervals are
  compared on the forward coordinate axis.
- It does not distinguish sense from antisense at a finer granularity
  than `+`/`-`.
- It has no effect on the coordinate system or on chromosome handling.

## Where to go next

- [Strand-aware annotation](../operations/strand-aware.md) — what the
  checkbox changes in each operation, including the closest-mode
  subtlety.
- [Example 3: Strand-aware annotation](../examples/strand.md) — the
  rule demonstrated on a 3×3 fixture.