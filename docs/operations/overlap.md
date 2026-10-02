# Overlap

## Definition

Two intervals on the **same chromosome** overlap if their intersection
contains at least one base. In canonical 0-based half-open form, query
`[q_start, q_end)` and annotation `[a_start, a_end)` overlap if and
only if:

```text
max(q_start, a_start) < min(q_end, a_end)
```

Equivalently: the overlap length `min(q_end, a_end) − max(q_start, a_start)`
is **positive**. Overlap is the default AnnotateR operation and the
basis for all the others
([Choosing an operation](choosing-an-operation.md)).

## The one-base case

<!-- BEGIN GENERATED: one_base_overlap -->
```text
chromosome chr1; 0-based half-open coordinates
cells are genomic bases: # = included base, . = outside interval

bases        10 11 12 13 14 15 16 17 18 19
query         #  #  #  #  #  #  #  #  #  #  [10, 20)
annotation    .  .  .  .  .  .  .  .  .  #  [19, 20)

query       bases 10–19 (10 bases); boundary coordinates 10 and 20
annotation  base 19 (1 base); boundary coordinates 19 and 20

overlap: yes
overlap length: 1
query length: 10
overlap fraction (query-relative): 0.1
```
<!-- END GENERATED: one_base_overlap -->

The shared bases are base 19 — a **1-base overlap is a real overlap**.
Any positive intersection counts; there is no minimum length in plain
overlap mode (that is what `min_overlap` adds; see below).

## Overlap (interval intersection)

<!-- BEGIN GENERATED: true_overlap -->
```text
chromosome chr1; 0-based half-open coordinates
cells are genomic bases: # = included base, . = outside interval

bases        10 11 12 13 14 15 16 17 18 19 20 21
query         #  #  #  #  #  #  #  #  .  .  .  .  [10, 18)
annotation    .  .  .  #  #  #  #  #  #  #  #  #  [13, 22)

query       bases 10–17 (8 bases); boundary coordinates 10 and 18
annotation  bases 13–21 (9 bases); boundary coordinates 13 and 22

overlap: yes
overlap length: 5
query length: 8
overlap fraction (query-relative): 0.625
```
<!-- END GENERATED: true_overlap -->

## Touching is NOT overlap

<!-- BEGIN GENERATED: touching_intervals -->
```text
chromosome chr1; 0-based half-open coordinates
cells are genomic bases: # = included base, . = outside interval

bases        10 11 12 13 14 15 16 17 18 19 20 21 22 23 24
query         #  #  #  #  #  #  #  #  #  #  .  .  .  .  .  [10, 20)
annotation    .  .  .  .  .  .  .  .  .  .  #  #  #  #  #  [20, 25)

query       bases 10–19 (10 bases); boundary coordinates 10 and 20
annotation  bases 20–24 (5 bases); boundary coordinates 20 and 25

overlap: no
overlap length: 0
closest distance: 0
```
<!-- END GENERATED: touching_intervals -->

`[10, 20)` covers bases 10–19; `[20, 25)` covers bases 20–24. They touch
at the same boundary coordinate, 20, but share no genomic base (20 is
not an element of `[10, 20)`), so they do **not** overlap under this
operation.

- If you expected your adjacent intervals to match, they are touching,
  not overlapping — see [Coordinate systems → why touching intervals
  are not overlaps](../preparing-your-data/coordinate-systems.md).
- If you *want* touching intervals to count, use
  [closest](closest.md): touching intervals have distance 0 there.

## Inner behavior

With **inner join**, only overlapping pairs appear in the result. A
query with no overlapping annotation produces **no rows at all** — the
query disappears from the table ([Join behavior: left vs
inner](join-behavior.md)).

## Left behavior

With **left join**, every query row appears: overlapping queries get
one row per overlapping annotation, and a query with no overlapping
annotation appears exactly once with all `annot_*` fields missing and
`has_overlap = False` ([Matched vs unmatched
rows](../results/matched-unmatched.md)).

## Multiple matches and duplicates

- One query overlapping **N** distinct annotations returns **N rows** —
  AnnotateR never picks one for you.
- Duplicate rows in your input (the same interval twice) are preserved
  and each produces its own result rows; nothing is collapsed.
- A query overlapping the *same* annotation twice is impossible in
  interval math, but the same query/annotation pair can appear twice if
  the annotation file lists it twice.

## See also

- [Minimum overlap](min-overlap.md) — the fraction-of-query threshold
  for overlap mode.
- [Contains](contains.md) / [Within](within.md) — the containment
  directions.
- [Strand-aware annotation](strand-aware.md) — making strand a
  condition of overlap.
- [Example 1: BED query against GFF3 annotations](../examples/bed-vs-gff3.md).