# Within

> **The query interval is fully contained within the annotation
> interval.**

Formally, query `Q = [q_start, q_end)` and annotation
`A = [a_start, a_end)` on the same chromosome qualify when:

```text
a_start <= q_start
and
a_end   >= q_end
```

Use **within** when the containing interval is the *reference
feature*: "my points — what feature sits **around** them?" (for
example, which gene spans each of my variants). The directional inverse
is [Contains](contains.md).

## Diagram

<!-- BEGIN GENERATED: within_example -->
```text
coordinates are 0-based half-open; chromosome chr1

bases   10 11 12 13 14 15 16 17 18 19 20 21 22 23
query    .  .  .  .  #  #  #  #  #  #  .  .  .  .  [14, 20)
A        #  #  #  #  #  #  #  #  #  #  #  #  #  #  [10, 24)

query  bases 14–19 (6 bases); boundary coordinates 14 and 20
A      bases 10–23 (14 bases); boundary coordinates 10 and 24

overlap: yes
overlap length: 6
query contains annotation: no
query within annotation: yes
```
<!-- END GENERATED: within_example -->

## Boundary equality and identity

Exactly as for [contains](contains.md): shared edges qualify
(`a_start == q_start` or `a_end == q_end`), and **identical intervals
qualify for `within` as well as `contains`**.

## within is not the opposite of min_overlap either

The SPEC counterexample: `Q = [10, 20)`, `A = [5, 15)`.

- `min_overlap = 0.5`: overlap is `[10, 15)` = 5 bases; `5 / 10 = 0.5`
  → **passes** (inclusive threshold).
- `within`: `a_end = 15 < q_end = 20` → **fails**. The query's last 5
  bases are not inside the annotation.

A "half-covered" query is inside *part* of an annotation, not inside it.

## contains vs within: a directional pair

The two predicates are **directional inverses**, never aliases:

| Operation | Containing interval | Contained interval | Ask yourself |
|---|---|---|---|
| **contains** | **the query** | the annotation | "my regions, what features fit *inside* them?" |
| **within** | **the annotation** | the query | "my points, what feature sits *around* them?" |

Identical intervals satisfy **both** — and that is the only overlap
between the two answer sets in the equal-interval case:

```text
query:         [────────────)      [30, 50)
annotation:    [────────────)      [30, 50)   identical  →  contains ✓  and  within ✓
```

A practical check when you get "wrong" results: if your answer set
looks like the mirror image of what you expected, you likely chose the
wrong direction — swapping the two uploaded files exchanges
`contains` for `within`. Worked example:
[Example 4: contains vs within](../examples/contains-within.md).

## Strand

Strand matching composes with `within` by **AND**, exactly as for
contains ([Strand-aware annotation](strand-aware.md)).

## Row behavior

One query contained by N annotations returns N rows (inner) or those
plus one unmatched row if N = 0 (left) —
[Join behavior: left vs inner](join-behavior.md).

## See also

- [Contains](contains.md) — the inverse predicate.
- [Choosing an operation](choosing-an-operation.md) — the bookmark
  matrix.