# AnnotateR Architecture

**Status:** target architecture for the Polars-Bio parity refactor  
**Last updated:** 2026-09-21

## 1. Current problem

AnnotateR already has the right high-level abstraction: an `AnnotationEngine` with Bedtools and Polars-Bio implementations. However, backend choice currently affects more than interval execution. Parsing paths, backend-native schemas, output renaming, left-join behavior, and incomplete operation implementations are mixed together.

That makes a simple question — “do both engines produce the same annotation?” — difficult to answer because multiple transformations differ at once.

## 2. Target data flow

```text
uploaded/source file
        |
        v
+--------------------+
| format parser      |
| BED/GFF/GTF/VCF... |
+--------------------+
        |
        v
+-------------------------+
| normalization           |
| - chromosome IDs        |
| - coordinate convention |
| - dtypes/validation     |
| - metadata provenance   |
+-------------------------+
        |
        v
 canonical query/annotation DataFrames
        |
        +---------------------+
        |                     |
        v                     v
+------------------+   +------------------+
| BedtoolsEngine   |   | PolarsBioEngine |
+------------------+   +------------------+
        |                     |
        +----------+----------+
                   |
                   v
        backend-native result
                   |
                   v
+--------------------------------+
| canonical result adapter       |
| coord_* / annot_* / overlap    |
| missing values / ordering      |
+--------------------------------+
                   |
                   v
+--------------------------------+
| Streamlit presentation/export  |
+--------------------------------+
```

## 3. Boundaries

### Parser layer

Responsibilities:

- read a declared/supported file format;
- retain source metadata;
- identify source coordinate convention;
- report malformed input.

The parser layer MUST NOT decide which annotation backend will run.

The implemented parsers (`streamlit_app/core/parsers.py`) are explicit
and line-oriented, and emit **source-level** coordinates; conversion to
the canonical model happens in the normalization layer:

- **BED** — line-based, variable-width (3 to 12+ columns). Optional
  fields (`name`, `score`, `strand`) are missing per row where absent.
  Structurally invalid lines raise `MalformedFileError` with the
  offending physical line number; records are never silently dropped.
- **GFF/GTF** — fixed 9-column TSV layout; attributes parsed from the
  attribute column.
- **VCF** — the first eight tab-separated fields (CHROM POS ID REF ALT
  QUAL FILTER INFO) are parsed as text, which is complete per the VCF
  specification because tabs inside INFO values are escaped. Each
  variant becomes the interval occupied by its reference sequence,
  `[POS, POS + max(1, len(REF)) - 1]`, or `[POS, END]` (both 1-based
  inclusive) when `INFO/END` is present. Source metadata is preserved:
  the raw INFO field is kept as an `info` metadata column (VCF `.` →
  canonical missing), and when the `#CHROM` header declares `FORMAT` and
  sample columns, `format` plus one column per sample (named from the
  header, in source order) are kept with `.` → canonical missing; FORMAT
  sub-fields are not expanded. `FILTER` distinguishes the three spec
  meanings — `PASS`, a semicolon-separated failed-filter list, and
  MISSING (`.` = filters not applied → canonical missing, never
  converted to `PASS`). A sample name colliding with a parser/core
  column is renamed to `sample_<name>`; duplicate sample IDs and
  header/record field-count mismatches fail explicitly.

VCF parsing deliberately has no external VCF-library dependency: the
pinned pysam build in this environment does not expose `INFO/END`
through its record API, and an explicit parser keeps the coordinate
conversion deterministic and version-independent.

### Normalization layer

Responsibilities:

- map chromosome identifiers where requested;
- convert coordinates to the canonical interval model;
- normalize core data types;
- validate interval invariants;
- preserve row identity when needed for left joins and duplicate-safe operations.

This is the semantic boundary shared by both engines.

The implemented boundary is `streamlit_app/core/normalization.py`.
`parse_and_normalize` is the single entry point through which every
backend's source files enter canonical space, and it takes **no
backend/engine argument by design**. Per-format coordinate systems are
fixed by `FORMAT_COORDINATE_SYSTEMS` (BED: 0-based; GFF/GTF: 1-based;
VCF: 1-based); a user-declared system applies only to custom tables
after explicit column mapping (default 0-based, the historical
effective behavior). `normalize_intervals` enforces the invariants in
`core/schema.py` and returns deterministic column order:
`chr, start, end, [strand], <metadata in source order>`.

### Engine layer

Responsibilities:

- perform interval operations;
- respect requested operation options;
- return enough provenance to reconstruct canonical results;
- propagate execution failures rather than disguising them as empty valid results.

The engine layer MAY use backend-native dataframe representations internally.

### Result adapter

Responsibilities:

- map backend-native output into the public contract;
- preserve query/annotation provenance;
- normalize missing values;
- add `has_overlap` where applicable;
- enforce deterministic column and row ordering.

Backend-specific suffix conventions belong here or inside the backend implementation, never in UI code.

The contract machinery lives in `streamlit_app/core/schema.py`.
`canonicalize_annotation_result` enforces the exact canonical column
set, boolean `has_overlap`, integer coordinate dtypes, canonical
missing (`pd.NA`) in every `annot_*` field of unmatched rows, and the
deterministic column order. Malformed query intervals (any row) and
malformed matched annotation coordinates — non-numeric or non-integer
coordinates, missing annotation chromosome, zero-width or reversed
intervals — are rejected with `CanonicalSchemaError` rather than coerced
to missing, which would fabricate a valid-looking row. The
`coord_`/`annot_` prefixes are
reserved — source metadata may not use them — and any backend-suffixed
leakage (`_1`, `_2`, `_right`) is rejected because the expected column
set is exact. Operation-specific additions (e.g. `distance` for closest
mode) must be explicitly declared; anything undeclared is rejected.
Row order is preserved exactly as the engine emits it; duplicated rows
are never collapsed. Task 4/5 implements the per-engine adapters that
map backend output into this contract.

### UI/export layer

Responsibilities:

- collect user inputs/options;
- select an engine;
- display/export canonical results;
- report actionable errors.

The UI MUST NOT contain backend-specific scientific semantics.

## 4. Coordinate model

The target internal interval convention is 0-based, half-open `[start, end)`. Format-specific conversion belongs before backend execution. This model is compatible with BED/bedtools conventions and makes one-base boundary behavior explicit.

Because Polars-Bio can carry coordinate-system metadata when using its own I/O, direct DataFrame paths MUST NOT assume that automatic detection will fix unnormalized application DataFrames. AnnotateR owns its canonical coordinate contract.

Implemented per-format conversion (Task 2):

| Source  | Source convention        | Canonical conversion |
|---------|--------------------------|----------------------|
| BED     | 0-based half-open        | unchanged            |
| GFF/GTF | 1-based inclusive        | `start := start - 1`; `end` unchanged |
| VCF     | `POS` 1-based            | span `[POS, POS + max(1, len(REF)) - 1]`, or `[POS, END]` when `INFO/END` is present (1-based inclusive), then `start := start - 1` |

VCF span limitation (Task 2): the occupied interval is derived from REF
length or `INFO/END` only. Broader structural-variant interpretation
(e.g. ALT-only complex events) is intentionally not performed; variants
are represented by the interval their reference sequence occupies.

## 5. Row identity

Stable row identity is required whenever value equality is insufficient, especially:

- duplicated query rows;
- duplicated annotation rows;
- reconstruction of unmatched queries in left mode;
- deterministic sorting after backend execution.

Temporary row IDs MAY be added internally and MUST NOT leak into public output unless explicitly documented.

## 6. Error model

There is an important distinction between:

- a valid annotation run with zero overlaps;
- invalid input;
- unsupported requested semantics;
- backend execution failure;
- missing system dependency.

These states MUST NOT all collapse to an empty DataFrame.

## 7. Testing layers

```text
unit tests
  parser / normalization / coordinate boundaries
        |
        v
engine contract tests
  same operation semantics for each backend
        |
        v
parity tests
  Bedtools canonical result == Polars-Bio canonical result
        |
        v
Streamlit integration tests
  engine selection does not change scientific result
```

Large benchmark datasets are not substitutes for the minimal edge-case fixtures needed to catch semantic errors.

## 8. Deployment boundary

SciLifeLab Serve is a deployment target, not part of interval semantics. Container/deployment configuration should consume the tested application rather than influence how coordinates are interpreted.

See `docs/references.md` for current Serve and Streamlit documentation.
