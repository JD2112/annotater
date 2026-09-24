You are working on **AnnotateR**.

Tasks 1–5 and Tasks 6A–6D are complete and merged.

Implement **Task 6E only: final backend-independent `closest` / `nearest` semantics**.

This is the final extended-semantics task.

Do not add unrelated annotation modes, performance optimizations, parser changes, or UI redesign.

---

# Start state

Start from the current clean `main` after Task 6D has been merged and CI has passed.

Before editing:

1. `git fetch origin`
2. fast-forward local `main`
3. verify `main == origin/main`
4. verify working tree clean
5. create:

`task-6e-closest-semantics`

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
11. Task 6A `min_overlap` tests
12. Task 6B strand tests
13. Task 6C contains tests
14. Task 6D within tests
15. focused Bedtools and Polars-Bio engine tests

Consult pinned/version-matched primary documentation for:

* Bedtools `closest`;
* pybedtools closest behavior;
* Polars-Bio 0.35.1 `nearest`;
* canonical BED/interval coordinate conventions.

Do not use native backend distance values as semantic truth until they have been compared against the AnnotateR contract below.

---

# Goal

Make `closest` / `nearest` one backend-independent AnnotateR operation.

For the same canonical input and options:

```text
same query
same annotations
same strand setting
        ↓
BedtoolsEngine
PolarsBioEngine
        ↓
same nearest rows
same distance
same tie behavior
same ordering
```

The backend is an implementation detail.

---

# Normative terminology

AnnotateR's public mode remains:

```text
mode="closest"
```

Internally/backend APIs may call the operation `closest` or `nearest`.

These names refer to the same AnnotateR contract.

Do not introduce a second user-facing mode called `nearest`.

---

# Canonical distance definition

For canonical 0-based half-open intervals:

```text
Query Q      = [q_start, q_end)
Annotation A = [a_start, a_end)
```

Define canonical distance:

```text
if intervals overlap:
    distance = 0

elif q_end == a_start:
    distance = 0

elif a_end == q_start:
    distance = 0

elif q_end < a_start:
    distance = a_start - q_end

elif a_end < q_start:
    distance = q_start - a_end
```

Equivalent compact definition:

```text
distance(Q, A) =
    max(
        0,
        a_start - q_end,
        q_start - a_end
    )
```

Distance is therefore the number of genomic bases in the gap between the two half-open intervals.

---

# Important boundary examples

## Overlap

```text
Q = [10,20)
A = [15,25)

distance = 0
```

---

## Exact equality

```text
Q = [10,20)
A = [10,20)

distance = 0
```

---

## Touching right

```text
Q = [10,20)
A = [20,30)

distance = 0
```

---

## Touching left

```text
Q = [10,20)
A = [0,10)

distance = 0
```

---

## One-base gap right

```text
Q = [10,20)
A = [21,30)

distance = 1
```

---

## One-base gap left

```text
Q = [10,20)
A = [0,9)

distance = 1
```

---

## Larger gap

```text
Q = [10,20)
A = [25,30)

distance = 5
```

---

# Resolve the known 76-vs-75 discrepancy

Task 5 documented a Bedtools-vs-Polars-Bio closest distance discrepancy such as:

```text
Bedtools     → 76
Polars-Bio   → 75
```

Do NOT choose one backend's native distance convention as normative.

AnnotateR's canonical half-open gap formula above is normative.

If a backend native distance differs:

* use the backend only to identify candidate nearest rows if useful;
* calculate/recalculate canonical AnnotateR distance from canonical coordinates;
* return the canonical distance.

Add a regression fixture reproducing the old off-by-one discrepancy.

---

# Same chromosome is mandatory

Closest candidates must be on the same chromosome as the query.

Annotations on different chromosomes are not candidates regardless of numerical coordinate proximity.

For a query with no eligible annotation on its chromosome:

* inner closest → zero rows;
* left closest → exactly one unmatched query row.

Do not define distance across chromosomes.

---

# Tie semantics

AnnotateR SHALL return **all annotation rows tied for the minimum canonical distance**.

For each query:

```text
1. identify eligible annotations;
2. compute canonical distance for each;
3. find d_min;
4. return every annotation with distance == d_min;
```

Do not arbitrarily choose one.

---

# Tie ordering

For tied nearest annotations, preserve:

```text
annotation input order
```

Overall canonical ordering remains:

```text
query input order
→ annotation input order among tied nearest rows
```

Do not sort ties by:

* coordinate;
* strand;
* interval length;
* backend output order;
* lexicographic metadata;
* native distance column.

Use explicit annotation row identity where needed.

---

# Required tie examples

## Symmetric tie

```text
Q = [10,20)

A = [0,5)    distance 5
B = [25,30)  distance 5
```

Return both A and B.

---

## Duplicate tied annotations

Two identical annotations at the minimum distance must produce two rows.

Do not deduplicate.

---

## Three-way tie

All three minimum-distance annotations must be returned in original annotation order.

---

# Overlap and nearest

Overlapping annotations are legitimate nearest candidates.

If one or more annotations overlap the query:

```text
distance = 0
```

and all overlapping annotations tied at zero must be returned.

Annotations with positive distance are not returned.

Example:

```text
Q [10,20)

A [11,15)  distance 0
B [18,30)  distance 0
C [21,30)  distance 1
```

Return A and B only.

---

# Touching and nearest

Touching intervals also have canonical distance zero.

Example:

```text
Q [10,20)

A [20,30)  distance 0
B [21,30)  distance 1
```

Return A only.

This is intentional even though ordinary overlap semantics treat touching as non-overlap.

Closest distance and overlap qualification are different concepts.

---

# Strand semantics

Task 6B is normative.

## `use_strand=False`

Ignore strand when determining eligible closest annotations.

---

## `use_strand=True`

Filter eligible annotations BEFORE nearest selection.

A candidate annotation is strand-eligible only if:

```text
query strand ∈ {"+", "-"}
AND
annotation strand ∈ {"+", "-"}
AND
query strand == annotation strand
```

Missing/unknown strand is NOT a wildcard.

---

# Order of operations for stranded closest

This is critical.

Correct:

```text
same chromosome
      ↓
strand eligibility
      ↓
canonical distance
      ↓
minimum distance
      ↓
all ties
```

Incorrect:

```text
find nearest ignoring strand
      ↓
discard wrong-strand nearest
```

The latter can lose a valid farther same-strand annotation.

---

# Required stranded-nearest fixture

```text
Query Q "+"

A "-" distance 1
B "+" distance 10
```

With:

```text
use_strand=False
```

nearest = A.

With:

```text
use_strand=True
```

nearest = B.

This case is mandatory.

---

# Missing-strand closest

Example:

```text
Query Q "+"
A missing, distance 1
B "+",     distance 10
```

With `use_strand=True`, B is the nearest eligible annotation.

If all annotations have missing/opposite strand:

* inner → zero rows;
* left → exactly one unmatched query row.

---

# Relationship with `min_overlap`

`min_overlap` remains scoped to:

```text
mode="overlap"
```

It SHALL NOT affect closest.

Do not use overlap fraction when selecting nearest.

Pin this with a regression test.

---

# Relationship with contains / within

`contains` and `within` semantics do not apply in closest mode.

A contained annotation may naturally have distance zero, but it is selected because:

```text
distance == minimum distance
```

not because the contains/within predicate ran.

Keep relation modes mutually explicit.

---

# Inner closest semantics

For:

```text
how="inner"
mode="closest"
```

For every query with one or more eligible same-chromosome annotations:

* return all annotations tied at minimum distance;
* add canonical distance;
* preserve query/annotation metadata.

If a query has no eligible candidate:

```text
emit zero rows for that query
```

---

# Left closest semantics

For:

```text
how="left"
mode="closest"
```

Every query row survives.

If eligible nearest annotation(s) exist:

* emit one row per minimum-distance annotation;
* `has_overlap=True` according to the existing canonical "matched relation" convention;
* canonical distance populated.

If no eligible annotation exists:

* emit exactly one unmatched query row;
* annotation fields canonical missing;
* `has_overlap=False`;
* distance canonical missing.

Do not emit failed candidates.

---

# Distance column contract

Inspect the existing public closest result schema and preserve the established column name if one already exists.

Do not casually rename it.

Make its semantics normative.

Preferred canonical dtype:

```text
nullable integer (Int64)
```

because canonical distance is an integer number of bases.

Matched closest rows:

```text
distance >= 0
```

Unmatched left rows:

```text
distance = pd.NA
```

Do not return backend-native float distance when the canonical gap is integral.

---

# `has_overlap` naming note

The existing canonical field is called:

```text
has_overlap
```

even though in closest mode a positive-distance nearest relation is not literally an overlap.

Do not rename this field in Task 6E unless SPEC already mandates another representation.

Within closest mode interpret:

```text
has_overlap=True
```

as:

> this query has a qualifying closest annotation result row

and:

```text
False
```

for unmatched left rows.

Document this existing convention if necessary.

Do not broaden Task 6E into a schema redesign.

---

# Architecture

Do not let each backend define closest independently.

Preferred architecture:

```text
canonical query / annotation frames
        ↓
eligible candidate generation
        ↓
same-chromosome filter
        ↓
shared strand eligibility
        ↓
shared canonical distance
        ↓
shared per-query minimum selection
        ↓
all ties
        ↓
left reconstruction
        ↓
canonical output
```

A backend may help generate nearest candidates, but correctness must come from AnnotateR's canonical contract.

---

# Candidate-generation strategy

Investigate the simplest correct implementation.

Potential strategies include:

## Strategy A — backend-native nearest + verification/expansion

Use Bedtools / Polars-Bio nearest machinery to identify likely nearest candidate(s), then:

* recompute canonical distance;
* ensure all ties are returned;
* correct backend-specific distance convention.

This is acceptable only if native APIs provide enough candidates to recover all canonical ties.

---

## Strategy B — AnnotateR canonical per-chromosome nearest selection

Use canonical input tables directly:

* group candidates by chromosome;
* optionally strand-filter;
* calculate canonical distance;
* choose minima.

This provides one implementation for both backends and may be preferable for correctness.

However, consider scalability.

Do NOT blindly build a full genome-wide Cartesian product.

If implementing canonical nearest directly, constrain candidate search intelligently by:

* chromosome;
* sorted intervals;
* backend-assisted candidates;
* or another deterministic non-quadratic approach where practical.

Correctness comes first, but avoid obviously pathological design if a simple efficient solution exists.

---

# Bedtools strategy

Current Bedtools closest behavior is non-normative and has:

* native distance convention discrepancy;
* existing `-s` forwarding;
* sorted-input requirements.

Do not preserve these as public AnnotateR semantics automatically.

In particular:

## Native distance

Do not return Bedtools `-d` as canonical distance without recalculation.

## Strand

Do not delegate public strand semantics to `bedtools closest -s`.

Apply Task 6B eligibility before nearest selection or otherwise prove exact equivalence, especially for missing strand.

## Ties

Inspect Bedtools tie behavior and options.

Do not assume its default ordering/multiplicity alone satisfies AnnotateR.

## Sorted input

AnnotateR should not require users to genomically sort canonical DataFrames merely because native Bedtools closest does.

If Bedtools requires sorted temporary input:

* sort internal temporary data if necessary;
* preserve/reconstruct original query and annotation identity/order;
* do not expose backend sorting requirements as a user contract unless unavoidable and explicitly justified.

---

# Polars-Bio strategy

Inspect pinned Polars-Bio 0.35.1 `nearest` semantics.

Verify:

* overlap inclusion;
* distance convention;
* tie behavior;
* `k=1`;
* ordering;
* empty inputs;
* whether all equal-distance nearest rows are returned;
* strand support or absence thereof.

Do not rely on `k=1` if it drops tied nearest annotations.

If Polars-Bio returns only one tied row, use a strategy that can recover all canonical ties.

Recalculate distance canonically.

---

# Required explicit fixtures

Create expected-result fixtures independent of either backend.

At minimum cover:

## 1. Exact overlap

distance 0.

---

## 2. Exact equality

distance 0.

---

## 3. Containment

distance 0.

---

## 4. Touching right

distance 0.

---

## 5. Touching left

distance 0.

---

## 6. One-base right gap

distance 1.

---

## 7. One-base left gap

distance 1.

---

## 8. Larger right gap

exact expected distance.

---

## 9. Larger left gap

exact expected distance.

---

## 10. Old 76-vs-75 discrepancy

Pin canonical expected distance explicitly.

---

## 11. Two candidates, different distances

Return nearest only.

---

## 12. Symmetric left/right tie

Return both.

---

## 13. Multiple overlapping candidates

All distance-zero ties returned.

---

## 14. Touching + overlapping tie

If both canonical distance zero, return both.

---

## 15. Duplicate nearest annotations

Preserve duplicates.

---

## 16. Duplicate queries

Each query identity resolved independently.

---

## 17. Three-way tie

Preserve annotation input order.

---

## 18. Annotation on different chromosome closer numerically

Ignore it.

---

## 19. No same-chromosome annotation

Inner → none.

Left → unmatched exactly once.

---

## 20. Strand off nearest

Closest chosen regardless of strand.

---

## 21. Strand on: geometrically nearest wrong strand

Farther same-strand annotation must win.

Mandatory fixture.

---

## 22. Strand on: same-distance same/opposite strand

Return only same-strand candidate(s).

---

## 23. Strand on: no same-strand candidate

Inner → none.

Left → unmatched.

---

## 24. Missing query strand

With `use_strand=True`, no candidate qualifies.

---

## 25. Missing annotation strand

Not eligible in stranded mode.

---

## 26. Both missing strand

Unknown-vs-unknown does not qualify.

---

## 27. `min_overlap` supplied in closest mode

Must not affect result.

---

## 28. Metadata preservation

All query/annotation metadata preserved.

---

## 29. Empty query

Empty result for both inner and left.

---

## 30. Empty annotation

Inner → empty.

Left → one unmatched row per query.

---

# Canonical distance helper

Prefer one shared engine-neutral helper such as:

```text
interval_distance(...)
```

It must operate on canonical coordinates and implement exactly the normative half-open formula.

Do not duplicate distance arithmetic in both engines.

Add focused unit tests directly against the helper.

---

# Nearest selection helper

Prefer one shared concept for:

```text
per query:
    eligible candidates
    → minimum canonical distance
    → all ties
```

Avoid separate tie logic in BedtoolsEngine and PolarsBioEngine.

---

# Numeric robustness

Coordinates are integer canonical coordinates.

Distance must therefore be exact integer arithmetic.

Do not use floating-point distance calculations.

Avoid conversion through float that could corrupt large genomic coordinates.

---

# Ordering

The result must preserve:

```text
query input order
→ annotation input order among nearest ties
```

Queries themselves must not be sorted genomically in final output.

Any backend-internal sorting must be undone using stable row identity.

---

# Metadata

Task 5's metadata round-trip rules remain normative.

Do not allow closest implementation to reintroduce:

* Bedtools string retyping;
* `"."` sentinel leakage;
* suffix artifacts;
* internal IDs;
* Polars helper columns.

---

# Failure behavior

Backend/native failure:

```text
→ propagated error
```

Valid absence of eligible annotation:

```text
→ valid no-match
```

Do not convert backend errors to unmatched rows.

---

# UI

Do not redesign the UI.

If closest is already selectable, preserve that surface.

Correct help text if it currently implies backend-native distance.

Suggested wording:

> Return the nearest annotation interval(s). Tied nearest annotations are all returned. Distance is the canonical number of bases between intervals; overlapping or touching intervals have distance 0.

Keep copy concise.

---

# Documentation changes

Task 6E makes closest normative.

Update at minimum:

* `SPEC.md`
* `docs/engine-contract.md`
* `docs/implementation-notes.md`
* `PLAN.md`
* user-facing README/QUICKSTART/settings help text if stale
* `docs/references.md` only if a backend-specific behavior discovered during implementation needs recording

Document:

1. canonical distance formula;
2. overlap = 0;
3. touching = 0;
4. gap measured in bases;
5. same chromosome only;
6. all minimum-distance ties returned;
7. tie ordering = annotation input order;
8. strand filtering occurs before nearest selection;
9. missing strand not wildcard;
10. left unmatched behavior;
11. canonical nullable-integer distance;
12. native backend distance is non-normative.

Remove all stale notes calling closest non-normative after completion.

---

# Explicit non-goals

Do NOT implement:

* upstream/downstream directional nearest modes;
* transcription-aware upstream/downstream semantics;
* signed distance;
* maximum-distance cutoff;
* `k > 1` nearest ranking;
* first-only / last-only tie controls;
* reciprocal strand logic;
* cross-chromosome distance;
* circular chromosomes;
* parser changes;
* schema redesign;
* dependency upgrades;
* broad performance optimization;
* UI redesign.

Task 6E defines only the existing closest mode.

---

# Review loop

Use two independent Pi subagent reviewers if available.

## Reviewer 1 — genomic semantics

Check:

* half-open distance arithmetic;
* overlap = 0;
* touching = 0;
* one-base gaps;
* old 76-vs-75 fixture;
* same-chromosome restriction;
* all ties;
* tie ordering;
* strand-before-nearest;
* missing-strand behavior;
* left semantics.

## Reviewer 2 — implementation/test quality

Check:

* one shared distance definition;
* no reliance on native backend distance;
* no arbitrary one-tie selection;
* no Cartesian explosion without justification;
* stable row identity/order;
* metadata preservation;
* Bedtools sorting requirements hidden internally;
* Polars `k=1` tie loss avoided if applicable;
* empty inputs;
* no scope creep.

Resolve all BLOCKER and MAJOR findings.

---

# Acceptance criteria

Task 6E is complete only when:

1. closest has one explicit backend-independent definition;
2. canonical half-open distance formula is documented;
3. overlapping intervals have distance 0;
4. touching intervals have distance 0;
5. one-base gap has distance 1;
6. larger gaps are exact;
7. old Bedtools-vs-Polars off-by-one case is resolved canonically;
8. only same-chromosome annotations are eligible;
9. all minimum-distance ties are returned;
10. tie order follows annotation input order;
11. overlapping zero-distance ties are all returned;
12. duplicate annotations preserved;
13. duplicate queries preserved;
14. `use_strand=False` ignores strand;
15. `use_strand=True` filters eligibility before nearest selection;
16. wrong-strand nearer candidate cannot suppress farther same-strand candidate;
17. missing strand is not wildcard;
18. no eligible stranded candidate behaves as no-match;
19. `min_overlap` does not affect closest;
20. contains/within predicates do not run in closest mode;
21. inner semantics correct;
22. left semantics correct;
23. unmatched left distance is missing;
24. canonical distance dtype is nullable integer;
25. metadata preserved;
26. deterministic ordering preserved;
27. empty-input behavior canonical;
28. Bedtools independently satisfies explicit expected fixtures;
29. Polars-Bio independently satisfies same fixtures;
30. differential parity passes;
31. native backend distance values are not exposed as canonical truth;
32. docs updated and stale non-normative language removed;
33. no unexpected FAIL/XPASS in full suite;
34. no unrelated feature work started.

---

# Final verification

Before completion:

1. inspect full diff vs `origin/main`;
2. run focused canonical-distance helper tests;
3. run Bedtools closest contract tests;
4. run Polars-Bio closest contract tests;
5. run differential closest parity;
6. run tie tests;
7. run stranded-nearest tests;
8. run old 76-vs-75 regression fixture;
9. run empty-input tests;
10. run full parity suite;
11. run full repository suite twice;
12. report exact PASS/XFAIL/XPASS/FAIL/SKIP;
13. manually inspect touching vs one-base-gap output;
14. manually inspect stranded farther-candidate fixture;
15. manually inspect all-ties ordering;
16. verify no backend-private distance leaks;
17. verify docs and implementation agree exactly.

---

# Git discipline

Use:

`task-6e-closest-semantics`

Prefer logical commits such as:

```text
test: define canonical closest and distance contract
feat: implement backend-independent nearest selection
docs: lock down closest semantics
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
* exact canonical distance formula;
* explanation of touching vs one-base-gap;
* resolution of the old 76-vs-75 discrepancy;
* tie policy;
* tie ordering;
* implementation architecture;
* Bedtools implementation strategy;
* Polars-Bio implementation strategy;
* strand-before-nearest strategy;
* missing-strand behavior;
* inner behavior;
* left behavior;
* distance dtype/missing-value policy;
* duplicate/multiplicity behavior;
* empty-input behavior;
* exact focused test counts;
* exact full parity counts;
* exact repository-wide PASS/XFAIL/XPASS/FAIL/SKIP;
* reviewer findings and resolutions;
* SPEC/engine-contract changes;
* acceptance criteria status one by one;
* any remaining known limitations;
* explicit confirmation that no additional Task 6 feature work was started.

Do not begin any new milestone after Task 6E.
