# Example 5: Finding the closest feature

The closest example: four VCF variants (query-only format) against three
genes — demonstrating distance 0 (an overlap), a 50-base gap, an
**exact tie**, and an unmatched variant on a chromosome with no
annotations.

## Input

Query: [`data/examples/example_closest_variants.vcf`](https://github.com/pyrevo/annotater/blob/main/data/examples/example_closest_variants.vcf)

```text
#CHROM  POS   ID   REF  ALT  QUAL  FILTER  INFO
chr1    1200  v1   A    T    .     .       .
chr1    1551  v2   C    G    .     .       .
chr1    3751  v3   G    A    .     .       .
chr2    100   v4   T    C    .     .       .
```

Each is a 1-base substitution: canonical interval `[POS − 1, POS)`.

Annotation: [`data/examples/example_closest_annotations.gff3`](https://github.com/pyrevo/annotater/blob/main/data/examples/example_closest_annotations.gff3)
(GFF3 1-based, all strand `+`, chr1 only):

| gene | 0-based interval |
|---|---|
| GENE_A | [999, 1500) |
| GENE_B | [3000, 3500) |
| GENE_C | [4001, 4501) |

## Settings

- Query file: the VCF (accepted by the Query coordinates uploader);
- Operation: **Closest**, **left join**, strand **off**.
- Feature filter: gene (default) — the annotation is GFF3, so the
  filter applies.

## Expected result: 5 rows — 4 matched, 1 unmatched

| variant | canonical interval | attached gene | distance | why |
|---|---|---|---|---|
| v1 | chr1 [1199, 1200) | GENE_A | **0** | inside GENE_A — overlapping intervals have distance 0 |
| v2 | chr1 [1550, 1551) | GENE_A | **50** | 1550 − 1500 = 50 bases gap; GENE_B is 1449 away |
| v3 | chr1 [3750, 3751) | GENE_B | **250** | 3750 − 3500 = 250 … |
| v3 | chr1 [3750, 3751) | GENE_C | **250** | … and 4001 − 3751 = 250 — **an exact tie: both rows are returned**, in annotation input order (B before C) |
| v4 | chr2 [99, 100) | — | (missing) | no annotation on chr2 — unmatched row |

```text
chr1:  GENE_A [───────────────)         [999, 1500)
        v1  [.)  d=0      v2 [.) d=50   [1199,1200) [1550,1551)

        GENE_B [───────────────)       [3000, 3500)
                             v3 [.) d=250 both ways  [3750, 3751)
        GENE_C [───────────────)       [4001, 4501)
```

Things to verify in the table:

- **`has_overlap = True` on v1, v2 and both v3 rows** even though only
  v1 actually overlaps — in closest mode the flag means "an annotation
  was attached"; read the **`distance`** column for the gap
  ([Closest → what the result looks like](../operations/closest.md#what-the-result-looks-like)).
- The two v3 rows are a **tie**, not a duplication: identical
  `distance = 250`, different `annot_*` values, in annotation input
  order.
- The v4 row has missing `annot_*` and missing `distance`
  ([Matched vs unmatched rows](../results/matched-unmatched.md)).
- `coord_ref`/`coord_alt`/`coord_info` show the preserved VCF fields —
  and note the **Annotated VCF** download button, available because the
  query was VCF ([Downloading and exporting results](../results/export.md)).

## Part B (optional) — the strand subtlety

Turn strand matching **on** and re-run. The queries come from a VCF:
VCF carries **no strand**, so every query row has missing strand —
under strand matching, missing is not a wildcard.

**Expected result: 4 rows, 0 matched** — every variant becomes an
unmatched row ([Strand information](../preparing-your-data/strand-information.md)).
This is the standard answer to "my closest run lost all its matches":
strand matching on a VCF query can only produce unmatched rows.

## What this example covered

- the canonical distance formula in all four cases (overlap, gap, tie,
  no candidate);
- touching/overlapping = distance 0;
- ties returned in annotation input order;
- `has_overlap` semantics in closest mode;
- VCF as a query-only input, with metadata preservation;
- the strand rule applied *before* selection.