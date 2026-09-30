# Limitations

An honest list of what AnnotateR v0.1.0 does not do. If a workflow
needs any of these, plan around them.

## Scope and data

- **Two files per run** — one query, one annotation. No batch mode, no
  stored analyses, no account, no history.
- **No persistence** — files and results exist only for your session;
  download what you need.
- **File size limit: 200 MB per file** ([Uploading files](using/uploading-files.md)).
- **In-memory, single-session processing** — there is no job queue;
  very large runs are bounded by the deployment's resources and any
  deployment timeout. In the [AnnotateR benchmark](benchmark.md),
  Polars-Bio was faster for pair-producing operations (`overlap`,
  `contains`, `within`) on the measured workloads; `closest` uses the
  shared canonical implementation and has similar runtime across
  backends, and it is the most expensive operation at large scale.

## Format and semantics

- **VCF is query-only** — you cannot annotate against a VCF in v0.1.0.
- **Feature filtering applies to GFF/GTF only**, matches the feature
  type string exactly, and defaults to `gene` only
  ([Feature filtering](using/feature-filtering.md)).
- **Chromosome conversion covers UCSC ⇄ Ensembl.** NCBI accession
  styles are recognized but not a convertible target
  ([Chromosome identifiers](preparing-your-data/chromosome-identifiers.md)).
- **Strand is an equality filter only** — no strand flip, no
  reverse-complement, no sense/antisense beyond `+`/`-`
  ([Strand information](preparing-your-data/strand-information.md)).
- **No feature "selection"** — every qualifying annotation produces a
  row. There is no "best gene" logic, no merging of duplicates, no
  deduplication: input rows are preserved, never collapsed.
- **No operation chaining** — one interval operation per run; combine
  steps in your downstream pipeline.
- **Closest has no distance limit** — every query gets its nearest
  same-chromosome annotation(s), however far, unless left-join
  unmatched rows are all you get (e.g. strand mismatch).

## Environments

- **Bedtools requires a system binary** on PATH with a writable
  `TMPDIR`; if missing, the run fails loudly and Polars-Bio is the
  alternative ([Deployment](deployment.md),
  [Troubleshooting → engine unavailable](troubleshooting.md#engine-unavailable)).
- **Excel export requires openpyxl** in the app environment.

## Version

- This manual documents the **v0.1.0** release, latest-only. The
  application is pre-1.0: the *canonical result schema and the
  scientific semantics* are stable by contract
  ([Technical Reference](technical/scientific-contract.md)), but UI
  labels, page structure, and convenience features may change before
  1.0 without migration guides.