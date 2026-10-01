# Minimum overlap (min_overlap)

`min_overlap` sharpens the [overlap](overlap.md) operation: a pair
qualifies only if a **single annotation** covers at least a specified
fraction of the **query**.

## The exact rule

For a query `Q` of length `|Q| = q_end − q_start` and one annotation
`A`, let `overlap_length` be the positive intersection length
(`0` when the intervals do not overlap). The pair qualifies if and
only if:

```text
overlap_length / |Q| >= min_overlap
```

with a positive overlap still required. Four properties follow from
this formula — and they answer most surprising results:

1. **The denominator is the query length.** What matters is how much of
   *your* interval is covered, never how much of the annotation.
2. **The threshold is inclusive.** A pair that covers *exactly* the
   threshold qualifies (e.g. exactly 50% passes at `min_overlap = 0.5`).
3. **Coverage is never summed.** Each query/annotation pair is judged
   **alone**. Two annotations that together cover 100% of a query do
   not replace one annotation that covers 100%; at threshold 0.5, each
   of them (covering 40% and 60%) is judged on its own 40% or 60%.
4. **The annotation's own coverage is irrelevant.** A tiny annotation
   that is 100% covered by the query but covers only 20% of it **fails**
   at `min_overlap = 0.5`.

`min_overlap = 0` is plain overlap (any positive intersection), and the
slider is available **in overlap mode only**.

## Numerical example

Three queries of length 100 each, threshold `min_overlap = 0.5`,
inner join:

```text
query q_full:    [───────────────────────────────)   [0, 100)
annotation a_full:    [───────────────────────────────)   [0, 100)     → 100/100 = 1.0  ✓

query q_part40:  [───────────────────────────────)   [200, 300)
annotation a_part40:  [─────)                          [200, 240)   → 40/100  = 0.4  ✗

query q_part60:  [───────────────────────────────)   [400, 500)
annotation a_part60:      [─────────────)            [410, 470)   → 60/100  = 0.6  ✓
```

At `min_overlap = 0.5` with an **inner** join the result contains
exactly two rows (`q_full/a_full` and `q_part60/a_part60`);
`q_part40` vanishes. With a **left** join it remains, once, unmatched —
see [Example 2: Minimum-overlap filtering](../examples/min-overlap.md)
for this exact fixture.

## Boundary example

A pair that covers exactly the threshold qualifies. Facts for one
canonical pair:

<!-- BEGIN GENERATED: min_overlap_on_threshold -->
```text
coordinates are 0-based half-open; chromosome chr1

bases   10 11 12 13 14 15 16 17 18 19 20 21 22 23 24
query    #  #  #  #  #  #  #  #  #  #  .  .  .  .  .  [10, 20)
A        .  .  .  .  .  #  #  #  #  #  #  #  #  #  #  [15, 25)

query  bases 10–19 (10 bases); boundary coordinates 10 and 20
A      bases 15–24 (10 bases); boundary coordinates 15 and 25

min_overlap threshold: 0.5
overlap: yes
overlap length: 5
query length: 10
overlap fraction (query-relative): 0.5
passes min_overlap: yes
```
<!-- END GENERATED: min_overlap_on_threshold -->

## min_overlap = 1 is NOT contains

A common guess: "100% overlap must mean the annotation contains the
query" — it does not, and the direction matters. Two counterexamples
(query `Q`, annotation `A`):

| Case | Intervals | `overlap/|Q|` at threshold 1 | What `contains` would say |
|---|---|---|---|
| Annotation much larger than query | `Q = [10, 20)`, `A = [0, 100)` | overlap 10 / 10 = 1.0 → **passes** | `A` contains `Q`, not the other way around |
| Query much larger than annotation | `Q = [0, 100)`, `A = [10, 20)` | overlap 10 / 100 = 0.1 → **fails** | `Q` contains `A` |

`min_overlap` measures *the query's* coverage; `contains` asserts a
geometric direction ([Contains](contains.md)). They agree on nothing by
accident.

## Left-mode behavior

In left-join mode a query whose overlaps all fail the threshold appears
exactly once, unmatched, with `has_overlap = False`
([Matched vs unmatched rows](../results/matched-unmatched.md)).

## Where to go next

- [Choosing an operation](choosing-an-operation.md) — `min_overlap` as a
  modifier of overlap.
- [Example 2](../examples/min-overlap.md) — the worked fixture above.
- [FAQ → Does min_overlap add up coverage?](../faq.md)