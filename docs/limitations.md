# Limitations

An honest list of what AnnotateR does not do in the upcoming v0.1.0
release (currently in `0.1.0-rc1` beta testing). If a workflow needs any
of these, plan around them.

## Scope and data

- **Two files per run** — one query, one annotation. No batch mode, no
  stored analyses, no account, no history.
- **No intentional persistence** — parsed data and results exist only in
  application memory for the active session; download what you need
  ([Data handling](#data-handling)).
- **File size limit: 200 MB per file by default** (Streamlit's
  `server.maxUploadSize`, which AnnotateR does not override). The
  SciLifeLab Serve platform documents a lower 100 MB limit for Streamlit
  apps ([Uploading files](using/uploading-files.md#file-limits),
  [Deployment](deployment.md#environment-configuration)).
- **In-memory, single-session processing** — there is no job queue;
  very large runs are bounded by the deployment's resources and any
  deployment timeout. In the [AnnotateR benchmark](benchmark.md),
  Polars-Bio was faster for pair-producing operations (`overlap`,
  `contains`, `within`) on the measured workloads; `closest` uses the
  shared canonical implementation and has similar runtime across
  backends, and it is the most expensive operation at large scale.

## Data handling

- Uploaded files are processed by the running AnnotateR server.
- A temporary on-disk copy of each upload may be created for parsing. It
  is deleted immediately after parsing, whether parsing succeeds or
  fails.
- Parsed data and results remain only in application memory for the
  active session. AnnotateR does not intentionally persist uploaded files
  or results after that lifecycle.
- Local Docker execution processes uploads in the AnnotateR container
  running on your own machine; SciLifeLab Serve is not involved.
- This page makes no statement about the infrastructure that hosts a
  deployment (for example its logs, caches, proxies or node storage);
  consult the operator of the deployment you use.

## Format and semantics

- **VCF is query-only** — you cannot annotate against a VCF in v0.1.0.
- **Feature filtering applies to GFF/GTF only**, matches the feature
  type string exactly, and defaults to `gene` only
  ([Feature filtering](using/feature-filtering.md)).
- **Chromosome conversion covers UCSC ⇄ Ensembl only**, for the
  mappings `1–22, X, Y, MT` ⇄ `chr1–chr22, chrX, chrY, chrM`. NCBI
  accession-style identifiers are not converted; unmapped labels are
  left unchanged
  ([Chromosome identifiers](preparing-your-data/chromosome-identifiers.md)).
- **GFF3 and GTF are annotation-only inputs.** The query uploader does
  not accept them ([Supported file formats](preparing-your-data/supported-formats.md)).
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

- This manual documents the **upcoming v0.1.0** release
  (`0.1.0-rc1` beta testing), latest-only. The
  application is pre-1.0: the *canonical result schema and the
  scientific semantics* are stable by contract
  ([Technical Reference](technical/scientific-contract.md)), but UI
  labels, page structure, and convenience features may change before
  1.0 without migration guides.