You are working on **AnnotateR**.

Tasks 1, 2, and 2.5 are complete and merged.

Implement **PLAN Task 3 only: systematic Bedtools ↔ Polars-Bio parity harness**.

The purpose of this task is to build an executable differential contract that precisely identifies where the two annotation engines agree and where Polars-Bio currently violates the AnnotateR specification.

Do **not** fix the Polars-Bio implementation in this task.

---

# Start state

Start from the current clean `main` after Task 2.5 has been merged and CI has passed.

Before editing:

1. `git fetch origin`
2. update local `main` with fast-forward only;
3. verify `main == origin/main`;
4. verify the working tree is clean;
5. create a dedicated branch:

`task-3-engine-parity-harness`

Do not work directly on `main`.

---

# Mandatory reading

Read in this order:

1. `AGENTS.md`
2. `SPEC.md`
3. `PLAN.md` — Task 3 only
4. `docs/architecture.md`
5. `docs/engine-contract.md`
6. `docs/references.md`
7. `docs/implementation-notes.md`
8. `streamlit_app/core/schema.py`
9. `streamlit_app/core/normalization.py`
10. `streamlit_app/core/annotator.py`
11. all existing engine-contract/parity tests, especially:

* `tests/test_engine_contract.py`
* relevant normalization/parser tests

Treat `SPEC.md` and `docs/engine-contract.md` as normative.

Existing engine behavior is evidence, not the contract.

Use the pinned environment established by Task 2.5:

* Python 3.12 tested/supported runtime;
* Bedtools 2.31.1;
* pybedtools 0.12.1;
* Polars 1.44.2;
* Polars-Bio 0.35.1.

For Polars-Bio behavior, verify against the documentation/release references corresponding to the pinned version rather than assuming latest documentation always applies.

---

# Context

Task 2.5 already created an initial engine-contract baseline and captured several known deviations as strict `xfail` tests.

Known issues include at least:

* Polars-Bio interpreting canonical 0-based half-open intervals incorrectly unless its coordinate-system behavior is explicitly configured;
* output column/suffix/provenance differences;
* row-id/backend-artifact leakage;
* Bedtools left-join sentinel behavior requiring canonicalization;
* exception swallowing / empty-result behavior.

Those existing tests are the seed of Task 3.

Task 3 must expand them into a systematic parity harness.

Do not remove or weaken known-failure tests merely because they expose current Polars-Bio defects.

---

# Primary goal

Given identical canonical query and annotation DataFrames:

```text
canonical query
canonical annotation
        │
        ├── BedtoolsEngine
        │
        └── PolarsBioEngine
```

the test harness must be able to determine whether both engines satisfy the same **AnnotateR semantic contract**.

Parity means semantic equivalence after canonical result normalization.

It does not mean:

* identical raw backend column names;
* identical backend row ordering before adaptation;
* identical temporary files;
* identical Bedtools/Polars-Bio internal representation.

The comparison target is AnnotateR's canonical result contract.

---

# Oracle strategy

Do not define correctness as:

> whatever Bedtools currently produces.

Use three layers of evidence:

1. **explicit expected fixtures** derived from `SPEC.md` / `docs/engine-contract.md`;
2. each backend independently compared against those expected results;
3. differential comparison between Bedtools and Polars-Bio.

This prevents two engines sharing the same bug from being considered correct merely because they agree.

Where a case has clear expected genomic semantics, encode those expected rows explicitly.

Bedtools may be treated as the reference implementation only where the contract and authoritative interval semantics agree with it.

---

# Required work

## 1. Build reusable parity-fixture infrastructure

Create a focused parity-test structure.

A suitable layout might be:

```text
tests/
    parity/
        __init__.py
        conftest.py
        fixtures.py
        test_overlap_parity.py
        test_left_parity.py
        test_boundary_parity.py
        test_metadata_parity.py
        ...
```

or an equivalent clean organization.

Do not split files mechanically if a smaller structure is clearer.

Fixtures should use tiny in-memory canonical DataFrames wherever possible.

Avoid large external genomic files for fundamental contract tests.

Every fixture should be easy for a human reviewer to reason about.

---

## 2. Define a strict canonical result comparator

Implement test utilities that compare semantically relevant canonical outputs.

Comparison must consider at minimum:

* exact row set;
* row multiplicity;
* canonical columns;
* canonical column order where normative;
* values;
* missing values;
* `has_overlap`;
* metadata provenance;
* relevant dtypes;
* deterministic result ordering after canonical normalization.

Do not compare only:

* row counts;
* unordered coordinate sets if duplicates matter;
* stringified DataFrames.

Do not hide unexpected backend columns.

Backend-specific artifacts must either be removed by the canonical adapter or cause a contract failure where appropriate.

---

# 3. Systematically test inner-overlap semantics

Cover at minimum:

### Basic overlap

* exact same interval;
* partial overlap at left;
* partial overlap at right;
* annotation fully inside query;
* query fully inside annotation.

### Non-overlap

* different chromosomes;
* gap of one or more bases;
* directly touching half-open intervals:

```text
query:      [10,20)
annotation: [20,25)
```

Expected: **no overlap**.

This case is especially important because Task 2.5 already identified a Polars-Bio coordinate-system deviation.

### One-base intervals

Examples such as:

```text
[10,11)
[10,11)
```

and adjacent single-base intervals.

### Multiple hits

* one query → two annotations;
* one annotation → two queries;
* many-to-many case with explicitly enumerable expected rows.

### Duplicate input rows

* duplicate queries;
* duplicate annotations;
* duplicate query + duplicate annotation.

Multiplicity must be preserved.

Do not silently deduplicate.

---

# 4. Test left-join semantics

AnnotateR's left mode must preserve every query row.

Test at minimum:

* matching query;
* non-matching query;
* mixture of matched and unmatched queries;
* one query with multiple annotation hits;
* duplicate unmatched query rows;
* all queries unmatched;
* empty annotation DataFrame if supported by contract;
* empty query DataFrame if supported by contract.

For unmatched rows verify canonical behavior explicitly:

* query metadata preserved;
* `has_overlap == False`;
* annotation canonical fields missing;
* annotation metadata missing;
* exactly one unmatched result row per unmatched query input row.

Do not accept Bedtools `.` / `-1` sentinels as canonical output.

Do not treat Polars-Bio's `overlap_output="left"` as equivalent to AnnotateR left semantics without testing it. Task 2.5 already documented that they are not automatically the same concept.

---

# 5. Test boundary semantics exhaustively

Add compact fixtures for off-by-one behavior.

At minimum test:

```text
A [0,1)
B [0,1)       overlap

A [0,1)
B [1,2)       no overlap

A [9,10)
B [10,11)     no overlap

A [9,11)
B [10,11)     overlap
```

Include chromosome zero/start-zero cases where relevant.

Expected outcomes must be explicit and independent of backend behavior.

These tests must make an accidental conversion to 1-based closed semantics immediately visible.

---

# 6. Test metadata provenance

Use query and annotation DataFrames containing extra fields, including potentially colliding names such as:

```text
query:
    feature
    score
    id

annotation:
    feature
    score
    id
```

Verify canonical output provenance:

```text
coord_feature
coord_score
coord_id

annot_feature
annot_score
annot_id
```

Also test:

* arbitrary string metadata;
* numeric metadata;
* missing metadata values;
* boolean metadata where supported;
* metadata ordering;
* input columns already beginning with `coord_` or `annot_`, according to the Task 2 reserved-name policy.

No `_1`, `_2`, `_right`, `pb_row_id`, or equivalent backend artifacts may leak into a passing canonical result.

---

# 7. Test deterministic row behavior

The engine contract defines deterministic result ordering.

Create fixtures where backend-native ordering could plausibly differ.

Expected canonical ordering should follow the normative project rule established in Task 2, including query input identity/order and annotation order within query where defined.

Test duplicate rows explicitly so ordering is not accidentally inferred from coordinate values alone.

If current adapters cannot yet enforce the normative order, capture the deviation as a strict xfail rather than modifying the engines in Task 3.

---

# 8. Exercise supported overlap options without implementing fixes

Inspect `SPEC.md`, `PLAN.md`, and `docs/engine-contract.md` for the supported operation surface.

For semantics that belong to later implementation tasks, add contract cases where the expected behavior is already normative.

Potential areas include:

* `min_overlap`;
* strand-aware overlap;
* `contains`;
* `within`;
* closest/nearest.

However, respect Task 3 scope:

* establish executable expected behavior;
* identify current deviations;
* do not repair implementation.

If some operation is intentionally scheduled for a later dedicated task and its semantics are not sufficiently specified yet, document the gap rather than inventing behavior.

Prioritize overlap and left semantics first.

---

# 9. Handle known failures with strict xfail only

A parity test may be marked:

```python
pytest.mark.xfail(strict=True, reason="...")
```

only when:

1. the expected behavior is clearly established by the project contract;
2. current implementation is known to violate it;
3. the reason identifies the actual deviation;
4. the reason references the relevant SPEC/engine-contract requirement where practical.

Never use xfail because:

* the expected behavior is unclear;
* a test is flaky;
* the fixture is inconvenient;
* a backend raises an unexplained exception.

If an existing xfail now unexpectedly passes, investigate why.

Because all xfails are strict, an XPASS must fail CI until the marker is reviewed.

---

# 10. Distinguish backend defect from adapter defect

When a test fails, determine which layer produces the mismatch:

```text
canonical input
    ↓
backend call
    ↓
raw backend result
    ↓
AnnotateR adapter/canonicalizer
    ↓
canonical output
```

Record enough diagnostic information in the test or failure message to identify whether a deviation originates from:

* incorrect backend invocation/configuration;
* backend-native semantics;
* result-column mapping;
* missing left reconstruction;
* metadata loss;
* row ordering;
* canonicalization.

Do not fix it in Task 3.

Create a concise deviation inventory for Task 4.

---

# 11. Test backend failure behavior

The engine contract must not silently convert genuine backend errors into plausible empty biological results.

Add targeted tests where safe and deterministic for:

* invalid engine mode;
* malformed backend input if applicable;
* backend invocation/configuration error.

If current implementation swallows an exception and returns an empty DataFrame, encode the normative expected behavior and mark the current deviation strict-xfail.

Do not deliberately depend on random external failures.

---

# 12. Keep tests version-robust

The parity harness must test **AnnotateR semantics**, not incidental textual representation from a particular Bedtools or Polars-Bio release.

Avoid assertions on:

* complete exception message strings from third-party libraries;
* backend temporary filenames;
* internal DataFusion plan representation;
* undocumented column ordering before adaptation.

Assert only externally relevant behavior and the AnnotateR canonical contract.

---

# Test matrix

At completion, produce a compact documented matrix covering at least:

| Area     | Case        | Bedtools | Polars-Bio | Expected contract   | Status     |
| -------- | ----------- | -------- | ---------- | ------------------- | ---------- |
| overlap  | exact       | ...      | ...        | match               | PASS/XFAIL |
| overlap  | touching    | ...      | ...        | no match            | ...        |
| overlap  | one-to-many | ...      | ...        | 2 rows              | ...        |
| left     | unmatched   | ...      | ...        | preserved once      | ...        |
| metadata | collisions  | ...      | ...        | provenance prefixes | ...        |
| ordering | duplicates  | ...      | ...        | deterministic       | ...        |

Do not manually maintain redundant truth if it can be generated from tests, but provide a useful human-readable summary in the Task 3 report or implementation notes.

---

# Existing Task 2.5 contract tests

Do not simply duplicate `tests/test_engine_contract.py`.

Either:

* migrate/refactor those cases cleanly into the systematic Task 3 harness while preserving git-readable intent;

or

* retain them as smoke-level contract tests and build the deeper parity suite alongside them.

Choose the cleaner approach.

Do not lose any of the five currently documented known deviations.

---

# Explicit non-goals / prohibitions

Do NOT in Task 3:

* set the Polars-Bio zero-based coordinate option as a production fix;
* rewrite `PolarsBioEngine._join_overlap`;
* fix suffix mapping;
* reconstruct left joins in implementation;
* remove backend sentinel values by changing engine code;
* fix exception swallowing;
* implement/fix contains/within/closest engine behavior;
* redesign parser logic;
* change canonical schema semantics from Task 2;
* redesign the Streamlit UI;
* optimize performance;
* benchmark Bedtools versus Polars-Bio;
* change dependency pins unless required to repair a broken test environment;
* weaken or delete a correct failing parity test simply to obtain a green suite.

This task is diagnostic/test infrastructure.

Task 4 is where current Polars-Bio deviations are fixed.

---

# Documentation

Update the appropriate documentation with:

* parity-testing strategy;
* oracle strategy;
* current deviation inventory;
* distinction between backend equivalence and raw output identity;
* explanation of strict xfail policy.

Prefer focused updates to:

* `docs/engine-contract.md`
* `docs/implementation-notes.md`
* tests themselves

Do not bloat `SPEC.md` unless a genuine normative ambiguity is discovered.

If you discover an ambiguity or contradiction in the SPEC, stop and report it instead of silently choosing whichever behavior makes a test pass.

---

# Review loop

Use independent Pi subagents if available.

Have at least one reviewer focus specifically on genomic interval semantics and ask:

* Are any expected results derived circularly from Bedtools output?
* Are half-open boundaries correct?
* Are duplicates/multiplicity preserved?
* Does any test accidentally compare only counts?
* Are left unmatched semantics precise?
* Are metadata collisions covered?
* Are strict xfails justified?

Have another reviewer, if practical, focus on test quality:

* fixture independence;
* false positives;
* overly broad xfails;
* implementation-aware assertions;
* backend-specific assumptions;
* missing negative cases.

Classify findings:

* BLOCKER
* MAJOR
* MINOR
* NOTE

Resolve all BLOCKER and MAJOR findings before finalizing.

Do not let reviewers implement Task 4 fixes.

---

# Acceptance criteria

Task 3 is complete only when:

1. a systematic parity harness exists for both engines;
2. explicit expected fixtures act as the primary semantic oracle;
3. both engines are independently testable against the same contract;
4. differential comparison exists in addition to expected-result comparison;
5. half-open boundary behavior is thoroughly covered;
6. one-base and touching-interval behavior is covered;
7. one-to-many, many-to-many, and no-match behavior is covered;
8. left semantics are covered;
9. duplicate/multiplicity behavior is covered;
10. metadata provenance and name collisions are covered;
11. deterministic canonical ordering is tested;
12. backend artifacts cannot silently leak into passing canonical results;
13. genuine current deviations are represented as justified `xfail(strict=True)`;
14. an XPASS fails the suite;
15. no current known deviation from Task 2.5 was lost;
16. backend errors are not treated as valid empty biological results by the contract;
17. a concise deviation inventory exists for Task 4;
18. the full test suite has no unexpected FAIL or XPASS;
19. no Task 4 production fix was implemented.

---

# Final verification

Before declaring completion:

1. inspect the complete diff against `origin/main`;
2. verify no production engine implementation was changed;
3. run the focused parity suite;
4. run the complete pytest suite at least twice;
5. report exact:

   * PASS
   * XFAIL
   * XPASS
   * FAIL
   * SKIP
6. verify every xfail is `strict=True`;
7. review each xfail reason manually;
8. confirm every expected fixture can be understood without inspecting backend output;
9. confirm no third-party temporary/internal representation is treated as normative;
10. inspect the Task 4 deviation inventory for completeness.

---

# Git discipline

Keep Task 3 on its own branch.

Prefer logical commits such as:

```text
test: add explicit genomic parity fixtures
test: expand Bedtools and Polars-Bio contract matrix
docs: record engine parity deviations
```

but do not manufacture commits unnecessarily.

Create the PR only after review findings are resolved.

Do not merge automatically unless that is the established repository workflow.

---

# Final report

Return:

* branch;
* base commit;
* commits;
* files changed;
* parity harness architecture;
* complete fixture/case inventory;
* oracle strategy;
* exact Bedtools PASS/XFAIL status;
* exact Polars-Bio PASS/XFAIL status;
* all current deviations grouped by root cause;
* which deviations were already known from Task 2.5;
* new deviations discovered;
* exact focused-test counts;
* exact full-suite PASS/XFAIL/XPASS/FAIL/SKIP counts;
* reviewer findings and resolutions;
* Task 3 acceptance criteria status one by one;
* concise Task 4 implementation backlog derived from failing contract cases;
* explicit confirmation that no Task 4 production fix was implemented.

Do not begin Task 4.
