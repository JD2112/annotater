# Join behavior: left vs inner

The **Join behavior** radio in the sidebar decides *which rows you see*.
It does not change which pairs qualify — the operation's predicate
defines qualification; the join only projects the result.

## The two behaviors

| Behavior (sidebar label) | Query rows in the result |
|---|---|
| **Keep all query rows (left join)** | **always exactly one row per query row**: once if nothing qualified, once per qualifying annotation otherwise |
| **Matched rows only (inner join)** | only qualifying pairs; a query with no qualifying annotation produces **no rows at all** |

In neither behavior is anything collapsed: N qualifying annotations
always produce N rows for that query.

## When a query has no match

```text
query:      Q1  Q2  Q3        (three query rows)
annotations: A (overlaps Q1 only)

left join:   Q1–A,  Q2 (unmatched),  Q3 (unmatched)     → 3 rows
inner join:  Q1–A                                 → 1 row
```

Unmatched rows are *real rows*, not display artifacts: they carry the
query's `coord_*` values, `has_overlap = False`, **missing** `annot_*`
fields, and — in closest mode — missing `distance`
([Matched vs unmatched rows](../results/matched-unmatched.md)).

## Which one do I want?

- **left** (the default) when you need a **complete table of your
  input** — e.g. you want to know which of *your* regions found nothing
  (a "no annotation assigned" flag is itself information). Most
  downstream pipelines want left.
- **inner** when you want only the pairs that qualified, e.g. to feed
  only matched regions to the next step.

The choice is **orthogonal to the operation**: every operation (overlap
with or without `min_overlap`, contains, within, closest) works with
both joins, and the only difference is unmatched rows.

## A note on counts

Left-join result row count ≥ query row count (some queries produce
several rows), and can be much larger for dense annotations. Inner-join
row count is whatever qualified. If your row count surprises you, check
this page before suspecting the operation — see
[FAQ → Why is my result table bigger than my input?](../faq.md).