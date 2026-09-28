# External References and Manuals

**Last checked:** 2026-09-25

This file is the reference index for version-sensitive implementation decisions. Prefer primary project documentation and specifications. Agents changing interval semantics MUST consult the relevant reference rather than relying on memory or inferred backend behavior.

## Genomic interval engines

### bedtools

- **bedtools documentation:** https://bedtools.readthedocs.io/
- **`intersect` manual:** https://bedtools.readthedocs.io/en/latest/content/tools/intersect.html
- **`closest` manual:** https://bedtools.readthedocs.io/en/latest/content/tools/closest.html

Implementation notes relevant to AnnotateR:

- `intersect -loj` is the reference behavior for retaining A records with and without B overlaps.
- `-f`, `-F`, `-r`, and `-e` have distinct fractional-overlap semantics; do not compress them into one application parameter without explicitly defining the mapping.
- `-f` is a minimum overlap as a fraction of **A**; `-F` is a minimum overlap as a fraction of **B**. AnnotateR passes the query table as `-a` and the annotation table as `-b`, so a native `-F 1.0` expresses "the annotation is covered by the query" — the `contains` direction (SPEC 8.4) — not `within` (SPEC 8.5). Backend fraction flags must not define an AnnotateR interval relation in either direction.
- `-s` enforces same-strand intersections.
- **`closest -d` distance is gap + 1 for separated pairs (bedtools 2.31.1, observed):** for `[15,25)` vs `[100,200)` it reports 76 (the canonical half-open gap is 75 = 100 − 25), and for a touching pair (`a_start == q_end`) it reports 1. This native value is NON-NORMATIVE for AnnotateR: since Task 6E, `mode="closest"` never calls bedtools `closest` and recomputes the canonical distance `max(0, a_start - q_end, q_start - a_end)` (SPEC 8.6). Also note `closest` requires genomically sorted input and, by default, returns only ONE feature per query (`-t` selects which tie) — neither behavior is reproducible as-is in the AnnotateR contract (all ties are returned, SPEC 8.6).

### pybedtools

- **Documentation:** https://daler.github.io/pybedtools/
- **`BedTool.intersect` API:** https://daler.github.io/pybedtools/autodocs/pybedtools.bedtool.BedTool.intersect.html
- **GitHub:** https://github.com/daler/pybedtools

pybedtools is a Python wrapper around bedtools behavior. The external bedtools executable remains a system dependency and should be documented separately from Python requirements.

Empirical observation (Task 8): pybedtools' Cython iterator packs record positions into a 32-bit `CHRPOS` field, so result iteration raises `OverflowError: value too large to convert to CHRPOS` for coordinates >= 2**31 (2,147,483,647). This is a hard input limit of AnnotateR's Bedtools backend as implemented (see `docs/benchmark.md`, Limitations); every natural chromosome is far below this bound.

### Polars-Bio

- **Documentation home:** https://biodatageeks.org/polars-bio/
- **Quick start:** https://biodatageeks.org/polars-bio/quick-start/
- **Genomic operations API:** https://biodatageeks.org/polars-bio/api/operations/
- **Genomic operations guide:** https://biodatageeks.org/polars-bio/features/operations/
- **DataFrame support:** https://biodatageeks.org/polars-bio/features/dataframes/
- **GitHub:** https://github.com/biodatageeks/polars-bio
- **PyPI (pinned release):** https://pypi.org/project/polars-bio/0.35.1/
- **PyPI JSON (wheel metadata, machine-readable):** https://pypi.org/pypi/polars-bio/0.35.1/json

Important current-API observations:

- `overlap()` accepts explicit `cols1` and `cols2` interval columns.
- Current documented default suffixes are `("_1", "_2")`, not `_right`.
- `overlap_output="join"` returns joined overlapping pairs.
- `overlap_output="left"` returns df1 rows that overlap at least one df2 row; it is not, by itself, equivalent to bedtools `-loj` because non-overlapping df1 rows are absent.
- The pinned 0.35.1 package exposes no containment primitive in either direction (its interval operations are `overlap`, `nearest`, `count_overlaps`, `coverage`, `depth`, `merge`, `cluster`, `complement`, `subtract`); AnnotateR therefore derives `contains` and `within` from ordinary `overlap` candidates plus a shared canonical predicate (SPEC 8.4 / 8.5).
- **`nearest` distance is the raw gap (0 for overlapping AND touching pairs), and `k` selects ONE row per query:** unlike bedtools `closest -d` (gap + 1 for separated pairs, 1 for touching), polars-bio `nearest.distance` reports 75 for `[15,25)` vs `[100,200)` and 0 for a touching pair, and its one-row-per-query selection is a backend-defined tie break. All of this is NON-NORMATIVE for AnnotateR: since Task 6E, `mode="closest"` never calls `nearest` and uses the shared canonical selection and distance (SPEC 8.6).
- coordinate metadata can be used by Polars-Bio I/O paths, but AnnotateR must still own and test its canonical application coordinate semantics.
- **Wheel availability (re-verified 2026-09-25 from the PyPI JSON above):** the pinned 0.35.1 release publishes a `manylinux_2_17_x86_64` wheel and macOS/Windows wheels, but **no `linux/aarch64` wheel**. This is why the production Docker image is pinned to `linux/amd64` (see `docs/deployment.md`); an arm64-native build cannot resolve the pinned dependency set.

The repository currently also contains `docs/polars-bio_manual.pdf`. Treat that PDF as a historical/local convenience copy. For version-sensitive implementation, the current official online documentation above takes precedence unless the project deliberately pins a version whose bundled manual is authoritative.

## File-format semantics

### BED / UCSC conventions

- **UCSC BED FAQ / format documentation:** https://genome.ucsc.edu/FAQ/FAQformat.html#format1

BED uses zero-based starts with half-open interval interpretation in standard genomic tooling.

### GFF3

- **Sequence Ontology GFF3 specification:** https://github.com/The-Sequence-Ontology/Specifications/blob/master/gff3.md

GFF3 coordinates are 1-based and inclusive. Conversion to AnnotateR's canonical half-open interval model must therefore be explicit and boundary-tested.

### VCF

- **GA4GH / hts-specs VCF specification repository:** https://github.com/samtools/hts-specs
- **Normative VCF specification version: VCF v4.5** ("The Variant Call Format Specification, VCFv4.5 and BCFv2.2"): https://github.com/samtools/hts-specs/blob/master/VCFv4.5.tex
- **Rendered VCF v4.5 PDF:** https://github.com/samtools/hts-specs/blob/master/VCFv4.5.pdf

VCF POS is 1-based. Variant interval construction depends on REF/END semantics and must not be treated as a generic BED row without an explicit conversion rule. AnnotateR's line-based VCF parser implements the fixed eight tab-separated fields (CHROM POS ID REF ALT QUAL FILTER INFO) plus INFO/END span handling; if the parser's supported feature set ever diverges from VCF v4.5, update this section and the parser tests together.

### GTF

- GENCODE GTF format:
  https://www.gencodegenes.org/pages/data_format.html

## Dataframe/runtime libraries

### Polars

- **Python documentation:** https://docs.pola.rs/api/python/stable/reference/
- **User guide:** https://docs.pola.rs/

Use explicit nullable/data-type behavior when canonical result equality depends on type or missing-value representation.

### pandas

- **Documentation:** https://pandas.pydata.org/docs/
- **Testing helpers:** https://pandas.pydata.org/docs/reference/testing.html

`pandas.testing.assert_frame_equal` is appropriate for strict canonical table comparisons.

## Application and testing

### Streamlit

- **Documentation:** https://docs.streamlit.io/
- **App testing overview:** https://docs.streamlit.io/develop/concepts/app-testing
- **`st.testing.v1.AppTest`:** https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest

Streamlit's native `AppTest` can execute an app headlessly, manipulate widgets, and inspect rendered output. Use it for UI integration after core engine parity is protected by lower-level tests.

### pytest

- **Documentation:** https://docs.pytest.org/
- **Parametrization:** https://docs.pytest.org/en/stable/how-to/parametrize.html

Shared engine-contract tests should prefer parametrization where the same semantic expectation applies to multiple backends.

## Deployment

### SciLifeLab Serve

Re-checked against the current official documentation on **2026-09-25** (Task 8). Exact pages:

- **Streamlit app hosting (step-by-step guide, resource defaults, image/tag rules, upload limit, FAQ):** https://serve.scilifelab.se/docs/application-hosting/streamlit/
- **Application hosting overview (port range 3000-9999, public code/data requirement, no databases):** https://serve.scilifelab.se/docs/application-hosting/
- **Other framework / custom apps:** https://serve.scilifelab.se/docs/application-hosting/other/
- **DOI for public apps:** https://serve.scilifelab.se/docs/doi/
- **Example Streamlit image + repo (GHCR publishing workflow template):** https://github.com/ScilifelabDataCentre/streamlit-image-to-smiles

Verified requirements that drive the AnnotateR deployment (details and the
build/test procedure are in [deployment.md](deployment.md)):

- Streamlit apps must be packaged as Docker images; the main application file must be named **`app.py`** in the image working directory.
- The app runs on **port 8501** (Serve asks for the port when creating the app; the overall platform range is 3000-9999).
- Build guidance uses `docker build --platform linux/amd64 -t <name>:<tag> .`.
- Default resources: **2 vCPU / 4 GB RAM** (requestable up to 12 vCPU / 48 GB with a motivated example).
- Images are pulled from a public registry (Docker Hub or GHCR) **at regular intervals** and must remain available; **each app version needs a unique image tag**.
- Upload size limit for Streamlit apps: **100 MB**.
- No sensitive data; code must be public; permissions (Private/Project/Link are temporary — apps must become Public eventually); public URL `*.serve.scilifelab.se`.
- Optional project **mount paths** for persistent storage (AnnotateR does not use them).

The service is beta and changes rapidly; re-check before each actual (re)deployment rather than relying on the summary above.

## Repository hosting

### GitHub repository rename

- **Renaming a repository:** https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository

GitHub redirects existing repository web traffic and old clone/fetch/push URLs after a repository rename, but local remotes should still be updated to the new URL. Do not later create a different repository at the old path, because that can break redirects.
