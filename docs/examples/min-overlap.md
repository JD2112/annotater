# Example 2: Minimum-overlap filtering

A minimal fixture that isolates what `min_overlap` does: three 100-base
queries, three annotations covering 100%, 40%, and 60% of them.

## Input

Query: [`data/examples/example_min_overlap_coordinates.bed`](https://github.com/JD2112/annotater/blob/main/data/examples/example_min_overlap_coordinates.bed)

```text
chr1    0      100     q_full
chr1    200    300     q_part40
chr1    400    500     q_part60
```

Annotation: [`data/examples/example_min_overlap_annotations.bed`](https://github.com/JD2112/annotater/blob/main/data/examples/example_min_overlap_annotations.bed)

```text
chr1    0      100     a_full
chr1    200    240     a_part40
chr1    410    470     a_part60
```

## Part A — the threshold at work

Settings: **Overlap**, **Min_overlap = 0.5**, **inner join**, feature
filter empty (BED annotations are not feature-filtered; the feature
filter only affects GFF/GTF files), strand off.

**Expected result: exactly 2 rows.**

| query | annotation | overlap | fraction | why |
|---|---|---|---|---|
| q_full | a_full | 100 | 1.0 | ≥ 0.5 |
| q_part60 | a_part60 | 60 | 0.6 | ≥ 0.5 |
| q_part40 | — | — | — | 0.4 < 0.5, fails the threshold |

`q_part40` does not appear at all — inner join drops queries with no
qualifying annotation.

## Part B — the same run with a left join

Switch to **Keep all query rows (left join)** and re-run.

**Expected result: 3 rows.** q_full/a_full and q_part60/a_part60 as
before, plus one row for **q_part40** with all `annot_*` columns
missing and `has_overlap = False`.

The threshold decision did not change between the two runs — only the
projection of the result
([Join behavior: left vs inner](../operations/join-behavior.md)).

## Part C (optional) — the inclusive threshold

Set **Min_overlap = 0.4** and re-run Part A (inner). **Expected: 3
rows** — q_part40 now qualifies, because the threshold is *inclusive*:
a pair covering *exactly* 40% passes at 0.4
([Minimum overlap → the exact rule](../operations/min-overlap.md#the-exact-rule)).

## What this example covered

- the fraction-of-**query** rule (denominator = query length);
- the inclusive threshold;
- per-pair judgment (no coverage summing);
- inner vs left on a threshold-failing query.

Next: [Example 3: Strand-aware annotation](strand.md).