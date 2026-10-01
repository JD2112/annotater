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

```text
bases:        10        11        12        13  14  15  16  17  18  19  20
query:       [─────────────────────────────)                          [10, 20)
annotation:                                            [─────────────) [19, 20)
```

The shared bases are base 19 — a **1-base overlap is a real overlap**.
Any positive intersection counts; there is no minimum length in plain
overlap mode (that is what `min_overlap` adds; see below).

## Overlap (interval intersection)

```text
bases:        0   10   20   30   40   50   60   70   80   90  100
query:        [────────────────────────────)                                 [10, 60)
annotation:              [──────────────────────────)                         [30, 80)
                         shared bases: 30..59  →  overlap of 30 bases
```

## Touching is NOT overlap

```text
bases:        10  11  12  13  14  15  16  17  18  19  20  21  22  23  24  25
query:        [────────────)                                        [10, 20)
annotation:                        [────────)                       [20, 25)
```

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