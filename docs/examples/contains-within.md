# Example 4: contains vs within

One tiny BED file used as **both** the query and the annotation — the
clearest possible way to see that `contains` and `within` are
directional inverses, not aliases.

## Input

[`data/examples/example_contains_within.bed`](https://github.com/pyrevo/annotater/blob/main/data/examples/example_contains_within.bed) — upload it **twice** (once into each uploader):

```text
chr1    0     100    A    0    +
chr1    40    60     B    0    +
chr2    200   300    C    0    +
```

Geometry: `B` sits strictly inside `A` on chr1; `C` is unrelated
(different chromosome).

```text
chr1:  A [───────────────────────)    [0, 100)
           B [─────)                  [40, 60)
chr2:                      C [─────)  [200, 300)
```

## Part A — contains (query ⊇ annotation)

Upload the file as query **and** annotation. Settings: Operation
**Contains**, **left join**, strand off.

**Expected result: 4 rows — all matched** (every query contains at
least one annotation, including itself, so left join produces no
unmatched rows here):

| query | annotation | why |
|---|---|---|
| A | A | identical intervals — contained (boundary equality) |
| A | B | B is strictly inside A |
| B | B | identical intervals |
| C | C | identical intervals |

The matched pairs are (A,A), (A,B), (B,B), (C,C). Note what is *absent*:
(B,A) — B does not contain A — and anything on chr2, since C shares no
chromosome with A or B.

## Part B — within (query ⊆ annotation)

Same two files, change only the Operation to **Within** and re-run.

**Expected result: 4 rows — all matched**:

| query | annotation | why |
|---|---|---|
| A | A | identical intervals |
| B | A | B is strictly inside A |
| B | B | identical intervals |
| C | C | identical intervals |

The matched pairs are (A,A), (B,A), (B,B), (C,C).

## The side-by-side comparison

| | matched pairs | result rows (left) |
|---|---|---|
| **contains** | (A,A) (A,B) (B,B) (C,C) | 4 (all matched) |
| **within** | (A,A) (B,A) (B,B) (C,C) | 4 (all matched) |

The *only* difference between the two answer sets is the direction of
the B relationship: **contains** returns "A contains B"; **within**
returns "B is within A". Identical intervals (A,A), (B,B), (C,C)
appear in **both** — exactly as
[Within → contains vs within](../operations/within.md) and
[Contains → boundary equality](../operations/contains.md) promise.

## What this example covered

- the directionality of the two containment predicates, with one file
  playing both roles;
- boundary equality and identical intervals qualifying for both;
- chromosome independence (C never matches A or B);
- how the same input + operation swap changes the answer set — and why
  a "mirror image" of your expected results usually means a swapped
  direction.

Next: [Example 5: Finding the closest feature](closest.md).