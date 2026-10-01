# Feature filtering

The **Filter by feature type** multiselect (subheader "Feature filter")
limits which features of a **GFF/GTF annotation file** participate in
the annotation run.

## What it does — and when

- Applies **only to GFF3/GTF annotation files**, because only they
  carry a feature type column.
- **Applies when you press Run annotation, before matching** — the
  engine receives the filtered table. The annotation **preview shows the
  parsed table before filtering** (all features, with coordinates
  already converted to the canonical model), so it does not reflect this
  filter; after the run, a caption reports "Using N of M annotation
  features".
- **Default: `gene` only.** A first run therefore annotates against
  genes only, even if your annotation file contains exons, transcripts,
  and more.
- **A selection that matches nothing** (for example a file whose type
  names differ from the listed ones) stops the run with a warning that
  no annotations match the selected feature types.
- **Empty selection = all features.** Selecting no feature types shows
  the caption "No feature types selected — all features will be
  included" and the full annotation is used.

## Available feature types

`gene`, `transcript`, `exon`, `CDS`, `5' UTR`, `3' UTR`, `start_codon`,
`stop_codon`.

### The transcript choice

`transcript` is also a label: it accepts these exact, case-sensitive
feature types.

| Choice | Accepted feature types |
|---|---|
| `transcript` | `transcript`, `mRNA` |

`transcript` is the transcript record in GENCODE (GTF and GFF3) and
Ensembl annotations; `mRNA` is the transcript-level record in the GFF3
specification (and in GFF3 files from sources that follow it, such as
RefSeq). The original feature value (`transcript` or `mRNA`) is kept
unchanged in the results.

Only these two names are recognised. Other RNA feature types
(`lnc_RNA`, `ncRNA`, `rRNA`, `tRNA`, `miRNA`, `snRNA`, `snoRNA`,
`primary_transcript`, …) are distinct feature types and are **not**
matched by `transcript`; other Sequence Ontology transcript subtypes are
not normalised automatically. If your annotation uses them, leave the
filter empty to include all features.

### The 5' UTR and 3' UTR choices

These two choices are labels, not literal feature names. The filter is
still based on the annotation's feature-type column, and each choice
accepts these exact, case-sensitive values:

| Choice | Accepted feature types |
|---|---|
| `5' UTR` | `five_prime_UTR`, `five_prime_utr` |
| `3' UTR` | `three_prime_UTR`, `three_prime_utr` |

`five_prime_UTR` / `three_prime_UTR` are the GFF3 (Sequence Ontology)
terms; the lowercase spellings are the older GFF3 form. The original
feature value is kept unchanged in the results.

A generic `UTR` feature type (as in GENCODE GTF files) has no direction,
so it is **not** matched by either choice, and the position is not used
to guess one. Annotations that only use `UTR` therefore cannot be
selected with these choices (leave the filter empty to include all
features).

The filter matches the annotation file's `feature` column value
**exactly, case-sensitively**: a GFF3 file containing `gene` and `exon`
records, filtered to `gene`, keeps only the gene records. A file that
uses unusual type names (e.g. `mrna`, `lnc_RNA`, `match`) will have nothing
selected by the default filter — in that case, either unselect all
types (all features) or make sure the file uses the listed type names.

## How to read the effect

With the default `gene`-only filter, exons in your annotation are
simply not part of the run — queries overlapping only an exon (not the
gene record) will not match. Adding `exon` to the selection can
*increase* matches because more annotation intervals exist
([Example 1, Part B](../examples/bed-vs-gff3.md) shows the row-count
effect concretely).

If the filter leaves **no** annotation features at all, the run stops
with a warning: "No annotations match the selected feature types
(filtered N features). Adjust the feature filter and run again."

Feature filtering composes with everything downstream by simple
reduction: the operation, strand rule, and join all see only the
surviving features.

## Notes

- Filtering the *query* file is not a thing — the filter belongs to the
  annotation role. (There is no query-side type column in any supported
  format.)
- The filter does not rename or rewrite feature types; it is a
  membership test on the exact string, against the accepted values of
  each choice (see above).