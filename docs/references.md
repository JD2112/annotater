# External References and Manuals

**Last checked:** 2026-09-21

This file is the reference index for version-sensitive implementation decisions. Prefer primary project documentation and specifications. Agents changing interval semantics MUST consult the relevant reference rather than relying on memory or inferred backend behavior.

## Genomic interval engines

### bedtools

- **bedtools documentation:** https://bedtools.readthedocs.io/
- **`intersect` manual:** https://bedtools.readthedocs.io/en/latest/content/tools/intersect.html
- **`closest` manual:** https://bedtools.readthedocs.io/en/latest/content/tools/closest.html

Implementation notes relevant to AnnotateR:

- `intersect -loj` is the reference behavior for retaining A records with and without B overlaps.
- `-f`, `-F`, `-r`, and `-e` have distinct fractional-overlap semantics; do not compress them into one application parameter without explicitly defining the mapping.
- `-s` enforces same-strand intersections.

### pybedtools

- **Documentation:** https://daler.github.io/pybedtools/
- **`BedTool.intersect` API:** https://daler.github.io/pybedtools/autodocs/pybedtools.bedtool.BedTool.intersect.html
- **GitHub:** https://github.com/daler/pybedtools

pybedtools is a Python wrapper around bedtools behavior. The external bedtools executable remains a system dependency and should be documented separately from Python requirements.

### Polars-Bio

- **Documentation home:** https://biodatageeks.org/polars-bio/
- **Quick start:** https://biodatageeks.org/polars-bio/quick-start/
- **Genomic operations API:** https://biodatageeks.org/polars-bio/api/operations/
- **Genomic operations guide:** https://biodatageeks.org/polars-bio/features/operations/
- **DataFrame support:** https://biodatageeks.org/polars-bio/features/dataframes/
- **GitHub:** https://github.com/biodatageeks/polars-bio

Important current-API observations:

- `overlap()` accepts explicit `cols1` and `cols2` interval columns.
- Current documented default suffixes are `("_1", "_2")`, not `_right`.
- `overlap_output="join"` returns joined overlapping pairs.
- `overlap_output="left"` returns df1 rows that overlap at least one df2 row; it is not, by itself, equivalent to bedtools `-loj` because non-overlapping df1 rows are absent.
- coordinate metadata can be used by Polars-Bio I/O paths, but AnnotateR must still own and test its canonical application coordinate semantics.

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

VCF POS is 1-based. Variant interval construction depends on REF/END semantics and must not be treated as a generic BED row without an explicit conversion rule.

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

- **Serve documentation:** https://serve.scilifelab.se/docs/
- Navigate from the documentation index to **Application hosting → Streamlit app hosting** for the current deployment procedure.

SciLifeLab Serve documentation identifies the service as beta and notes that functionality changes rapidly. Re-check deployment instructions during Task 8 rather than freezing today's assumptions into engine code.

## Repository hosting

### GitHub repository rename

- **Renaming a repository:** https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository

GitHub redirects existing repository web traffic and old clone/fetch/push URLs after a repository rename, but local remotes should still be updated to the new URL. Do not later create a different repository at the old path, because that can break redirects.
