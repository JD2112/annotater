# Uploading files

## The two uploaders

The **"1. Upload"** section holds exactly two uploaders:

- **Query coordinates** — accepts `.bed`, `.txt`, `.tsv`, `.csv`, `.vcf`
- **Annotation features** — accepts `.gtf`, `.gff`, `.gff3`, `.bed`,
  `.txt`, `.tsv`, `.csv` (no `.vcf` — VCF is a query-only input in
  v0.1.0)

You need both files before a run is possible.

![The upload section with both example files uploaded and their previews
visible](../assets/screenshots/upload.png)

*S1 — the "1. Upload" section with the two bundled example files
uploaded; the preview panels show detected format, row count, and the
first rows.*

## File limits

| Constraint | Value |
|---|---|
| Maximum file size | **200 MB per file** |
| Maximum number of files | **2** (one per role) |
| Acceptance | determined by **file extension** (the formats are documented in [Supported file formats](../preparing-your-data/supported-formats.md)) |

A file that exceeds the size limit or has an unrecognized extension is
rejected by the uploader with an error message.

## What happens after you choose a file

Immediately (no button to press):

1. the file is parsed and **normalized** — you see the first 10 rows of
   the *normalized* table under the uploader, with the detected format
   and row count;
2. any configuration change later (feature filter, coordinate-system
   declaration, chromosome handling) **re-parses** affected files and
   invalidates stored results — see
   [Running the annotation](running.md).

The preview is your contract: what the engine will receive is exactly
the table shown there.

## Replacing a file

Choosing a different file for an uploader replaces the previous one
and re-runs parsing. There is no multi-file list and no queue.

## Custom tables (CSV/TSV) — column mapping and coordinate declaration

For a file AnnotateR cannot recognize as a standard format, the preview
panel asks you to **map columns** (which column is chromosome, start,
end, and optionally strand/name/score). You must **apply the mapping**
before the file can be used. The same panel is where you **declare the
coordinate system** for the file (0-based half-open — the default — or
1-based inclusive). See
[Supported file formats → CSV/TSV and custom tables](../preparing-your-data/supported-formats.md)
and [Coordinate systems](../preparing-your-data/coordinate-systems.md).

## Upload errors you can expect

| Symptom | Usually means |
|---|---|
| Uploader rejects the file before parsing | wrong extension, or file > 200 MB |
| "File is empty" (no data rows) | header-only file, or all rows were comments/blank |
| Parsing error with a line number | malformed row — see the format-specific "Common errors" in [Supported file formats](../preparing-your-data/supported-formats.md) |
| Preview looks wrong (off-by-one everywhere) | wrong **coordinate-system declaration** for a custom table, or pre-adjusted source coordinates |
| Preview shows unexpected chromosome names | check the **Chromosome ID handling** option |

Full diagnosis: [Troubleshooting](../troubleshooting.md).