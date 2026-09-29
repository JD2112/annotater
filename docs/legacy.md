# Legacy files (deleted)

The original implementation of this project was an R/Shiny application.
It has been fully superseded by the current Python/Streamlit product
(`streamlit_app/`) and was **never** part of the production product:
it was excluded from the production Docker image (the `Dockerfile`
white-lists only the Python entry point and modules; `.dockerignore`
excluded the R files).

The historical files were tracked temporarily for reference purposes,
pending a post-acceptance cleanup decision. That decision has been made:
**the legacy files were deleted from the repository** in preparation for
publication. They remain fully recoverable from git history.

Deleted files:

| File | What it was |
|---|---|
| `app/app.R` | Historical Shiny GUI entry point |
| `app/annotater.R` | Historical R command-line annotation script (Shiny backend worker) |
| `app/www/test.bed`, `app/www/test.gff3`, `app/www/test.vcf` | Small sample files for the historical Shiny app |
| `app/README.md` | Note on the legacy directory's retention status |
| `.Rprofile` | Sourced `renv/activate.R` (R environment bootstrap) |
| `renv.lock` | Lockfile for the historical R environment (`renv/` itself was never tracked) |
| `docs/polars-bio_manual.pdf` | Local convenience copy of the upstream Polars-Bio manual; the current official online documentation is linked in [references.md](references.md) and is authoritative |

Also deleted as internal process artifacts (never referenced by code or
product documentation): `docs/prompts/` (per-task implementation
prompts). `docs/*.resolved` historical scratch files are retained.

Historical license headers: the legacy R files carried original
author-header license statements (e.g. "License: GNU GPLv3" in
`app/app.R`, "GNU3 open license" in `app/annotater.R`). Deletion makes
no claim about retroactive relicensing of the historical
implementation. The license provenance record, including the maintainers'
decision that the current AnnotateR product is **BSD-3-Clause** (root
`LICENSE`), remains in
[implementation-notes.md](implementation-notes.md) and `CITATION.cff`.