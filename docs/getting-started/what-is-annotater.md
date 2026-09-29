# What is AnnotateR?

AnnotateR annotates genomic intervals against a set of reference
features — for example, "which genes do my sequencing peaks overlap?" —
completely in the browser. You upload two files, choose an interval
operation, and download a canonical result table. Nothing is stored on
any server.

## Who it is for

- **Researchers and bioinformaticians** with a list of genomic
  coordinates (peaks, variants, regions) who want to attach gene or
  feature information without leaving the browser.
- **Computational users** who need precisely defined interval semantics
  (0-based half-open coordinates, explicit containment and distance
  rules, deterministic results) — see the
  [Annotation Operations](../operations/choosing-an-operation.md)
  pages and
  [Result columns and provenance](../results/result-columns.md).

## The core idea: query × annotation

Every run pairs one **query** file with one **annotation** file:

- **Query coordinates** — the intervals *you* want to annotate (your
  variants, peaks, regions).
- **Annotation features** — the reference features you annotate against
  (genes, exons, transcripts).

The two roles are independent of file format: a BED file can be your
query *or* your annotation. See
[Query coordinates vs annotation features](../preparing-your-data/query-vs-annotation.md).

## Two interchangeable backends

AnnotateR executes the interval operation with one of two backends:
**Bedtools** (the established command-line tool) or **Polars-Bio**
(dataframe-based). They are interchangeable: for every supported
operation and option, AnnotateR defines the semantics and both engines
return the same canonical result. Choose by environment or preference —
see [Choosing an annotation engine](../using/engines.md).

## What AnnotateR is NOT

- **Not a database.** Files are processed in memory for the duration of
  your session and are not persisted anywhere.
- **Not a multi-user service.** One session, one user, your machine or a
  single deployment.
- **Not a genome browser.** AnnotateR computes interval relations and
  returns tables; it does not render or browse sequences.
- **No account, no upload history, no saved analyses.**

## What it is NOT opinionated about

AnnotateR does not guess biology for you: it does not merge overlapping
annotations, does not pick a single gene when several qualify, and does
not infer strand for files that lack it. Multiple qualifying features
produce multiple result rows, by design.

## Where to go next

- [Quick start](quick-start.md) — files to results in five minutes.
- [The AnnotateR workflow](workflow.md) — the pipeline in detail.
- [Limitations](../limitations.md) — an honest list of v0.1.0 boundaries.