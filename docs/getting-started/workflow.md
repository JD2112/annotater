# The AnnotateR workflow

This page is the map the rest of the manual hangs on: what happens to
your files between **Upload** and **Download**, and which UI region
shows you each stage.

```text
   1. UPLOAD              2. PARSE + NORMALIZE          3. ANNOTATE             4. RESULT
 ┌──────────────┐      ┌─────────────────────────┐   ┌──────────────────┐   ┌──────────────────┐
 │ Query        │      │ detect format           │   │ interval         │   │ canonical result │
 │ coordinates  ├─────▶│ convert to the canonical├──▶│ operation on    ├──▶│ (coord_* /       │
 │ file         │      │ 0-based half-open model │   │ the chosen       │   │  annot_* rows,   │
 │              │      │ standardize chromosome  │   │ engine           │   │  has_overlap[,   │
 │ Annotation   │      │ IDs (if configured)     │   │ (Bedtools or     │   │  distance])      │
 │ features     │      │ apply the feature       │   │  Polars-Bio)     │   │                  │
 │ file         │      │ filter (GFF/GTF)        │   │                  │   │ display + export │
 └──────────────┘      └─────────────────────────┘   └──────────────────┘   └──────────────────┘
   "1. Upload"            previews below each        sidebar chooses       results section:
   section, both          uploader ("1. Upload")     stage 3; invalidates  metrics, Show filter,
   uploaders              the previews are the       stale results on      table, charts,
                          user-visible stage 2       every configuration   downloads
                                                      change
```

## Stage 1 — Upload (UI: "1. Upload")

You upload exactly two files: **Query coordinates** and **Annotation
features**. The accepted file extensions and size limits are documented
in [Uploading files](../using/uploading-files.md).

## Stage 2 — Parse and normalize (UI: the preview panels)

Each uploaded file is immediately:

1. **Detected** — the format is determined from the file (BED, GFF3,
   GTF, VCF, or custom table);
2. **Parsed** — intervals and metadata columns are extracted
   ([Supported file formats](../preparing-your-data/supported-formats.md));
3. **Normalized to the canonical model** — all coordinates become
   **0-based half-open** `[start, end)` intervals, regardless of the
   source format's convention ([Coordinate systems](../preparing-your-data/coordinate-systems.md));
4. **Chromosome-standardized** — if you configured conversion, both
   files' chromosome IDs are put in one naming style
   ([Chromosome identifiers](../preparing-your-data/chromosome-identifiers.md));
5. **Feature-filtered** — for GFF/GTF annotation files, only the
   selected feature types are kept ([Feature filtering](../using/feature-filtering.md)).

The preview panel under each uploader shows the first 10 rows of the
*normalized* table — what you see there is exactly what the annotation
engine will receive.

## Stage 3 — Annotate (UI: the sidebar)

The sidebar selects the execution of stage 3:

- **Annotation engine** — Bedtools or Polars-Bio
  ([Choosing an annotation engine](../using/engines.md));
- **Operation** — overlap, contains, within, or closest
  ([Choosing an operation](../operations/choosing-an-operation.md));
- **Join behavior** — keep all query rows (left) or matched rows only
  (inner) ([Join behavior: left vs inner](../operations/join-behavior.md));
- **Input options** — coordinate-system declaration (custom files),
  chromosome-ID handling;
- **Advanced options** — strand matching and the `min_overlap` slider
  (overlap mode only);
- **Feature filter** — which GFF/GTF feature types participate.

Pressing **Run annotation** executes the interval operation. Changing
any configuration option *invalidates* stored results: you never see a
stale table ([Running the annotation](../using/running.md)).

## Stage 4 — Result and export (UI: the results section)

The engine always produces the same **canonical result**: one row per
qualifying query/annotation pair (plus one row per unmatched query in
left-join mode), with `coord_*` and `annot_*` columns, `has_overlap`,
and — in closest mode — `distance`
([Result columns and provenance](../results/result-columns.md)).

From the results section you can filter what is displayed (which also
narrows the download), explore summary charts, and download CSV / TSV /
Excel / annotated VCF
([Downloading and exporting results](../results/export.md)).

## What does *not* happen

- No file ever leaves the app; no result is stored server-side.
- No silent engine fallback: if the selected engine is unavailable, the
  run fails with an explicit message
  ([Troubleshooting](../troubleshooting.md)).
- No guessing: malformed files, invalid intervals, and unrecognized
  coordinates fail with a message instead of producing a partial
  result.