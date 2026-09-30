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

**VCF is a query-only input in v0.1.0** — variants are things you
annotate, not a feature catalog you annotate against. Everything else
can play either role.

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

- **Common errors:** a header line in a `.bed` file (BED has no header;
  comment lines must start with `#`); tab-delimited, not
  comma-delimited, fields; `end <= start`.

## GFF3

- **Role:** query or annotation (typically annotation).
- **Required fields:** `seqid`, `start`, `end` (columns 1–2–5); the
  `type` column becomes the `feature` column.
- **Optional fields:** `source`, `score`, `frame`; **attributes** in
  column 9. The attribute keys `ID`, `Name`, `gene_id`, `gene_name`,
  `transcript_id`, `gene_type`, `gene_biotype`, and `Parent` are
  extracted as dedicated columns; the full raw attribute string is also
  preserved.
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

- **Common errors:** spaces instead of tabs; `end < start`; a
  `gene_id` you expect in results that is actually spelled differently
  in the attribute column (extraction is key-exact).

## GTF

- **Role:** query or annotation (typically annotation).
- **Required fields:** `seqid`, `source`, `feature` (type), `start`,
  `end`, `strand`, `frame`.
- **Optional fields:** the quote-delimited `attributes` field; the same
  keys as GFF3 are extracted (`gene_id`, `gene_name`, `transcript_id`,
  `gene_type`, …).
- **Coordinate convention:** 1-based inclusive — converted like GFF3.
- **Strand:** column 7.
- **Tiny valid example:**

  ```text
  chr1    example    gene    1001    2500    +    .    gene_id "G1"; gene_name "GENE1";
  ```

- **Common errors:** unbalanced quotes in the attribute field;
  `frame` not present (GTF requires it, `.` is fine).

## VCF

- **Role:** **query only** in v0.1.0.
- **Required fields:** `CHROM`, `POS`, `REF`, `ALT` (the VCF header
  must declare the columns; `#CHROM` lines are required).
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

- **Common errors:** missing `#CHROM` header (the column layout cannot
  be established); sample columns declared but missing on a record
  (records must carry exactly the fields the header declares);
  `INFO/END` smaller than `POS`.

## CSV/TSV and custom tables

- **Role:** query or annotation.
- **Required fields:** you choose — any columns you map as
  chromosome, start, and end
  ([Uploading files → custom column mapping](../using/uploading-files.md)).
- **Coordinate convention:** there is no format to fix it, so **you
  declare it** in the sidebar ("Query coordinates" / "Annotation
  coordinates"): 0-based or 1-based. Default is **0-based half-open**.
- **Strand:** any mapped strand column, or missing.
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