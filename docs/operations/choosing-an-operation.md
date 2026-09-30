# Choosing an operation

This is the front door to the four relation modes
(overlap, contains, within, closest). If you are not sure which one
you need, work through the questions below.

## The questions

```text
Q: I want every feature that intersects my query by at least one base?
  A: overlap

Q: …but only if a feature covers at least some FRACTION of my query?
  A: overlap + minimum overlap (min_overlap)

Q: The annotation must lie completely INSIDE my query?
  A: contains     — my regions, what features fit inside them

Q: My query must lie completely INSIDE the annotation?
  A: within       — my points, what feature sits around them

Q: I don't need any intersection — which annotation is NEAREST,
   even if far away?
  A: closest
```

## contains vs within: a directional pair

These two are the classic source of swapped answers, so here is the
mnemonic:

| Operation | Containing interval | Contained interval | Ask yourself |
|---|---|---|---|
| **contains** | **the query** | the annotation | "my regions, what features fit *inside* them?" |
| **within** | **the annotation** | the query | "my points, what feature sits *around* them?" |

Two properties make this airtight:

1. **Identical intervals satisfy both.** If query and annotation are the
   same interval, both operations return the pair.
2. **They are directional inverses.** Swapping the two uploaded files
   turns a `contains` question into a `within` question (and vice
   versa). The predicates are never aliases and never combined.

Worked examples: [Contains](contains.md), [Within](within.md), and
[Example 4: contains vs within](../examples/contains-within.md).

## Modifiers, not modes

Two options change *qualification* without being operations of their
own:

- **`min_overlap`** — applies to **overlap mode only**. It raises the
  bar from "any positive overlap" to "at least this fraction of the
  query is covered by one annotation"
  ([Minimum overlap](min-overlap.md)).
- **Strand matching** — applies to **all** operations. It adds an
  eligibility condition (both rows carry an explicit, equal strand)
  ([Strand-aware annotation](strand-aware.md)).

And the **join behavior** (left/inner) is *not* about qualification at
all: it only decides which rows you see — every query row, or only
matched rows ([Join behavior: left vs inner](join-behavior.md)).

## The bookmark matrix

| | overlap required? | touching (0-base gap) qualifies? | `min_overlap` applies? | strand applies? | `distance` column? |
|---|---|---|---|---|---|
| **overlap** | yes, ≥ 1 base | no | yes | yes | no |
| **overlap + min_overlap** | yes, ≥ threshold fraction | no | **this is it** | yes | no |
| **contains** | yes (containment implies overlap) | no | no | yes | no |
| **within** | yes (containment implies overlap) | no | no | yes | no |
| **closest** | **no** | yes (distance 0) | no | yes (before selection) | **yes** |

Notes on the matrix:

- contains/within are *implemented* as overlap candidates plus a
  containment check, so they never return non-overlapping pairs — but
  the qualifying rule you should use to *choose* them is containment,
  not overlap.
- In closest mode, `has_overlap=True` means "an annotation was
  attached" (possibly at a positive distance), not "the intervals
  overlap" — the `distance` column tells you the gap
  ([Closest (nearest)](closest.md)).

## Which join should I use with the operation?

There is no required pairing. The rule of thumb:

- **left join** if you need a complete table of *your input* (every
  query row present, matches or not) — the default, and what most
  downstream pipelines want;
- **inner join** if you only want the pairs that qualified.

See [Join behavior: left vs inner](join-behavior.md).