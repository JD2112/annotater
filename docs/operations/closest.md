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

**Overlapping** — distance 0 because the intervals share bases:

<!-- BEGIN GENERATED: closest_overlapping -->
```text
coordinates are 0-based half-open; chromosome chr1

bases   10 11 12 13 14 15 16 17 18 19 20 21 22 23
query    #  #  #  #  #  #  #  #  #  #  .  .  .  .  [10, 20)
A        .  .  .  .  #  #  #  #  #  #  #  #  #  #  [14, 24)

query  bases 10–19 (10 bases); boundary coordinates 10 and 20
A      bases 14–23 (10 bases); boundary coordinates 14 and 24

overlap: yes
overlap length: 6
closest distance: 0
```
<!-- END GENERATED: closest_overlapping -->

**Touching** — distance 0, but *not* an overlap (no shared base):

<!-- BEGIN GENERATED: touching_intervals -->
```text
coordinates are 0-based half-open; chromosome chr1

bases   10 11 12 13 14 15 16 17 18 19 20 21 22 23 24
query    #  #  #  #  #  #  #  #  #  #  .  .  .  .  .  [10, 20)
A        .  .  .  .  .  .  .  .  .  .  #  #  #  #  #  [20, 25)

query  bases 10–19 (10 bases); boundary coordinates 10 and 20
A      bases 20–24 (5 bases); boundary coordinates 20 and 25

overlap: no
overlap length: 0
closest distance: 0
```
<!-- END GENERATED: touching_intervals -->

**One-base gap** — base 20 lies between them, so distance 1:

<!-- BEGIN GENERATED: one_base_gap -->
```text
coordinates are 0-based half-open; chromosome chr1

bases   10 11 12 13 14 15 16 17 18 19 20 21 22 23 24
query    #  #  #  #  #  #  #  #  #  #  .  .  .  .  .  [10, 20)
A        .  .  .  .  .  .  .  .  .  .  .  #  #  #  #  [21, 25)

query  bases 10–19 (10 bases); boundary coordinates 10 and 20
A      bases 21–24 (4 bases); boundary coordinates 21 and 25

overlap: no
overlap length: 0
closest distance: 1
```
<!-- END GENERATED: one_base_gap -->

**Large gap** — the distance counts every base in the gap:

<!-- BEGIN GENERATED: closest_large_gap -->
```text
coordinates are 0-based half-open; chromosome chr1

bases    2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20
query    #  #  #  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  [2, 5)
A        .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  #  #  #  #  [17, 21)

query  bases 2–4 (3 bases); boundary coordinates 2 and 5
A      bases 17–20 (4 bases); boundary coordinates 17 and 21

overlap: no
overlap length: 0
closest distance: 12
```
<!-- END GENERATED: closest_large_gap -->

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

<!-- BEGIN GENERATED: closest_tie -->
```text
coordinates are 0-based half-open; chromosome chr1

bases    6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24
query    .  .  .  .  #  #  #  .  .  .  .  .  .  .  .  .  .  .  .  [10, 13)
A1       #  #  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  [6, 8)
A2       .  .  .  .  .  .  .  .  .  #  #  .  .  .  .  .  .  .  .  [15, 17)
A3       .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  .  #  #  #  [22, 25)

query  bases 10–12 (3 bases); boundary coordinates 10 and 13
A1     bases 6–7 (2 bases); boundary coordinates 6 and 8
A2     bases 15–16 (2 bases); boundary coordinates 15 and 17
A3     bases 22–24 (3 bases); boundary coordinates 22 and 25

closest distance: 2
closest ties retained: 2 (annotation order: A1, A2)
```
<!-- END GENERATED: closest_tie -->

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