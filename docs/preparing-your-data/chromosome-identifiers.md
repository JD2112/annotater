# Chromosome identifiers (chr1 vs 1)

Genome references name chromosomes differently. The two common styles
AnnotateR can convert between are:

| Style | Examples |
|---|---|
| **UCSC** | `chr1`, `chr2`, `chrX`, `chrM` |
| **Ensembl** | `1`, `2`, `X`, `MT` |

An interval on `chr1` and the same interval on `1` are the same
location — but as far as matching is concerned, **chromosome names are
compared as strings**. If your query says `chr1` and your annotation
says `1`, the two files share no chromosomes, and *nothing* will match
under any operation.

## Options in the sidebar: "Chromosome ID handling"

| Option | Behavior |
|---|---|
| **Auto-convert if needed** (default) | When the two files use *different* recognizable styles **that the converter can actually map (UCSC ⇄ Ensembl)**, AnnotateR standardizes **both files to UCSC style** before matching. If the files already agree, nothing is converted; if no mapping exists (for example NCBI accession names), nothing is converted either and the app warns instead of claiming a conversion. The preview panels and the result show the standardized names. |
| **Manual specification** | You pick a **Target style** — UCSC, Ensembl, or *Keep original* — and both files are converted to it (or left as-is). |

## What can and cannot be converted in v0.1.0

- **UCSC ⇄ Ensembl** — both directions supported for standard
  chromosome names (autosomes, sex chromosomes, the MT/M mapping).
- **NCBI accession names** (for example `NC_000001.11`) are
  *recognized* as a distinct style but are **not a convertible target
  in v0.1.0**. If one of your files uses accession names, rename it to
  UCSC or Ensembl names upstream.
- Names that do not fit any known style pass through unchanged. If the
  two files then disagree, rows on those chromosomes simply never match
  — there is no fuzzy matching and no warning per chromosome.

## What a mismatch looks like

A chromosome mismatch is the most common cause of "I definitely
expected matches and got none":

- With **left join** you see all your query rows, all unmatched
  (see [Troubleshooting → zero matches](../troubleshooting.md#zero-matches)).
- With **inner join** you see an empty result.

The fix is almost always to re-run with **Auto-convert if needed** or
with a manual target style — not to rename anything in your files.

## Notes

- Conversion is applied identically on both engines; it happens before
  the interval operation, so it does not change which operation
  semantics apply.
- The preview panels show the chromosome names *after* conversion, so
  you can verify the standardization before running.