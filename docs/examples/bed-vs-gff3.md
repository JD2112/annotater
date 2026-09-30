# Example 1: BED query against GFF3 annotations

The canonical first run. It uses the two example files bundled in the
repository, the default operation (Overlap), and the default left join.
Run this first to see how matched and unmatched rows look.

## Input

Query: [`data/examples/example_coordinates.bed`](https://github.com/JD2112/annotater/blob/main/data/examples/example_coordinates.bed)
— 6 regions (BED, 0-based half-open):

```text
chr1    100000    100500    region1    100    +
chr1    200000    200300    region2    200    +
chr2    150000    151000    region3    150    -
chr2    300000    300200    region4    180    +
chrX    50000     52000     regionX    250    +
chrY    75000     75500     regionY    120    +
```

Annotation: [`data/examples/example_annotations.gff3`](https://github.com/JD2112/annotater/blob/main/data/examples/example_annotations.gff3)
— 3 genes plus 5 exons on chr1/chr2/chrX (GFF3, 1-based inclusive).

## Settings (all defaults)

- Engine: **Bedtools** (or Polars-Bio — results are identical)
- Operation: **Overlap**
- Join: **Keep all query rows (left join)**
- Feature filter: **gene** (the default — exons are excluded in Part A)
- Strand: off, min_overlap: 0

## Part A — default settings (gene filter)

Run the annotation. **Expected result: 6 result rows — 3 matched, 3
unmatched.**

| coord_name | coord_chr | coord (0-based) | matched? | annot (gene, canonical 0-based, half-open end) |
|---|---|---|---|---|
| region1 | chr1 | 100000–100500 | ✓ | GENE1, chr1 49999–150000 |
| region2 | chr1 | 200000–200300 | ✗ | — |
| region3 | chr2 | 150000–151000 | ✓ | GENE2, chr2 99999–200000 |
| region4 | chr2 | 300000–300200 | ✗ | — |
| regionX | chrX | 50000–52000 | ✓ | GENEX, chrX 39999–60000 |
| regionY | chrY | 75000–75500 | ✗ | — |

Notes to verify in the table:

- The `annot_start`/`annot_end` values are **canonical 0-based**:
  GENE1's GFF3 `50000 150000` appears as `49999`–`150000`
  ([Coordinate systems](../preparing-your-data/coordinate-systems.md)).
- Unmatched rows (region2, region4, regionY) have all `annot_*`
  columns blank and `has_overlap = False`.
- Switch the Show filter to **Matched only** → "Showing 3 of 6 rows".

## Part B — add exons to the filter

In the sidebar, **Filter by feature type**: select **gene** *and*
**exon**, then **Run annotation** again.

**Expected result: 9 result rows — 6 matched, 3 unmatched.** Each of
the three matched queries now matches **two** annotations — its gene
and the one exon overlapping it:

| query | matches |
|---|---|
| region1 | GENE1 **and** exon ENSE001 — 2 rows |
| region3 | GENE2 **and** exon ENSE003 — 2 rows |
| regionX | GENEX **and** exon ENSE005 — 2 rows |
| region2 / region4 / regionY | unmatched — 1 row each |

The other exons (ENSE002, ENSE004) do not overlap any query region, so
they do not appear — the feature filter changes *which annotations
exist* for matching; the interval rule still decides what qualifies.
This part demonstrates the two most important row-count rules at once:
*one query with N matching annotations produces N rows*, and *the
feature filter acts at parse time, before matching*
([Feature filtering](../using/feature-filtering.md)).

## Part C (optional) — inner join

Re-run Part A with **Matched rows only (inner join)**: **3 rows**
(matched pairs only). The unmatched regions disappear entirely
([Join behavior: left vs inner](../operations/join-behavior.md)).

## What this example covered

- both uploader roles (BED as query, GFF3 as annotation);
- format-specific normalization visible in `annot_*` columns;
- left-join unmatched rows;
- feature filtering changing the result;
- inner vs left row counts.

Next: [Example 2: Minimum-overlap filtering](min-overlap.md).