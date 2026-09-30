# Example 3: Strand-aware annotation

A 3 × 3 fixture that isolates the strand rule: three query intervals
that each overlap exactly one gene, with the three genes carrying
strand `+`, `+`, and *missing* — and the queries carrying `+`, `-`,
`+`.

## Input

Query: [`data/examples/example_strand_coordinates.bed`](https://github.com/JD2112/annotater/blob/main/data/examples/example_strand_coordinates.bed)

```text
chr1    0     100    q_plus     0    +
chr1    200   300    q_minus    0    -
chr1    400   500    q_plus2    0    +
```

Annotation: [`data/examples/example_strand_annotations.gff3`](https://github.com/JD2112/annotater/blob/main/data/examples/example_strand_annotations.gff3)
(GFF3 1-based; the third gene's strand column is `.`):

| gene | 0-based interval | strand |
|---|---|---|
| gene_same (G1) | [0, 100) | `+` |
| gene_opp (G2) | [200, 300) | `+` |
| gene_miss (G3) | [400, 500) | **missing** |

The three overlapping pairs, and the strand rule applied to each:

| Pair | Overlaps? | Query strand | Gene strand | Stranded match? |
|---|---|---|---|---|
| q_plus / gene_same | yes | `+` | `+` | **yes** — explicit, equal |
| q_minus / gene_opp | yes | `-` | `+` | **no** — opposite |
| q_plus2 / gene_miss | yes | `+` | missing | **no** — missing is not a wildcard |

## Part A — strand off (default)

Settings: **Overlap**, **left join**, strand checkbox **unchecked**.

**Expected result: 3 rows, 3 matched.** Strand is carried in the table
(`coord_strand`, `annot_strand`) but not checked — q_minus matches
gene_opp despite opposite strands, and q_plus2 matches gene_miss.

## Part B — strand on

Check **Require query and annotation to have the same explicit strand**
(the Advanced group label becomes "Advanced options (strand
required)"), then **Run annotation**.

**Expected result: 3 rows — 1 matched, 2 unmatched.**

| query | row type | why |
|---|---|---|
| q_plus | matched (gene_same) | `+` / `+` |
| q_minus | unmatched | opposite strands (`-` vs `+`) |
| q_plus2 | unmatched | gene strand is missing — no stranded match possible |

Nothing is dropped silently: both excluded pairs remain in the table
as real unmatched rows with `has_overlap = False`, and the metrics show
Matched = 1, Unmatched = 2.

## What this example covered

- strand is checked, not converted — the rule is explicit-and-equal;
- opposite strands do not match;
- **missing strand is not a wildcard** (the most common strand
  surprise — also why a VCF query can never match with strand on);
- strand matching only *removes* pairs; left join keeps the rest
  visible as unmatched rows.

Next: [Example 4: contains vs within](contains-within.md).