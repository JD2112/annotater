# Query coordinates vs annotation features

Every AnnotateR run pairs exactly two files in two different roles.
Understanding the roles is the single most important thing before
uploading anything.

## The two roles

| Role | UI label | What it is | Typical example |
|---|---|---|---|
| **Query** | "Query coordinates" uploader | The intervals *you* want to annotate — the question you are asking | your ChIP-seq peaks, your variant calls, your region list |
| **Annotation** | "Annotation features" uploader | The reference features you annotate against — the answer key | a gene model (GFF3/GTF), a BED file of known intervals |

Each role takes exactly one file. The **same file format can play either
role**: a BED file can be your query *and* a BED file can be your
annotation (see [Example 4: contains vs within](../examples/contains-within.md),
which uses one file in both roles).

## Why the roles matter

The interval operation is directional with respect to the roles:

- "Does my region **contain** a feature?" compares **query ⊇ annotation**
  ([Contains](../operations/contains.md));
- "Does my variant sit **inside** a gene?" compares **query ⊂ annotation**
  ([Within](../operations/within.md));
- `min_overlap` measures how much of **the query** is covered
  ([Minimum overlap](../operations/min-overlap.md)).

Swapping the two files is usually not an error — it is a *different
question*, and it will give a different answer.

## You will see the roles again in the result

Every column of the result table is prefixed with its role:
`coord_*` columns can only come from your **query** file, `annot_*`
columns only from your **annotation** file. That is why you can read a
result row even when both files have columns with the same name — see
[Result columns and provenance](../results/result-columns.md).

## A word on size

There is no requirement that one file be larger than the other. A
hundred variants against a full genome annotation set and a million
peaks against a ten-line BED file are both valid runs; performance
notes for large inputs are in [Limitations](../limitations.md) and
[Troubleshooting](../troubleshooting.md).