# Legacy files (temporary retention)

The original implementation of this project was an R/Shiny application.
It has been fully superseded by the current Python/Streamlit product
(`streamlit_app/`) and is **not part of the product**. The files below are
retained in the repository **temporarily, for historical/reference
purposes only**, pending a post-acceptance cleanup decision (deletion or
move into a `legacy/` directory).

| File | What it is | Referenced by current code/docs | Runtime dependency |
|---|---|---|---|
| `app/annotater.R` | Historical R command-line annotation script (Shiny backend worker) | `app/app.R` only | No |
| `app/app.R` | Historical Shiny GUI entry point | nothing current | No |
| `app/www/test.bed`, `app/www/test.gff3`, `app/www/test.vcf` | Small sample files for the historical Shiny app | `app/app.R` only | No |
| `.Rprofile` | Sources `renv/activate.R` (R environment bootstrap) | nothing current | No |
| `renv.lock` | Lockfile for the historical R environment (`renv/` itself is not tracked) | nothing current | No |
| `docs/polars-bio_manual.pdf` | Downloaded copy of upstream Polars-Bio documentation, kept as a local convenience copy. The current official online documentation is linked in [references.md](references.md) and takes precedence. Retained for now; candidate for removal after GUI acceptance once the maintainers confirm the online links are sufficient. | `docs/references.md` (describes it as a historical/local convenience copy) | No |

Disposition decisions (release-prep-0.1.0 pass):

- **Retain** all files in git for now. No deletion or reorganization in
  this pass.
- **Documented** here.
- **Excluded from the production Docker image**: the `Dockerfile`
  white-lists only `app.py`, `streamlit_app/`, `data/examples/`,
  `benchmarks/benchmark_engines.py`, and `scripts/docker_smoke.sh`, and
  `.dockerignore` additionally excludes `app/`, `renv.lock`, and `renv/`.
- **Final decision** (delete vs. move to `legacy/`) happens after manual
  GUI acceptance, as a separate, reference-safe cleanup.

Historical license headers: the legacy R files retain their original
author-header license statements (e.g. "License: GNU GPLv3" in
`app/app.R`) unchanged, as part of the historical record. Those headers
do not describe the current product: the current AnnotateR
Python/Streamlit release is licensed under **BSD-3-Clause** (root
`LICENSE`; license provenance and the maintainer decision are recorded in
[implementation-notes.md](implementation-notes.md)). No claim is made
about retroactive relicensing of the historical implementation.