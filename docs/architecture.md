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

### Normalization layer

Responsibilities:

- map chromosome identifiers where requested;
- convert coordinates to the canonical interval model;
- normalize core data types;
- validate interval invariants;
- preserve row identity when needed for left joins and duplicate-safe operations.

This is the semantic boundary shared by both engines.

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
