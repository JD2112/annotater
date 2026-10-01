# Contains

> **The query interval fully contains the annotation interval.**

Formally, query `Q = [q_start, q_end)` and annotation
`A = [a_start, a_end)` on the same chromosome qualify when:

```text
q_start <= a_start
and
q_end   >= a_end
```

Use **contains** when the containing interval is *yours*: "my regions —
what features fit **inside** them?" (for example, which exons fall
entirely inside my peaks). The directional inverse is
[Within](within.md).

## Diagram

<!-- BEGIN GENERATED: contains_example -->
```text
coordinates are 0-based half-open; chromosome chr1

bases   10 11 12 13 14 15 16 17 18 19 20 21 22 23
query    #  #  #  #  #  #  #  #  #  #  #  #  #  #  [10, 24)
A        .  .  .  .  #  #  #  #  #  #  .  .  .  .  [14, 20)

query  bases 10–23 (14 bases); boundary coordinates 10 and 24
A      bases 14–19 (6 bases); boundary coordinates 14 and 20

overlap: yes
overlap length: 6
query contains annotation: yes
query within annotation: no
```
<!-- END GENERATED: contains_example -->

## Boundary equality qualifies

The inequalities are inclusive: an annotation that starts exactly where
the query starts, or ends exactly where the query ends, is contained.

```text
shared left edge:   query [10, 60),  annotation [10, 50)   →  contained (q_start == a_start)
shared right edge:  query [10, 60),  annotation [20, 60)   →  contained (q_end   == a_end)
```

## Identical intervals qualify

If query and annotation are the *same* interval, they satisfy
`contains` — and they also satisfy [within](within.md). See
[Within → contains vs within: a directional pair](within.md#contains-vs-within-a-directional-pair).

## contains is not min_overlap = 1

At [minimum overlap](min-overlap.md) threshold 1 the rule is
"the query is 100% covered by one annotation" — a different geometry in
both directions:

- `Q = [10, 20)`, `A = [0, 100)`: passes `min_overlap = 1` (the small
  query is fully covered) but **fails** `contains` (the annotation is
  not inside the query).
- `Q = [0, 100)`, `A = [10, 20)`: is a `contains` match but scores only
  0.1 at `min_overlap = 1`.

If you need containment, use **contains**; do not approximate it with
`min_overlap`.

## Touching intervals never qualify

Containment requires the annotation's bases to be inside the query's
bases. Touching intervals meet at the same boundary coordinate but share no base
([Overlap → touching is not overlap](overlap.md#touching-is-not-overlap)),
so they can never be contained either way.

## Strand

Strand matching composes with `contains` by **AND**: a pair qualifies
only if it satisfies containment *and* (when enabled) the strand rule
([Strand-aware annotation](strand-aware.md)).

## Row behavior

One query containing N annotations returns N rows (inner) or those N
rows plus one unmatched row if N = 0 (left) —
[Join behavior: left vs inner](join-behavior.md).

## See also

- [Within](within.md) — the directional inverse, with the shared
  comparison.
- [Example 4: contains vs within](../examples/contains-within.md) — one
  file, two runs, side-by-side results.