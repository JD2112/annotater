# Strand-aware annotation

The sidebar toggle **"Strand-aware annotation (same-strand matching)"**
changes *eligibility* for every operation; it never changes the
coordinate or interval rules.

## Off: strand is carried, not checked

When strand matching is off, strand is ignored by the interval
operation. Strands are still **preserved** as metadata in the result
(`coord_strand`, `annot_strand` when your files carry them) — see
[Strand information](../preparing-your-data/strand-information.md).

## On: the matching rule

A query/annotation pair is eligible only if:

1. **both** rows carry an explicit strand (`+` or `-`), **and**
2. the strands are **equal**.

Consequences:

- `+` vs `+` ✓, `-` vs `-` ✓, `+` vs `-` ✗
- **missing vs missing ✗** — missing strand is not a wildcard; two
  rows that both lack strand do *not* match under strand matching
- missing vs explicit ✗

Strand matching can only **remove** qualifying pairs, never add them.

```text
query Q: [──) strand +      annotation A: [──) strand -      ✗ opposite
query Q: [──) strand +      annotation A: [──) strand +      ✓ same
query Q: [──) strand .      annotation A: [──) strand +      ✗ missing
query Q: [──) strand .      annotation A: [──) strand .      ✗ missing (not a wildcard)
```

## Per-operation composition

The strand rule is an **AND** with the interval rule, uniformly:

| Operation | Qualifies under strand matching when… |
|---|---|
| overlap | intervals overlap **and** strands are explicit and equal |
| overlap + min_overlap | the coverage threshold is met **and** the strand rule holds |
| contains | containment holds **and** the strand rule holds |
| within | within-holds **and** the strand rule holds |
| closest | the strand rule is applied **before selection** (see below) |

## Closest: before selection, with the two consequences

For closest, strand filtering happens **before** the nearest search:

- an **opposite-strand** annotation can never be selected;
- a **nearer opposite-strand annotation cannot suppress a farther
  same-strand one** — the far same-strand annotation is returned even
  though a closer (wrong-strand) one exists;
- a **missing-strand** query (including every row of a VCF query) can
  never form a stranded match at all — closest of a VCF query with
  strand matching on returns only unmatched rows.

## Interaction with other options

- **Feature filtering** (GFF/GTF) is applied when the run starts,
  before the operation; strand matching sees only the surviving features.
- **Chromosome handling** and **coordinate systems** are independent:
  conversion happens first, strand is compared after, verbatim (`+`
  and `-` only — nothing is normalized or case-folded).
- **Join behavior** is downstream: pairs removed by strand matching
  simply do not exist to be joined; queries left without any eligible
  pair become unmatched rows in left mode.

## Where to go next

- [Example 3: Strand-aware annotation](../examples/strand.md) — the
  rule on a 3×3 fixture, including the missing-strand cases.
- [Troubleshooting → zero matches](../troubleshooting.md#zero-matches) —
  the most common strand-related surprise.