# Annotation Engine Contract

**Applies to:** `BedtoolsEngine`, `PolarsBioEngine`, and future interval backends  
**Normative parent:** [`../SPEC.md`](../SPEC.md)

## 1. Interface

Each annotation engine implements the conceptual operation:

```python
intersect(coord_df, annot_df, how="inner") -> canonicalizable result
```

Engine inputs MUST represent the same canonical genomic intervals regardless of backend.

## 2. Required input fields

At minimum:

```text
chr    string
start  integer
end    integer
```

Optional fields include strand and arbitrary metadata. Engines MUST preserve enough field provenance to distinguish query metadata from annotation metadata after operations.

The canonical interval table contract (invariants, dtypes, reserved
names) is defined and validated in `streamlit_app/core/schema.py`
(`validate_canonical_interval_table`): 0-based half-open
`[start, end)`, `start >= 0`, `end > start`, `chr` present on every
row, strand restricted to `+`/`-` or missing, metadata columns
preserved in source order, and source columns using the reserved
`coord_`/`annot_` result prefixes rejected. The shared entry point
that produces such tables is
`streamlit_app/core/normalization.py::parse_and_normalize`, which takes
no backend/engine argument.

## 3. Canonical provenance

Given query columns:

```text
chr, start, end, query_name
```

and annotation columns:

```text
chr, start, end, feature, gene_id
```

a matched canonical result contains:

```text
coord_chr
coord_start
coord_end
coord_query_name
annot_chr
annot_start
annot_end
annot_feature
annot_gene_id
has_overlap
```

A backend-generated schema such as `chrom_1`, `chrom_2`, `start_right`, or bedtools positional fields is intermediate only.

This contract is enforced in code by
`streamlit_app/core/schema.py::canonicalize_annotation_result`: the
expected column set is exact, so leaked backend-suffixed columns are
rejected rather than renamed; `has_overlap` must be boolean; coordinate
dtypes are normalized; operation-specific columns (e.g. `distance`)
must be declared explicitly; and row order plus row multiplicity are
preserved as emitted by the engine.

## 4. Ordinary overlap

For canonical half-open intervals `A=[a_start,a_end)` and `B=[b_start,b_end)`, ordinary overlap exists when:

```text
max(a_start, b_start) < min(a_end, b_end)
```

Therefore intervals that merely touch at a boundary do not overlap.

Examples:

```text
A [10,20), B [15,25) -> overlap
A [10,20), B [19,20) -> overlap (1 bp)
A [10,20), B [20,25) -> no overlap
```

## 5. Inner mode

For `how="inner"`:

- output includes only matched query/annotation pairs;
- multiplicity is preserved;
- query row identity is preserved even for duplicate-valued rows;
- `has_overlap` is true for every returned row.

## 6. Left mode

For `how="left"`:

- every query row is represented;
- matched rows follow inner-mode multiplicity;
- each unmatched query row appears once;
- annotation fields are canonical missing values on unmatched rows;
- `has_overlap=False` on unmatched rows.

Bedtools `-loj` documents the desired conceptual behavior: all A features are emitted and unmatched A rows receive a null B record. Polars-Bio's documented `overlap_output="left"` is **not equivalent**, because it returns left rows that overlap; it does not itself emit non-overlapping query rows. Implementations MUST bridge this semantic difference explicitly.

## 7. Deterministic ordering

Until a more specialized rule is required, canonical results SHOULD sort stably by:

1. original query row identity;
2. original annotation row identity for matched rows;
3. unmatched row after/before matches only according to a single documented implementation rule.

Sorting by chromosome text alone is insufficient because lexical chromosome ordering can be surprising and duplicates lose identity.

## 8. Missing values

Canonical output SHOULD use dataframe-native missing values (`pd.NA`/nullable representation where practical) rather than bedtools sentinel strings/numbers.

Input-side VCF `.` values (FILTER = filters not applied, QUAL, ID, INFO, FORMAT/sample fields) are normalized to canonical missing at parse time; in particular FILTER `.` MUST NOT be rendered as `PASS` (see the VCF section of `docs/architecture.md`). In results, unmatched rows receive canonical missing in every `annot_*` field, while matched rows must carry a valid canonical annotation interval — malformed matched coordinates are rejected, never coerced to missing (which would fabricate a valid-looking row).

Conversion to textual sentinels belongs only in an export format that requires them.

As of Task 2 this is implemented at the canonical layer: on unmatched
rows every `annot_*` field (coordinates and metadata alike) is set to
`pd.NA` by `canonicalize_annotation_result`, so backend sentinels
(`.`, `-1`, ...) cannot reach public output.

## 9. Minimum-overlap options

Current bedtools documentation distinguishes:

- `-f`: minimum fraction of A;
- `-F`: minimum fraction of B;
- `-r`: reciprocal requirement;
- `-e`: either fraction may satisfy the condition.

AnnotateR's current single `min_overlap` parameter is therefore semantically ambiguous. Its exact meaning MUST be fixed in a dedicated task and tests before parity is claimed.

## 10. Strand options

Bedtools `-s` requires same-strand overlap. AnnotateR's `use_strand=True` SHOULD map to one explicit same-strand contract. Missing strand data MUST not be silently interpreted as a valid strand.

## 11. Contains / within

These operations require explicit predicates. A provisional mathematical definition for later confirmation is:

- query **within** annotation: `annot_start <= coord_start` and `coord_end <= annot_end`;
- query **contains** annotation: `coord_start <= annot_start` and `annot_end <= coord_end`.

Before implementation, verify that these definitions match UI wording and existing user expectations. Ordinary overlap followed by no filtering is NOT a valid implementation.

## 12. Closest

Closest requires a separate contract for:

- distance definition;
- whether overlaps have distance 0;
- upstream/downstream sign;
- ties;
- multiple nearest records;
- strand-aware behavior;
- left completeness.

Do not infer all of these from backend defaults.

## 13. Backend notes

### Bedtools / pybedtools

Use the official bedtools semantics as primary evidence; pybedtools wraps bedtools and therefore also requires the external bedtools executable.

### Polars-Bio

Use current documented function parameters. As of the documentation reviewed on 2026-09-21, `overlap()` defaults to suffixes `("_1", "_2")`, accepts explicit interval columns, and supports multiple output shapes. Code MUST NOT depend on an assumed `_right` suffix.

## 14. Contract-test pattern

Preferred structure:

```python
@pytest.mark.parametrize("engine_cls", [BedtoolsEngine, PolarsBioEngine])
def test_exact_overlap_contract(engine_cls):
    result = run_and_canonicalize(engine_cls, query, annotation)
    assert_frame_equal(result, expected)
```

Differential tests MAY additionally compare both engines directly, but expected-fixture tests remain important because two engines can agree on the same bug.

As of Task 3 this pattern is implemented by the parity harness in
`tests/parity/`:

- `comparator.py` provides `run_and_canonicalize` (engine → raw result →
  `canonicalize_annotation_result`) and `assert_canonical_equal` (strict
  comparison: exact canonical column set and order, row count, row order,
  NA-aware cell values, real booleans, contractually normative dtypes);
- `cases.py` / `fixtures.py` carry explicit per-case expected rows derived
  from the semantics above (never from backend output), with per-engine
  strict-xfail markers whose reasons name the exact root cause;
- `test_differential_parity.py` adds the direct engine-vs-engine layer;
- `test_backend_raw_diagnostics.py` attributes each known deviation to the
  exact layer (raw backend output vs canonical adapter) and records
  positive controls for layers that already conform.

The full current deviation inventory is in
`docs/implementation-notes.md` ("Task 3 — engine parity harness").
