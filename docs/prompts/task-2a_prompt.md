You are working on **AnnotateR**, a Streamlit genomic-coordinate annotation application with Bedtools and Polars-Bio backends.

Implement **PLAN Task 2 only: Canonical schemas and backend-independent normalization**.

Task 1 has been completed and merged. Start from the current clean `main`.

At the beginning:

1. fetch/update `main`;
2. verify the working tree is clean;
3. create a dedicated Task 2 branch, preferably named:

`task-2-canonical-schemas`

Do not work directly on `main`.

---

# Mandatory reading before editing

Read in this order:

1. `AGENTS.md`
2. `SPEC.md`
3. `PLAN.md` — Task 2 only
4. `docs/architecture.md`
5. `docs/engine-contract.md`
6. `docs/references.md`
7. existing parsers, coordinate utilities, engine interfaces, tests, and Streamlit wiring relevant to parser/backend selection

Treat `SPEC.md` as normative.

Existing implementation is historical evidence, not automatically the desired contract.

For format semantics, consult the primary references linked in `docs/references.md`, especially:

* UCSC BED documentation;
* GFF3 specification;
* VCF specification;
* Bedtools documentation where interval behavior is relevant;
* current Polars-Bio documentation only where needed to understand existing coupling.

Do not rely on memory for coordinate-system rules.

---

# Current baseline

Task 1 established a reproducible test baseline.

The known baseline included:

* successful pytest collection from repository root;
* 22 tests collected;
* 21 passing;
* one pre-existing failure in `tests/test_core.py::TestParsers::test_bed_parser`, caused by the historical mixed-width BED fixture/parser behavior.

That failure was directly reproduced on the Task 1 parent commit.

Task 2 MAY resolve that failure if the correct fix naturally follows from the canonical parsing/normalization contract.

Do not modify a test merely to turn the suite green without establishing the intended semantics.

---

# Goal

Introduce explicit, backend-independent canonical input and result schemas so that the **same source genomic input is normalized identically regardless of whether Bedtools or Polars-Bio is selected later**.

Task 2 establishes the representation and normalization contract.

It does **not** yet make all Bedtools and Polars-Bio annotation outputs identical. Differential engine parity belongs to Task 3 and implementation parity to Task 4+.

---

# Architectural target

The intended flow is conceptually:

```text
source file / uploaded dataframe
        ↓
format-specific parser
        ↓
format-specific coordinate conversion
        ↓
canonical normalized interval dataframe
        ↓
annotation engine
   ┌───────────────┴────────────────┐
   │                                │
BedtoolsEngine                PolarsBioEngine
   │                                │
   └───────────────┬────────────────┘
                   ↓
       canonical result adapter
                   ↓
       deterministic public result
```

The important invariant is:

```text
parser / normalization
≠
backend selection
```

Choosing Polars-Bio MUST NOT cause AnnotateR to parse the same input using different scientific semantics than choosing Bedtools.

---

# Required work

## 1. Define the canonical interval dataframe contract

Implement and document one explicit internal interval representation consistent with `SPEC.md`.

At minimum the canonical interval model MUST define:

* chromosome as string;
* start as integer;
* end as integer;
* coordinates as **0-based, half-open**;
* valid interval requirement:

  * `start >= 0`
  * `end > start`
* optional strand representation;
* preservation of non-coordinate metadata;
* deterministic column handling.

Do not scatter these rules across multiple parsers.

Prefer one clearly identifiable normalization/schema boundary.

The exact implementation structure is your design decision, but it should be obvious to a future developer where the canonical interval contract lives.

Examples that may be appropriate include:

```text
core/schema.py
core/normalization.py
```

or equivalent focused modules.

Do not create abstractions solely for abstraction's sake.

---

## 2. Centralize format-to-canonical coordinate conversion

Establish explicit conversion rules for supported source formats.

### BED

BED is already 0-based / half-open and SHOULD enter the canonical model without an off-by-one transformation.

### GFF/GTF

GFF/GTF coordinates are 1-based inclusive.

Conversion to canonical intervals MUST therefore be explicit and boundary-tested.

For a source interval:

```text
start = S
end   = E
```

the canonical representation should reflect the documented coordinate semantics, not whichever behavior the existing parser happened to produce.

### VCF

VCF `POS` is 1-based.

Do not invent a simplistic generic conversion if the repository already supports variant span semantics involving `REF`, `END`, or equivalent information.

Inspect the existing implementation and current VCF specification before deciding the minimal correct Task 2 behavior.

If the project currently supports only a subset of VCF interval semantics, document that limitation instead of pretending to support every structural-variant case.

---

## 3. Preserve metadata provenance

Canonical normalization MUST preserve source metadata without making it ambiguous which fields are coordinates versus metadata.

The normalization layer SHOULD NOT silently discard arbitrary user/source fields merely because Bedtools or Polars-Bio does not need them for overlap calculation.

Avoid destructive renaming unless necessary.

If coordinate source columns require mapping to canonical names, preserve enough information to make later canonical output provenance deterministic.

Duplicate metadata column names or collisions with reserved canonical names must have an explicit behavior.

Do not solve backend suffix problems here with `_1`, `_2`, or `_right` heuristics.

---

## 4. Define the canonical annotation-result schema

Task 2 must make the canonical output contract explicit in code/tests/documentation even though full backend adaptation will be completed in later tasks.

Core required result columns are:

```text
coord_chr
coord_start
coord_end
annot_chr
annot_start
annot_end
has_overlap
```

Additional metadata must have deterministic provenance:

```text
coord_<original_name>
annot_<original_name>
```

Define at minimum:

* reserved/core columns;
* deterministic column ordering;
* metadata ordering;
* canonical missing-value representation;
* required type/behavior of `has_overlap`;
* deterministic row-order policy or a clear normalization rule that produces one;
* behavior with duplicate input rows.

External-library suffixes such as:

```text
_1
_2
_right
```

MUST NOT be part of the canonical public contract.

Do **not** rewrite every backend operation merely to enforce the result schema in Task 2.

Implement reusable schema/canonicalization machinery sufficient for later engine adapters and unit-test it independently.

---

## 5. Decouple parsing from backend selection

Inspect the current code paths where choosing Bedtools versus Polars-Bio changes parser behavior, for example historical patterns such as:

```python
parse(..., use_polars_bio=True)
```

Backend selection MUST NOT determine scientific parsing/coordinate normalization.

Refactor the core API so that the same source input is parsed and normalized the same way regardless of the chosen annotation engine.

Remove backend-specific parser branching where it is necessary to satisfy the Task 2 contract.

Do not redesign the Streamlit interface.

A small wiring change in the current application is acceptable if required to stop engine selection from changing parsing semantics, but UI/UX redesign and full Streamlit integration testing remain later tasks.

Do not optimize parsing with Polars-Bio in this task. Polars-Bio-native parsing is explicitly deferred.

---

## 6. Add focused normalization tests

Add small synthetic tests for the canonical normalization contract.

At minimum cover:

### Canonical interval validation

* valid ordinary interval;
* start = 0;
* invalid negative start;
* invalid zero-width interval;
* invalid end < start.

### BED boundaries

* simple BED interval remains unchanged;
* one-base BED interval:

```text
chr1  100  101
```

represents exactly one base.

### GFF/GTF boundaries

Include cases capable of detecting a one-base conversion error.

For example, a 1-based inclusive single-base source feature must become the corresponding one-base canonical half-open interval.

Tests should make the expected numeric values explicit.

### VCF boundaries

Add the smallest correct tests justified by the project's currently supported VCF semantics.

### Metadata

* arbitrary metadata survives normalization;
* coordinate fields are clearly separated from metadata;
* metadata ordering is deterministic.

### Engine independence

This is the central Task 2 acceptance test:

Given the **same source input**, normalization MUST produce the same canonical dataframe irrespective of later backend choice.

Ideally make backend choice absent from the parser/normalizer API entirely.

If the application wiring still passes an engine choice at a higher layer, explicitly test that it cannot alter normalized interval values/schema.

---

# Canonical dataframe testing

Use strict dataframe assertions where practical.

Tests should verify not only row counts but contractually relevant properties such as:

* values;
* column names;
* column order;
* row order where defined;
* relevant data types;
* missing values;
* duplicate preservation.

Do not use:

> same number of rows

as sufficient evidence.

---

# Existing parser failure

Investigate:

`tests/test_core.py::TestParsers::test_bed_parser`

in light of the new canonical parsing contract.

It is acceptable for Task 2 to fix this failure **only if** the change is the principled result of the canonical parser/normalization design.

Examples of unacceptable fixes:

* weakening the assertion;
* deleting malformed/mixed fixture lines merely to satisfy Pandas;
* adding broad `try/except` behavior that silently drops records;
* changing the fixture to something easier without explaining what behavior is actually supported.

If the historical test encodes invalid or ambiguous input that should instead fail explicitly, replace its expectation with a precise documented validation/error contract and justify that choice.

---

# Documentation

Update the relevant project documentation only where Task 2 establishes real contract details.

At minimum make sure the repository clearly records:

* canonical 0-based half-open internal coordinates;
* source-format conversion responsibilities;
* parser/backend independence;
* canonical result schema;
* missing-value convention;
* deterministic ordering policy.

Prefer updating:

* `docs/architecture.md`
* `docs/engine-contract.md`

and, if necessary, `SPEC.md` only when clarification is required and does not weaken existing normative requirements.

Do not casually rewrite the normative specification to match implementation convenience.

If you discover a genuine conflict between the current SPEC and authoritative external format documentation, stop and report it instead of silently changing either.

---

# Explicit non-goals / prohibitions

Do NOT in Task 2:

* build the Bedtools-vs-Polars-Bio differential parity harness planned for Task 3;
* change Polars-Bio overlap logic merely to make its current output match Bedtools;
* rewrite `PolarsBioEngine._join_overlap` for suffix handling;
* implement full left-join parity;
* implement/fix `contains`;
* implement/fix `within`;
* implement/fix `closest`;
* define final `min_overlap` semantics unless unavoidable for normalization;
* redesign the Streamlit UI;
* benchmark engines;
* broadly upgrade dependencies;
* optimize performance;
* use Polars-Bio-native parsing as an optimization;
* collapse duplicate genomic records;
* treat Bedtools formatting as the canonical public schema;
* add backend suffix heuristics to the canonical layer;
* silently catch parser/backend errors and turn them into empty dataframes.

If you encounter Task 3/4+ defects while working, record them as later-task findings and leave them untouched unless they prevent Task 2 acceptance criteria.

---

# Compatibility and migration discipline

This repository is an existing application, not a greenfield library.

Where practical, preserve current public call sites while moving normalization behind a better boundary.

If an existing parser API must change:

* update all repository call sites in the same task;
* add tests protecting the new contract;
* avoid temporary dual semantics where Bedtools and Polars-Bio paths normalize differently.

Do not preserve a bad backend-coupled API merely for backward compatibility if doing so violates the normative architecture.

---

# Task 2 acceptance criteria

You are done only when:

1. the canonical interval dataframe requirements are explicit in code and documentation;
2. supported source coordinate systems are converted explicitly to the canonical 0-based half-open model;
3. boundary tests detect one-base conversion errors;
4. source metadata is preserved deterministically;
5. canonical result columns, missing-value behavior, and deterministic ordering are explicitly defined;
6. parser/normalization behavior is independent of annotation backend choice;
7. the same source input normalizes identically regardless of selected engine;
8. no Task 3/4+ engine parity implementation has been smuggled into the diff;
9. the documented full test command runs and all newly introduced Task 2 tests pass;
10. any remaining pre-existing failure is precisely distinguished from new regressions.

---

# Git / commit / PR discipline

Use one Task 2 branch and keep the diff narrowly scoped.

Prefer a small number of logically separated commits, for example:

```text
test: define canonical interval normalization contract
refactor: centralize backend-independent interval normalization
docs: document canonical schemas and coordinate conversion
```

This is guidance, not a requirement to manufacture unnecessary commits.

Before completion:

* inspect the full diff against `origin/main`;
* ensure no unrelated formatting churn;
* ensure no Task 3/4 implementation slipped in.

If your normal project workflow creates a PR, create one only after the implementation and review loop is complete.

Do not merge until blocking review findings are resolved.

---

# Review loop

Use Pi subagents for independent review if available.

A reviewer must read:

* `SPEC.md`;
* `PLAN.md` Task 2;
* `AGENTS.md`;
* `docs/architecture.md`;
* `docs/engine-contract.md`;
* relevant external references.

The reviewer should inspect specifically for:

* off-by-one errors;
* BED/GFF/VCF coordinate-system mistakes;
* parser/backend coupling that remains;
* lost metadata;
* accidental duplicate collapsing;
* unstable column/row ordering;
* backend suffixes leaking into canonical schemas;
* output contract being defined from current Bedtools formatting rather than SPEC;
* Task 3/4 scope creep;
* tests that only compare row counts;
* overly permissive parsing that silently discards malformed data.

Classify review findings:

* BLOCKER
* MAJOR
* MINOR
* NOTE

Resolve all BLOCKER and MAJOR findings before finalizing.

If the `pi-subagents` extension is unavailable or broken, do not block the task solely for that reason. Perform a rigorous self-review and report the tooling limitation explicitly.

---

# Final verification

Before declaring completion:

1. re-read every Task 2 acceptance criterion;
2. inspect the full diff against the current Task 2 base;
3. run narrow normalization/parser tests;
4. run the documented full pytest command from repository root;
5. report exact collected/pass/fail/skip counts;
6. verify no engine parity code from Task 3/4 was implemented;
7. verify both engine choices consume or can consume the same canonical normalized input;
8. verify documentation agrees with implemented coordinate semantics.

---

# Final report

Return a concise but complete report containing:

* branch name;
* base commit;
* resulting commit(s);
* files changed;
* canonical interval schema implemented;
* exact BED/GFF/GTF/VCF conversion behavior;
* canonical result schema and ordering/missing-value policy;
* how parser/backend coupling was removed;
* tests added/modified;
* exact test commands and results;
* disposition of the historical `test_bed_parser` failure;
* reviewer findings and their resolution;
* Task 2 acceptance criteria status one by one;
* later-task findings intentionally left untouched;
* explicit confirmation that Task 3 and Task 4 were not started.

Do not begin Task 3.
