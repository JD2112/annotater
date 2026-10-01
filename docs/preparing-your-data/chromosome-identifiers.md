# Chromosome identifiers (chr1 vs 1)

Genome references name chromosomes differently. AnnotateR converts
between exactly two styles, using a fixed mapping table:

| Style | Examples |
|---|---|
| **UCSC** | `chr1`, `chr2`, `chrX`, `chrM` |
| **Ensembl** | `1`, `2`, `X`, `MT` |

The mapping is `1–22, X, Y, MT` ⇄ `chr1–chr22, chrX, chrY, chrM`.
Nothing else is converted.

An interval on `chr1` and the same interval on `1` are the same
location — but as far as matching is concerned, **chromosome names are
compared as strings**. If your query says `chr1` and your annotation
says `1`, the two files share no chromosomes, and *nothing* will match
under any operation.

## Options in the sidebar: "Chromosome ID handling"

| Option | Behavior |
|---|---|
| **Auto-convert if needed** (default) | When the two files use *different* recognizable styles **that the converter can actually map (UCSC ⇄ Ensembl)**, AnnotateR standardizes **both files to UCSC style** when you press **Run annotation**. If the files already agree, nothing is converted; if no mapping exists (for example NCBI accession names), nothing is converted either and the app warns instead of claiming a conversion. The result shows the standardized names. |
| **Manual specification** | You pick a **Target style**: UCSC or Ensembl converts both files to that style where the mapping applies; *Keep original* converts nothing, and the app warns if the two styles differ. |

## What can and cannot be converted in v0.1.0

- **UCSC ⇄ Ensembl** — both directions are supported for the fixed
  mapping `1–22, X, Y, MT` ⇄ `chr1–chr22, chrX, chrY, chrM`. The style
  of a file is detected from up to its first 50 distinct chromosome
  identifiers.
- **NCBI accession names** (for example `NC_000001.11`) are
  *recognized* as a distinct style but are **never converted**, as a
  source or as a target. If one of your files uses accession names,
  rename it to UCSC or Ensembl names upstream.
- Any label outside the mapping table (for example unplaced or
  alternate contigs, or numbers above 22) is left **unchanged**, as are
  names that do not fit any known style. If the two files then
  disagree, rows on those chromosomes simply never match — there is no
  fuzzy matching and no per-chromosome warning.
- Support is limited to the UCSC/Ensembl labels in the table above;
  other organisms' chromosome names are converted only where they
  coincide with those labels.
- If, after any conversion, the query and annotation share **no**
  chromosome identifier, the app shows a warning that no shared
  chromosome identifiers remain between the two tables.

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
- The preview panels show the parsed table **before** chromosome
  conversion: chromosome names appear as they are in your files.
  Conversion is applied when you press **Run annotation** (an info
  message states that IDs were standardized), and the standardized
  names appear in the result table.