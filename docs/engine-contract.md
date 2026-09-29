# Annotation Engine Contract

**Applies to:** `BedtoolsEngine`, `PolarsBioEngine`, and future interval backends  
**Normative parent:** [`SPEC.md`](https://github.com/pyrevo/annotater/blob/main/SPEC.md)

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

## 9. Minimum overlap (fixed in Task 6A)

Bedtools distinguishes `-f` (fraction of A), `-F` (fraction of B), `-r`
(reciprocal), and `-e` (either side may satisfy). AnnotateR's single
`min_overlap` parameter is **normatively defined in SPEC 8.2** and is
none of those options by delegation:

> `min_overlap` is the minimum fraction of the canonical query
> interval covered by a single annotation interval for that
> query/annotation pair to qualify as a match.

```text
overlap_length = max(0, min(q_end, a_end) - max(q_start, a_start))
query_length   = q_end - q_start
qualifies iff  overlap_length > 0 AND overlap_length / query_length >= min_overlap
```

Query-relative (denominator is the query length), non-reciprocal, no
aggregation across annotation rows, inclusive threshold. Valid values:
`None` or a number in `[0, 1]` (int or float); anything else (out of
range, NaN, infinities, booleans, non-numeric) is rejected with
`ValueError` at engine construction, before any backend execution. In
left mode the threshold participates in match determination: a query
whose matches all fail the threshold appears exactly once, unmatched.

Implementation (Task 6A): the predicate lives at the contract level as
`streamlit_app/core/annotator.py::min_overlap_keep_mask` and is applied
as a **shared canonical post-filter** over ordinary backend overlap
pairs — after backend matching, before left-mode reconstruction — by
BOTH engines, so the meaning is identical by construction. The filter
applies in `overlap` mode only (SPEC 8.2 is defined for the overlap
method); `contains` (section 11) and `within` (section 11) have their
own interval-relation predicates (Task 6A review decision; the
`contains` exemption is pinned by a Task 6C regression test and the
`within` exemption by a Task 6D regression test). Bedtools
`-f` is NOT used for `min_overlap` (bedtools rejects `-f 0.0` — its
range is `(0.0, 1.0]` — and backend options must not define the
parameter), and no fraction flag is forwarded anywhere on the overlap
path. Pinned polars-bio 0.35.1 `overlap` exposes
no fraction mechanism, so the Polars-Bio engine enforces the same
shared predicate explicitly. The parameter is validated once in the
shared `AnnotationEngine` constructor via `validate_min_overlap`.

## 10. Strand options (fixed in Task 6B)

AnnotateR's `use_strand` has one normative, backend-independent meaning (SPEC 8.3):

- `use_strand=False`: strand does not participate in match qualification.
- `use_strand=True`: a matched pair qualifies only if BOTH rows carry an explicit canonical strand (`+` or `-`) and the strands are equal, in addition to the selected interval predicate qualifying.

Missing/unknown strand (canonical missing, or an absent strand column on either input) is NOT a wildcard and NOT a strand — no stranded match is possible for such a row, including unknown-vs-unknown. This is identical for both engines by construction: the predicate lives at the contract level as `streamlit_app/core/annotator.py::strand_keep_mask` and is applied as a **shared canonical post-filter** over ordinary backend overlap pairs — after backend matching, before left-mode reconstruction — by BOTH engines (the same architecture as the Task 6A `min_overlap` predicate).

- Bedtools does NOT use native `-s` for the overlap path: bedtools' stranded behavior (its undocumented treatment of `.` and its column-6 dependency) must not define the AnnotateR contract. Task 6E removed the native `-s` forwarding from the closest path as well: both engines now apply the shared strand predicate to the closest candidate set BEFORE nearest selection (SPEC 8.6).
- Pinned polars-bio 0.35.1 `overlap` exposes no strand option, so the shared predicate is applied post-hoc there as well.

In left mode, a query whose geometrical overlaps all fail the strand predicate appears exactly once, unmatched (SPEC 7.2); a query with at least one qualifying match emits only its qualifying matches. The predicate composes with `min_overlap` by logical AND (no precedence). Canonical strand values other than `+`/`-`/missing are rejected by `validate_canonical_interval_table`, which both engines invoke before any backend execution.

The predicate is deliberately **not** mode-gated (unlike the Task 6A `min_overlap` gate, which SPEC 8.2 limits to the overlap method): it therefore also applies to `contains` mode (SPEC 8.4) and `within` mode (SPEC 8.5), identically on both engines. (`contains` became normative in Task 6C; `within` became normative in Task 6D.)

## 11. Contains (fixed in Task 6C) and within (fixed in Task 6D)

`mode="contains"` means **the QUERY interval fully contains the
ANNOTATION interval** (SPEC 8.4):

```text
contains(Q, A) = q_start <= a_start AND q_end >= a_end
```

Directionality is fixed: the query is the containing interval and the
annotation is the contained interval. Equal intervals and shared
left/right boundaries qualify; partial overlaps, boundary-touching
(non-overlapping) intervals, and annotation-contains-query (the
`within` direction) do not.

`contains` is explicitly NOT `min_overlap = 1.0` (section 9 / SPEC
8.2): the two predicates are independent in both directions, and
`min_overlap` is not applied in contains mode.

Implementation (Task 6C): the predicate lives at the contract level as
`streamlit_app/core/annotator.py::contains_keep_mask` and is applied as
a **shared canonical post-filter** over ordinary backend overlap
candidate pairs — after backend matching, before left-mode
reconstruction — by BOTH engines, so the meaning is identical by
construction (the same architecture as the Task 6A `min_overlap` and
Task 6B `strand` predicates). Candidate generation is ordinary overlap,
never a Cartesian query x annotation product and never a
backend-native containment flag: a true containment pair necessarily
overlaps, so overlap candidates are lossless and the shared filter then
removes every non-qualifying row.

- Bedtools does NOT use `-f 1.0` (or any fraction flag) for `contains`.
  Bedtools `-f` is a fraction of A (the query) and is a different,
  version-coupled, backend-defined predicate, so it must not define the
  AnnotateR contract; the old `-f 1.0` placeholder mapping is removed.
- Pinned polars-bio 0.35.1 exposes no query-contains-annotation
  primitive (verified against the installed package), so the shared
  predicate is applied post-hoc there as well.

`use_strand` composes with `contains` by logical AND (section 10): a
contained pair must also satisfy the strand predicate under
`use_strand=True`, and missing/unknown strand is not a wildcard. In left
mode a query whose overlapping annotations all fail the containment or
strand predicate appears exactly once, unmatched (SPEC 7.2).

`mode="within"` means **the QUERY interval is fully contained within the
ANNOTATION interval** (SPEC 8.5):

```text
within(Q, A) = a_start <= q_start AND a_end >= q_end
```

Directionality is fixed and is the opposite of `contains`: the
annotation is the containing interval and the query is the contained
interval. Equal intervals and shared left/right boundaries qualify;
partial overlaps, boundary-touching intervals, and
query-contains-annotation (the `contains` direction) do not. The two
relations are directional inverses — `within(Q, A) == contains(A, Q)` —
and equality satisfies BOTH.

`within` is explicitly NOT `min_overlap` (section 9 / SPEC 8.2), and it
MUST NOT be inferred from an overlap percentage: `Q[10,20)` vs
`A[5,15)` has query fraction 0.5 (so `min_overlap=0.5` qualifies) while
`within` is false. `min_overlap` is not applied in within mode.

Implementation (Task 6D): the predicate lives at the contract level as
`streamlit_app/core/annotator.py::within_keep_mask` and is applied as a
**shared canonical post-filter** over ordinary backend overlap candidate
pairs — after backend matching, before left-mode reconstruction — by
BOTH engines, so the meaning is identical by construction (the same
architecture as the Task 6A `min_overlap`, Task 6B `strand`, and Task 6C
`contains` predicates). Candidate generation is ordinary overlap, never
a Cartesian query x annotation product and never a backend-native
containment flag: a true containment pair necessarily overlaps, so
overlap candidates are lossless and the shared filter then removes every
non-qualifying row.

- Bedtools does NOT use `-F 1.0` (or any fraction flag) for `within`.
  Bedtools `-F` is a minimum overlap as a fraction of B — in AnnotateR's
  orientation B is the annotation — so a native `-F 1.0` computes
  annotation-inside-query, i.e. the *`contains`* direction, with an
  inner-only join. That old placeholder mapping was removed, not
  preserved: a backend-defined fraction flag must not define an
  AnnotateR relation. The overlap path now forwards no `-f`/`-F`/`-r`/`-e`
  at all.
- Pinned polars-bio 0.35.1 exposes no containment primitive in either
  direction (verified against the installed package: only
  `overlap`/`nearest`/coverage/count operations exist), so the shared
  predicate is applied post-hoc there as well; the historical
  plain-overlap-plus-no-op behaviour is gone.

`use_strand` composes with `within` by logical AND (section 10): a
contained pair must also satisfy the strand predicate under
`use_strand=True`, and missing/unknown strand is not a wildcard. In left
mode a query whose overlapping annotations all fail the containment or
strand predicate appears exactly once, unmatched (SPEC 7.2).

## 12. Closest (fixed in Task 6E)

`closest` now has the one normative, backend-independent contract of
SPEC 8.6. Both engines implement it through the shared canonical
selection in `streamlit_app/core/annotator.py` (`interval_distance`,
`closest_matches`, `canonical_closest`); NEITHER engine calls a
backend-native closest/nearest operation (no pybedtools `BedTool.closest`,
no polars-bio `nearest`), so the selection, the ties, the ordering, and
the distance are identical by construction.

- **Distance.** `distance(Q, A) = max(0, a_start - q_end, q_start - a_end)`
  — the exact integer number of bases in the gap between the two
  0-based half-open intervals. Overlaps and touching (bookended) pairs
  are 0; a one-base gap is 1; a larger gap is the exact base count.
  Integer-only arithmetic (no floats); the shared helper
  `interval_distance` is the single definition.
- **Candidates.** Same-chromosome annotations only, per query. Under
  `use_strand=True`, SPEC 8.3 strand eligibility is applied to the
  candidate set BEFORE nearest selection (strand-before-nearest, not a
  post-filter on winners): missing/unknown strand never qualifies as a
  wildcard, and an ineligible nearer annotation cannot suppress a
  farther eligible one. `use_strand=False` ignores strand entirely.
- **Ties.** ALL tied-nearest annotations are returned per query (no
  arbitrary one-tie selection, no deduplication); row order is query
  input order, then annotation input order among the ties. Distance
  never breaks ties (it annotates the selected rows). Duplicate-valued
  annotations each produce their own rows.
- **No extra predicates.** `min_overlap` (SPEC 8.2), `contains` (8.4),
  and `within` (8.5) do NOT participate in closest mode.
- **`how="inner"`.** Zero rows for a query with no eligible candidate.
  **`how="left"`.** Every query appears exactly once; a query with no
  eligible candidate appears exactly once with `has_overlap=False`,
  canonical-missing `annot_*` fields and canonical-missing distance.
  In closest mode `has_overlap` means "an annotation was attached"
  (True for matched rows including separated ones, False for unmatched
  left rows) — it is not an overlap predicate (SPEC 7.2/8.6).
- **`distance` column.** The closest result carries one extra column,
  `distance`, with canonical nullable-integer (Int64) values: integer
  >= 0 for matched rows, `pd.NA` for unmatched left rows. It is the
  first extra column carried through the canonicalization layer.
- **Native distances are non-normative and never surface.** Bedtools
  2.31.1 `closest -d` reports gap + 1 for separated pairs (76 where the
  canonical gap is 75; 1 for touching pairs) and polars-bio 0.35.1
  `nearest.distance` reports the gap itself (75; 0 for overlapping and
  touching) — the Task 5 documented 76-vs-75 discrepancy. The canonical
  gap (75) is returned on both engines; the regression is pinned in
  `tests/parity/test_closest_parity.py` (including a direct assertion
  that the native bedtools value differs and never leaks).

Do not infer any of these from backend defaults: any implementation
that reproduces backend-native closest/nearest behavior instead of the
SPEC 8.6 definition is a defect.

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
