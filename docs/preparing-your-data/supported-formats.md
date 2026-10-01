# Supported file formats (BED, GFF3, GTF, VCF, CSV/TSV)

AnnotateR understands five input formats: **BED**, **GFF3**, **GTF**,
**VCF**, and **custom tables** (CSV/TSV with column mapping). The
complete, authoritative specifications live in the
[External references](../references.md) page — this page documents only
what AnnotateR requires, normalizes, and preserves from each format.

## Which formats can play which role?

The two uploaders accept different extensions:

| Uploader | Accepted extensions | Notes |
|---|---|---|
| **Query coordinates** | `.bed` `.txt` `.tsv` `.csv` `.vcf` | VCF is accepted here |
| **Annotation features** | `.gtf` `.gff` `.gff3` `.bed` `.txt` `.tsv` `.csv` | no `.vcf` |

**Roles are fixed by the uploader, not only by the format:**

- **VCF is a query-only input in v0.1.0** — variants are things you
  annotate, not a feature catalog you annotate against.
- **GFF3 and GTF are annotation-only inputs.** The query uploader does
  not accept `.gff`, `.gff3` or `.gtf` files. To use features from a
  GFF3/GTF file as query intervals, convert them to BED (or a custom
  CSV/TSV table) first.
- **BED and custom CSV/TSV tables can play either role.**

## BED

- **Role:** query or annotation.
- **Required fields:** `chrom`, `start`, `end` (columns 1–3).
- **Optional fields:** `name` (col 4), `score` (col 5), `strand` (col
  6); further columns are preserved as metadata.
- **Coordinate convention:** 0-based half-open — **no conversion** is
  performed ([Coordinate systems](coordinate-systems.md)).
- **Strand:** column 6, kept verbatim as `+` / `-`; anything else
  (including `.` or an empty value) is treated as missing strand.
- **Metadata preservation:** columns 4+ become `coord_name`,
  `coord_score`, `coord_strand` plus one metadata column per extra
  input column, in input order
  ([Result columns and provenance](../results/result-columns.md)).
- **Tiny valid example:**

  ```text
  chr1    1000    2500    region1    0    +
  chr2    50000   50100   .          .    .
  ```

- **Comment lines:** blank lines and lines starting with `#` are
  skipped. UCSC `track` and `browser` lines are **not supported**: they
  are not skipped, and a `track` line stops parsing with an error naming
  the line (for example "line 1: expected at least 3 tab-separated
  fields"). Remove them before uploading.
- **Common errors:** a header line or a `track`/`browser` line in a
  `.bed` file (BED has no header; comment lines must start with `#`);
  tab-delimited, not comma-delimited, fields; `end <= start`.

## GFF3

- **Role:** annotation only (the query uploader does not accept GFF3).
- **Required fields:** `seqid`, `type`, `start`, `end` (columns 1, 3,
  4, 5); the `type` column becomes the `feature` column.
- **Standard layout:** nine tab-delimited columns — `seqid`,
  `source`, `type`, `start`, `end`, `score`, `strand`, `frame`,
  `attributes`; `source`, `score`, and `frame` (the GFF3 phase
  column) may be `.`. The attribute keys `ID`, `Name`, `gene_id`,
  `gene_name`, `transcript_id`, `gene_type`, `gene_biotype`, and
  `Parent` are extracted from column 9 as dedicated columns; the
  full raw attribute string is also preserved.
- **Coordinate convention:** 1-based inclusive — AnnotateR converts at
  parse time: `start := start − 1`, `end` unchanged
  ([Coordinate systems](coordinate-systems.md)).
- **Strand:** column 7; `.` (or anything other than `+`/`-`) is
  missing strand.
- **Tiny valid example:**

  ```text
  ##gff-version 3
  chr1    example    gene    1001    2500    .    +    .    ID=gene:G1;gene_id=G1
  chr1    example    exon    1051    1200    .    +    .    Parent=gene:G1
  ```

- **Comment handling and `#` in attributes:** lines starting with `#`
  (including `##` directives) are skipped, but the parser treats **any
  `#` character as the start of a comment**, so a `#` inside the
  attributes column truncates the rest of that line — for example
  `Note=C#2;Name=X` is read as `Note=C`. AnnotateR does not implement
  full GFF3 lexical handling; percent-encode (`%23`) or remove `#`
  characters in attribute values before uploading.
- **Common errors:** spaces instead of tabs; `end < start`; a
  `gene_id` you expect in results that is actually spelled differently
  in the attribute column (extraction is key-exact); a literal `#` in
  an attribute value.

## GTF

- **Role:** annotation only (the query uploader does not accept GTF).
- **Required fields:** all nine tab-delimited columns — `seqid`,
  `source`, `feature` (type), `start`, `end`, `score`, `strand`,
  `frame`, `attributes`; `score` and `frame` may be `.`. The same
  keys as GFF3 are extracted from column 9 (`gene_id`, `gene_name`,
  `transcript_id`, `gene_type`, …), using the GTF quoted
  `key "value";` syntax.
- **Coordinate convention:** 1-based inclusive — converted like GFF3.
- **Comments:** the same `#` handling as GFF3 applies (any `#` starts a
  comment, so it also truncates attribute values).
- **Strand:** column 7.
- **Tiny valid example:**

  ```text
  chr1    example    gene    1001    2500    .    +    .    gene_id "G1"; gene_name "GENE1";
  ```

- **Common errors:** unbalanced quotes in the attribute field;
  `frame` not present (GTF requires it, `.` is fine).

## VCF

- **Role:** **query only** in v0.1.0.
- **Required fields:** the eight fixed tab-separated fields `CHROM`,
  `POS`, `ID`, `REF`, `ALT`, `QUAL`, `FILTER`, `INFO` on every record.
  The `#CHROM` header line is required when records carry `FORMAT` and
  sample columns: it declares them, and records with extra fields but no
  `#CHROM` line are rejected. When a `#CHROM` line is present, every
  record must have exactly the number of fields it declares.
- **Optional fields:** `ID`, `QUAL`, `FILTER`, `INFO`, and
  `FORMAT`/sample columns — all are preserved as metadata.
- **Coordinate convention:** `POS` is 1-based and points at the
  **first base of the reference interval**. AnnotateR converts the
  variant to the canonical interval occupied by its reference sequence:
  `start = POS − 1`, `end = POS + span − 1` where `span` comes from
  `INFO/END` if present, otherwise from the length of `REF` (at least
  1)
  ([Coordinate systems](coordinate-systems.md)).
  So a simple substitution `POS=100, REF=A` becomes `[99, 100)`; a 4-bp
  reference `POS=100, REF=ACGT` becomes `[99, 103)`.
- **Strand:** VCF carries no strand. VCF query rows have **missing
  strand** — with strand matching enabled they can never form a
  stranded match ([Strand information](strand-information.md)).
- **Metadata preservation:** `ID`, `REF`, `ALT`, `QUAL`, `FILTER`,
  `INFO` and one column per declared sample become `coord_*` metadata
  columns; VCF `.` values become canonical missing.
- **Tiny valid example:**

  ```text
  ##fileformat=VCFv4.2
  #CHROM  POS  ID   REF  ALT  QUAL  FILTER  INFO
  chr1    1200 v1   A    T    .     .      .
  ```

- **Original header lines:** the `##` metadata lines before `#CHROM`
  are retained so the Annotated VCF export can carry them forward
  ([Downloading and exporting results](../results/export.md)).
- **Common errors:** records with `FORMAT`/sample fields but no
  `#CHROM` header (the column layout cannot be established); sample
  columns declared but missing on a record (records must carry exactly
  the fields the header declares); `INFO/END` smaller than `POS`.

## CSV/TSV and custom tables

- **Role:** query or annotation. The two roles are handled differently:
  - **Custom query table:** you map columns explicitly in the
    "Map coordinate columns" panel: *chromosome*, *start*, and an
    optional *end* (choose "None (single positions)" for point data).
    Every unmapped column is preserved as query metadata and appears in
    results with the `coord_` prefix, in original column order. A
    column named `strand` among the unmapped columns is kept as query
    metadata and can take part in strand-aware annotation. Two roles
    cannot share one source column, and an unmapped column literally
    named `chr`, `start` or `end` is refused with a mapping error.
  - **Custom annotation table:** no mapping panel is shown. The table
    must already contain the canonical columns `chr`, `start` and
    `end`; the preview states this. Other columns are preserved as
    annotation metadata (`annot_*`).
- **Coordinate convention:** there is no format to fix it, so **you
  declare it** in the sidebar ("Query coordinates" / "Annotation
  coordinates"): 0-based or 1-based. Default is **0-based half-open**.
  The declaration is applied exactly once. For a custom query it is
  applied when you press "Apply column mapping"; for a custom
  annotation table when it is parsed.
- **Single positions (custom query, no end column):** a position is
  exactly one base in the declared system. A 1-based position `P` is
  the base `[P−1, P)` in canonical coordinates; a 0-based position `P`
  is `[P, P+1)`.
- **Strand:** a `strand` metadata column, or missing.
- **Tiny valid example (TSV, 1-based declared):**

  ```text
  chrom	start	end	name
  1	100	250	regionA
  2	50	60	regionB
  ```

- **Common errors:** declaring the wrong coordinate system (off-by-one
  everywhere — see [Troubleshooting](../troubleshooting.md));
  wrong delimiter; forgetting to apply the column mapping before
  running.

## Where the full specifications live

AnnotateR never reproduces the format specifications; the authoritative
external documents (UCSC BED, GFF3, GTF, VCF) are listed in
[External references](../references.md).