# AnnotateR

**AnnotateR** is a free web application that maps genomic coordinates to
gene features. Upload your genomic coordinates and annotate them against
gene annotation files, gaining insights into genomic regions of interest
directly in the browser.

- **File formats:** BED · GFF3 · GTF · VCF · CSV/TSV (custom tables)
- **Operations:** overlap, minimum overlap, contains, within, closest —
  with optional strand-aware matching
- **Backends:** Bedtools (command-line) and Polars-Bio (dataframe),
  interchangeable and producing the same canonical result
- **Runs locally or as a deployed service** — your files never leave the
  app; nothing is stored on any server

## Where to start

- **New here?** Read [What is AnnotateR?](getting-started/what-is-annotater.md)
  and then the [Quick start](getting-started/quick-start.md).
- **Running it locally?** Developers should follow
  [QUICKSTART.md](https://github.com/JD2112/annotater/blob/main/assets/QUICKSTART.md)
  in the repository.

## The three topics users land on most

| You want to… | Go to |
|---|---|
| Know which files you can upload | [Supported file formats](preparing-your-data/supported-formats.md) |
| Pick the right annotation operation | [Choosing an operation](operations/choosing-an-operation.md) |
| Read the result table | [Understanding the results page](results/results-page.md) |

## Example

The repository ships tiny example files you can use to try the app:

- [`data/examples/example_coordinates.bed`](https://github.com/JD2112/annotater/blob/main/data/examples/example_coordinates.bed)
  (query regions) and
  [`data/examples/example_annotations.gff3`](https://github.com/JD2112/annotater/blob/main/data/examples/example_annotations.gff3)
  (gene/exon annotations).

See the [Examples](examples/bed-vs-gff3.md) section for five complete,
deterministic walkthroughs.

## Documentation

This site is the complete user manual for the AnnotateR v0.1.0 release.
Technical and developer material (architecture, engine contract,
benchmark, deployment) lives in the
[Technical Reference](technical/scientific-contract.md) section and in
the [repository](https://github.com/JD2112/annotater).