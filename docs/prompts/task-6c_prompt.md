You are working on **AnnotateR**.

Tasks 1–5, Task 6A (`min_overlap`), and Task 6B (`use_strand`) are complete and merged.

Implement **Task 6C only: `contains` semantics**.

Do not implement `within` or final `closest/nearest` semantics in this PR.

The purpose of Task 6C is to define, document, test, and implement one backend-independent meaning for AnnotateR's existing `contains` operation.

---

# Start state

Start from the current clean `main` after Task 6B has been merged and CI has passed.

Before editing:

1. `git fetch origin`
2. fast-forward local `main`
3. verify `main == origin/main`
4. verify working tree clean
5. create:

`task-6c-contains-semantics`

Do not work directly on `main`.

---

# Mandatory reading

Read in this order:

1. `AGENTS.md`
2. `SPEC.md`
3. `PLAN.md` — Task 6
4. `docs/architecture.md`
5. `docs/engine-contract.md`
6. `docs/references.md`
7. `docs/implementation-notes.md`
8. `streamlit_app/core/annotator.py`
9. `streamlit_app/core/schema.py`
10. complete `tests/parity/`
11. Task 6A min-overlap tests
12. Task 6B strand tests
13. focused Bedtools and Polars-Bio engine tests

Consult pinned/version-matched primary documentation for Bedtools and Polars-Bio interval-containment-related behavior.

Do not rely on backend option names as semantic truth.

---

# Normative definition

For canonical half-open intervals:

```text
Query Q      = [q_start, q_end)
Annotation A = [a_start, a_end)
```

AnnotateR `contains` SHALL mean:

> **the query interval fully contains the annotation interval**

Formally:

```text
contains(Q, A) =
    q_start <= a_start
    AND
    q_end >= a_end
```

Because canonical intervals are valid and non-empty, no additional positive-overlap condition is required: full containment already implies overlap.

Boundary equality counts as containment.

---

# Directionality is critical

These examples define the contract.

## Query larger than annotation

```text
Q = [10,30)
A = [15,20)
```

`contains=True`

---

## Equal intervals

```text
Q = [10,20)
A = [10,20)
```

`contains=True`

Equality satisfies containment.

---

## Same start, query extends farther

```text
Q = [10,30)
A = [10,20)
```

`contains=True`

---

## Same end, query starts earlier

```text
Q = [5,20)
A = [10,20)
```

`contains=True`

---

## Annotation contains query

```text
Q = [15,20)
A = [10,30)
```

`contains=False`

This case belongs to `within`, not `contains`.

---

## Partial overlap only

```text
Q = [10,20)
A = [15,25)
```

`contains=False`

Even though the intervals overlap.

---

## Touching only

```text
Q = [10,20)
A = [20,25)
```

`contains=False`

---

# Do not implement contains as overlap fraction

This distinction is important.

Example:

```text
Q = [10,20)
A = [10,15)
```

The query contains the annotation.

But:

```text
overlap_length / query_length = 5 / 10 = 0.5
```

Therefore `contains` is NOT equivalent to:

```text
min_overlap = 1.0
```

because Task 6A's denominator is the query.

Conversely:

```text
Q = [10,20)
A = [0,100)
```

Task 6A:

```text
min_overlap=1.0 → match
```

because the entire query is covered.

But:

```text
contains → false
```

because the query does not contain the annotation.

Add regression tests proving both distinctions.

---

# Architecture

`contains` is an AnnotateR semantic predicate.

Prefer a shared canonical predicate applied to candidate interval pairs rather than relying on backend-specific containment flags.

Conceptually:

```text
canonical inputs
      ↓
backend candidate interval pairs
      ↓
contains_keep_mask()
      ↓
strand filter if enabled
      ↓
left reconstruction
      ↓
canonical output
```

Exact implementation order between independent pair-level predicates may differ if logically equivalent, but the resulting semantics must be identical.

---

# Shared predicate

Prefer one engine-neutral helper such as:

```text
contains_keep_mask(...)
```

or an appropriately generalized interval-predicate helper.

It must use canonical coordinates only.

Do not duplicate containment inequalities independently inside BedtoolsEngine and PolarsBioEngine.

---

# Relationship with `mode`

Inspect the existing public API carefully.

If current modes include:

```text
overlap
contains
within
closest
```

then Task 6C should make `mode="contains"` normative.

Do not change how callers select modes unless necessary.

Invalid modes should continue to follow the existing validation/error contract.

---

# Relationship with `min_overlap`

For `mode="contains"`, `min_overlap` SHALL NOT redefine containment.

Task 6A deliberately scoped `min_overlap` to ordinary overlap mode.

Preserve that rule.

Therefore:

```text
mode="contains"
```

uses the containment predicate only, plus orthogonal filters such as strand where normative.

Do not additionally require query overlap fraction to satisfy `min_overlap`.

If current API permits supplying both `mode="contains"` and `min_overlap`, preserve the documented Task 6A behavior that `min_overlap` is not applied outside overlap mode.

Pin this with a regression test.

---

# Relationship with strand

Task 6B strand semantics ARE orthogonal and normative.

Therefore with:

```text
mode="contains"
use_strand=True
```

a pair qualifies iff:

```text
contains(Q, A)
AND
same_explicit_strand(Q, A)
```

Examples:

```text
Q [10,30) "+"
A [15,20) "+"
→ match
```

```text
Q [10,30) "+"
A [15,20) "-"
→ no match
```

```text
Q [10,30) missing
A [15,20) missing
→ no match when use_strand=True
```

Do not delegate missing-strand behavior to backend-native containment operations.

---

# Inner semantics

For:

```text
how="inner"
mode="contains"
```

emit one result row for every query/annotation pair satisfying the containment predicate and all orthogonal normative filters.

No qualifying pairs:

```text
→ zero rows
```

Preserve multiplicity.

---

# Left semantics

For:

```text
how="left"
mode="contains"
```

all query rows must survive.

For each query:

* one qualifying annotation → one matched row;
* multiple qualifying annotations → one row per qualifying annotation;
* zero qualifying annotations → exactly one unmatched query row;
* partial-overlap-but-not-contained annotations do not count as matches;
* annotations that contain the query do not count as matches.

Canonical unmatched rows:

```text
has_overlap = False
annotation fields = pd.NA
```

Although the public column remains named `has_overlap`, in a non-overlap mode it represents whether the selected annotation relation produced a qualifying match.

Do not rename the canonical column in this task unless SPEC already requires something else.

---

# Required fixtures

Build explicit expected-result fixtures independent of either backend.

At minimum include:

## 1. Strict containment

```text
Q [10,30)
A [15,20)
```

match.

---

## 2. Exact equality

```text
Q [10,20)
A [10,20)
```

match.

---

## 3. Shared left boundary

```text
Q [10,30)
A [10,20)
```

match.

---

## 4. Shared right boundary

```text
Q [5,20)
A [10,20)
```

match.

---

## 5. Annotation contains query

```text
Q [15,20)
A [10,30)
```

no match.

---

## 6. Partial right overlap

```text
Q [10,20)
A [15,25)
```

no match.

---

## 7. Partial left overlap

```text
Q [10,20)
A [5,15)
```

no match.

---

## 8. Touching right

```text
Q [10,20)
A [20,25)
```

no match.

---

## 9. Touching left

```text
Q [10,20)
A [5,10)
```

no match.

---

## 10. Different chromosome

Never match.

---

## 11. Multiple contained annotations

```text
Q [0,100)

A [10,20)
B [30,40)
C [90,100)
```

all three qualify.

Preserve annotation input order.

---

## 12. Mixed contained and partial

Only genuinely contained annotations qualify.

---

## 13. Duplicate queries

Preserve query identity and multiplicity.

---

## 14. Duplicate annotations

Preserve annotation multiplicity.

---

## 15. Left no qualifying matches

Query has overlapping annotations but none are fully contained.

Expected exactly one unmatched query row.

---

## 16. Left mixed

One contained + one partial annotation.

Emit only contained match.

No unmatched row.

---

## 17. Contains vs min_overlap=1 asymmetry A

```text
Q [10,20)
A [0,100)
```

`overlap + min_overlap=1.0` qualifies.

`contains` does not.

---

## 18. Contains vs min_overlap=1 asymmetry B

```text
Q [0,100)
A [10,20)
```

`contains` qualifies.

`overlap + min_overlap=1.0` does not.

---

## 19. Same strand

Contained pair + same strand passes with `use_strand=True`.

---

## 20. Opposite strand

Contained pair + opposite strand fails with `use_strand=True`.

---

## 21. Missing strand

Contained pair + missing strand fails in stranded mode.

---

## 22. Metadata preservation

Contained matches preserve all coord/annot metadata exactly.

---

# Backend strategy

## Bedtools

Existing placeholder behavior may currently approximate containment with:

```text
-f 1.0
```

or related flags.

Do NOT preserve it merely because it exists.

Determine exactly what that flag means relative to the A/B direction in the current Bedtools invocation.

Remember:

* Bedtools' `-f` refers to one side;
* `-F` refers to the other side;
* AnnotateR's query/annotation direction must remain explicit.

If native Bedtools containment is proven exactly equivalent to:

```text
q_start <= a_start
AND
q_end >= a_end
```

it may be used.

However, a shared canonical containment filter over ordinary candidate overlaps is likely simpler and safer.

Do not use `-f 1.0` if it actually expresses “annotation contains query” or query coverage rather than query contains annotation.

---

# Polars-Bio

Inspect pinned Polars-Bio 0.35.1 capabilities.

Do not infer meaning from function names alone.

If no exact query-contains-annotation primitive exists, use ordinary candidate overlaps + the shared canonical predicate.

Keep:

* coordinate-system metadata behavior from Task 4;
* exception propagation;
* deterministic ordering;
* row identity.

---

# Candidate-generation principle

A true containment pair necessarily overlaps.

Therefore ordinary interval overlap can safely generate candidate pairs, followed by canonical containment filtering.

Do not generate all Cartesian query × annotation pairs.

Preferred pattern:

```text
backend ordinary overlap
        ↓
contains predicate
```

This keeps performance reasonable while preserving backend-independent semantics.

---

# Empty inputs

Test:

* empty query;
* empty annotation;
* both empty.

For inner contains:

```text
empty query → empty result
empty annotation → empty result
```

For left contains:

```text
empty query → empty result
non-empty query + empty annotation
→ one unmatched row per query
```

Reuse established left reconstruction behavior.

---

# Ordering

Contains filtering removes non-qualifying candidate rows only.

Canonical order remains:

```text
query input order
→ annotation input order
```

Do not order by:

* interval length;
* containment depth;
* genomic coordinate;
* strand.

---

# Metadata and helper columns

Do not alter Task 4/5 provenance behavior.

No backend/helper artifacts may leak:

```text
pb_row_id
query row IDs
annotation row IDs
Bedtools temporary columns
suffix artifacts
```

Metadata preservation must remain exact according to the existing canonical contract.

---

# Documentation changes

Task 6C resolves the currently non-normative `contains` placeholder.

Update at minimum:

* `SPEC.md`
* `docs/engine-contract.md`
* `docs/implementation-notes.md`
* `PLAN.md`

Document explicitly:

> `contains` means the query interval fully contains the annotation interval.

Include the formal predicate:

```text
q_start <= a_start
AND
q_end >= a_end
```

Also document:

* equality allowed;
* directionality;
* distinction from `within`;
* distinction from `min_overlap=1`;
* strand composes via logical AND;
* left reconstruction rules.

Remove stale language calling `contains` a placeholder/non-normative mode after this task.

Do not make `within` normative yet.

---

# UI

Do not redesign the UI.

If `contains` is already selectable, retain the same surface.

Update help/copy only if it currently states the wrong direction or ambiguous wording.

Preferred user-facing wording:

> Query contains annotation

or:

> Return annotations fully contained within each query interval.

Do not use ambiguous wording like simply:

> containment mode

if a tiny clarification fits naturally.

---

# Explicit non-goals

Do NOT implement:

* `within`;
* closest/nearest final semantics;
* reciprocal containment;
* containment percentage;
* annotation-fraction thresholds;
* new min-overlap behavior outside overlap mode;
* opposite-strand modes;
* UI redesign;
* parser changes;
* coordinate-system changes;
* dependency upgrades;
* performance optimization.

Do not start Task 6D.

---

# Review loop

Use two independent Pi subagent reviewers if available.

## Reviewer 1 — genomic semantics

Ask specifically:

* Is directionality query contains annotation everywhere?
* Are equal intervals contained?
* Are shared-boundary cases correct?
* Do partial overlaps fail?
* Is annotation-contains-query correctly rejected?
* Is contains distinct from min_overlap=1?
* Are left semantics correct?
* Does strand compose correctly?

## Reviewer 2 — implementation/test quality

Ask specifically:

* Is there one shared containment predicate?
* Are backend-specific fraction flags avoided or proven equivalent?
* Are candidates generated efficiently via overlap rather than Cartesian product?
* Are duplicates/order/metadata preserved?
* Are empty inputs correct?
* Is `within` still untouched/non-normative?
* Are stale placeholder docs removed?

Resolve all BLOCKER and MAJOR findings.

---

# Acceptance criteria

Task 6C is complete only when:

1. `contains` is explicitly defined as query contains annotation;
2. formal predicate is `q_start <= a_start && q_end >= a_end`;
3. equal intervals qualify;
4. shared-left-boundary containment qualifies;
5. shared-right-boundary containment qualifies;
6. annotation-contains-query does not qualify;
7. partial overlaps do not qualify;
8. touching intervals do not qualify;
9. chromosome must match through candidate generation;
10. multiple contained annotations preserve multiplicity;
11. duplicate query/annotation identity is preserved;
12. left mode reconstructs zero-qualifying queries exactly once;
13. contains is explicitly distinguished from `min_overlap=1`;
14. `min_overlap` is not applied in contains mode;
15. strand composes by logical AND;
16. missing strand follows Task 6B semantics;
17. metadata preserved;
18. deterministic ordering preserved;
19. Bedtools independently passes explicit contains fixtures;
20. Polars-Bio independently passes the same fixtures;
21. differential parity passes;
22. empty-input behavior is canonical;
23. SPEC/engine-contract are updated;
24. no `within`/closest semantics implemented;
25. full repository suite has zero unexpected FAIL/XPASS.

---

# Final verification

Before completion:

1. inspect full diff vs `origin/main`;
2. run focused contains contract tests;
3. run Bedtools contains parity;
4. run Polars-Bio contains parity;
5. run differential contains parity;
6. run contains + strand tests;
7. run explicit contains-vs-min_overlap distinction tests;
8. run empty-input contains tests;
9. run full parity suite;
10. run full repository suite twice;
11. report exact PASS/XFAIL/XPASS/FAIL/SKIP;
12. manually inspect directionality fixtures;
13. verify `within` behavior/code remains unchanged except documentation needed to mark it future scope;
14. verify closest remains untouched;
15. verify docs and implementation agree exactly.

---

# Git discipline

Use:

`task-6c-contains-semantics`

Prefer logical commits such as:

```text
test: define query-contains-annotation contract
feat: implement backend-independent contains predicate
docs: lock down contains semantics
```

Do not manufacture unnecessary commits.

Open the PR only after independent review findings are resolved.

Do not merge automatically unless that is the established repository workflow.

---

# Final report

Return:

* branch;
* base commit;
* commits;
* files changed;
* final mathematical `contains` definition;
* directionality explanation;
* implementation architecture;
* Bedtools implementation strategy;
* Polars-Bio implementation strategy;
* relationship to `min_overlap`;
* relationship to strand;
* inner behavior;
* left behavior;
* duplicate/multiplicity behavior;
* empty-input behavior;
* exact focused test counts;
* exact full parity counts;
* exact repository-wide PASS/XFAIL/XPASS/FAIL/SKIP;
* reviewer findings and resolutions;
* SPEC/engine-contract changes;
* acceptance criteria status one by one;
* remaining Task 6D–6E backlog;
* explicit confirmation that `within` and final closest semantics were not implemented.

Do not begin Task 6D.
