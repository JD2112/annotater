# Closest (nearest)

**closest** answers "which annotation is nearest to my query?" — and it
is the one operation where the annotation does **not** need to overlap
the query at all.

## The canonical AnnotateR distance

For a query `Q = [q_start, q_end)` and a same-chromosome annotation
`A = [a_start, a_end)`:

```text
distance = max(0, a_start − q_end, q_start − a_end)
```

The distance is the exact number of bases in the gap between the two
intervals, and it is always a non-negative integer.

```text
overlapping:   Q [──)    A [────)        →  0
                              [5,25) [15,40)

touching:      Q [──) A [──)             →  0   (a_start == q_end)
                              [5,15) [15,25)

one-base gap:  Q [──) . A [──)           →  1   (base 15 is the gap)
                              [5,15) [16,26)

large gap:     Q [──) ...... A [──]      →  75
                              [5,15) [90,100)
```

Key readings of this formula:

- **Overlapping intervals have distance 0** — `max` with 0 clamps the
  negative "gap".
- **Touching intervals have distance 0** — there is no base between
  them. (Touching is *not* an [overlap](overlap.md); here it is
  simply distance 0. Both statements are true at once.)
- **One base between → distance 1.** The distance counts the bases in
  the gap: `[5,15)` and `[16,26)` have exactly base 15 between them.
- **Same chromosome only.** Annotations on other chromosomes are never
  candidates.
- This is AnnotateR's canonical distance, defined by the project — it
  is not the output of any particular backend's native distance mode.

## All ties are returned

If several annotations are equally nearest, **all of them are
returned** — one row each, at the same `distance`. AnnotateR never
breaks a tie arbitrarily. The tied rows appear in **annotation input
order**.

```text
query:                        [──)                 [3750, 3751)
annotation 1:  [────────)                       [3500, 3600)   distance 150
annotation 2:                                [────────)        [3901, 4000)  distance 150
             → both rows returned, in annotation input order
```

## Strand is applied before selection

When strand matching is enabled, annotations that fail the strand rule
are removed from candidacy **before** the nearest search
([Strand-aware annotation](strand-aware.md)). The consequence: a *nearer*
opposite-strand (or missing-strand) annotation **cannot suppress** a
farther same-strand one.

## What the result looks like

In closest mode the result table has one extra column, **`distance`**
(integer ≥ 0):

- matched rows carry the gap to the attached annotation;
- unmatched rows (left join) have **missing** `distance` and missing
  `annot_*` fields;
- **`has_overlap = True` means "an annotation was attached"**, not
  "the intervals overlap" — a row with `has_overlap = True` and
  `distance = 250` is a separated nearest-feature row, not an overlap.
  (In overlap/contains/within modes `has_overlap=True` genuinely means
  the intervals overlap.)

`min_overlap` does not participate in closest mode, and the `min_overlap`
slider is not even shown
([Configuring the analysis](../using/configuring.md)).

## Row behavior

One query with K tied-nearest annotations returns K rows; a query with
no same-chromosome annotation at all returns one unmatched row (left
join) or nothing (inner join) — [Join behavior: left vs
inner](join-behavior.md). Note closest is typically the *most
expensive* operation on large inputs
([Limitations](../limitations.md)).

## See also

- [Example 5: Finding the closest feature](../examples/closest.md) —
  distance 0, a 50-base gap, an exact tie, and an unmatched variant in
  one fixture.
- [FAQ → Why can closest return several annotations?](../faq.md)