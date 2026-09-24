You are working on **AnnotateR**.

Tasks 1–5 and Tasks 6A–6C are complete and merged.

Implement **Task 6D only: `within` semantics**.

Do not implement final `closest/nearest` semantics in this PR.

The purpose of Task 6D is to define, document, test, and implement one backend-independent meaning for AnnotateR's existing `within` operation.

---

# Start state

Start from the current clean `main` after Task 6C has been merged and CI has passed.

Before editing:

1. `git fetch origin`
2. fast-forward local `main`
3. verify `main == origin/main`
4. verify working tree clean
5. create:

`task-6d-within-semantics`

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
13. Task 6C contains tests
14. focused Bedtools and Polars-Bio engine tests

Consult pinned/version-matched primary documentation for Bedtools and Polars-Bio interval-containment behavior.

Do not use backend flag names as semantic truth.

---

# Normative definition

For canonical half-open intervals:

```text
Query Q      = [q_start, q_end)
Annotation A = [a_start, a_end)
```

AnnotateR `within` SHALL mean:

> **the query interval is fully contained within the annotation interval**

Formally:

```text
within(Q, A) =
    a_start <= q_start
    AND
    a_end >= q_end
```

Boundary equality counts as containment.

---

# Directionality is critical

The following examples define the contract.

## Annotation larger than query

```text
Q = [15,20)
A = [10,30)
```

`within=True`

---

## Equal intervals

```text
Q = [10,20)
A = [10,20)
```

`within=True`

---

## Shared left boundary

```text
Q = [10,20)
A = [10,30)
```

`within=True`

---

## Shared right boundary

```text
Q = [10,20)
A = [5,20)
```

`within=True`

---

## Query contains annotation

```text
Q = [10,30)
A = [15,20)
```

`within=False`

This is `contains`, not `within`.

---

## Partial overlap

```text
Q = [10,20)
A = [15,25)
```

`within=False`

---

## Touching only

```text
Q = [10,20)
A = [20,25)
```

`within=False`

---

# Contains / within inverse relationship

Task 6C defined:

```text
contains(Q, A) =
    q_start <= a_start
    AND
    q_end >= a_end
```

Task 6D defines:

```text
within(Q, A) =
    a_start <= q_start
    AND
    a_end >= q_end
```

These are directional inverses with respect to query/annotation roles.

Explicitly test both directions.

For example:

```text
Q [0,100)
A [10,20)
```

Expected:

```text
contains = True
within   = False
```

while:

```text
Q [10,20)
A [0,100)
```

Expected:

```text
contains = False
within   = True
```

Equal intervals:

```text
Q [10,20)
A [10,20)
```

Expected:

```text
contains = True
within   = True
```

because equality satisfies both containment relations.

---

# Do not implement within as min_overlap

Task 6A `min_overlap` is query-relative.

Therefore:

```text
Q [10,20)
A [0,100)
```

produces:

```text
min_overlap=1.0 → True
within          → True
```

but this coincidence does NOT make the operations equivalent.

Counterexample:

```text
Q [10,20)
A [5,15)
```

If overlap fraction is 0.5, `min_overlap=0.5` may qualify, while `within=False`.

And:

```text
Q [10,20)
A [10,20)
```

both may qualify for different semantic reasons.

Pin explicit tests proving that `within` is a positional containment predicate, not a coverage threshold.

---

# Architecture

`within` is an AnnotateR canonical predicate.

Prefer a shared engine-neutral predicate applied to ordinary overlap candidates.

Conceptually:

```text
canonical inputs
      ↓
ordinary backend overlap candidates
      ↓
within_keep_mask()
      ↓
strand filter if enabled
      ↓
left reconstruction
      ↓
canonical output
```

Do not implement the same inequalities separately in the Bedtools and Polars-Bio engines.

---

# Shared predicate

Prefer a single helper such as:

```text
within_keep_mask(...)
```

or an appropriately generalized interval-relation helper.

It must use canonical coordinates only.

Do not infer relation from overlap percentages.

---

# Relationship with existing mode

If the public API already accepts:

```text
mode="within"
```

make that mode normative.

Do not introduce a new operation name.

Do not alter invalid-mode behavior.

---

# Relationship with `min_overlap`

Task 6A scoped `min_overlap` to ordinary overlap mode.

Preserve that rule.

Therefore:

```text
mode="within"
```

must NOT apply `min_overlap`.

If callers provide both, the `within` predicate remains the operative interval relation and `min_overlap` remains inactive in this mode according to the existing contract.

Pin with a regression test.

---

# Relationship with strand

Task 6B strand semantics remain orthogonal.

With:

```text
mode="within"
use_strand=True
```

a pair qualifies iff:

```text
within(Q, A)
AND
same_explicit_strand(Q, A)
```

Examples:

```text
Q [15,20) "+"
A [10,30) "+"
→ match
```

```text
Q [15,20) "+"
A [10,30) "-"
→ no match
```

```text
Q [15,20) missing
A [10,30) "+"
→ no match
```

Do not delegate missing-strand behavior to backend-native containment flags.

---

# Inner semantics

For:

```text
how="inner"
mode="within"
```

emit one row per qualifying query/annotation pair.

No qualifying pairs:

```text
→ zero rows
```

Preserve duplicates and multiplicity.

---

# Left semantics

For:

```text
how="left"
mode="within"
```

all query rows survive.

Per query:

* one containing annotation → one matched row;
* multiple containing annotations → one row per qualifying annotation;
* zero containing annotations → exactly one unmatched query row;
* partial overlaps do not count;
* annotations contained by the query do not count.

Unmatched canonical row:

```text
has_overlap = False
annot_* = pd.NA
```

Do not emit both failed candidate rows and an unmatched row.

---

# Required fixtures

Build explicit expected-result fixtures independent of backend output.

At minimum include:

## 1. Strict within

```text
Q [15,20)
A [10,30)
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
Q [10,20)
A [10,30)
```

match.

---

## 4. Shared right boundary

```text
Q [10,20)
A [5,20)
```

match.

---

## 5. Query contains annotation

```text
Q [10,30)
A [15,20)
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
A [20,30)
```

no match.

---

## 9. Touching left

```text
Q [10,20)
A [0,10)
```

no match.

---

## 10. Different chromosome

Never match.

---

## 11. One query within multiple annotations

```text
Q [20,30)

A [0,100)
B [10,40)
C [20,30)
```

All three qualify.

Preserve annotation input order.

---

## 12. Mixed containing and partial annotations

Only actual containing annotations qualify.

---

## 13. Duplicate queries

Preserve query identity/multiplicity.

---

## 14. Duplicate annotations

Preserve annotation multiplicity.

---

## 15. Left no qualifying match

There may be ordinary overlaps, but none fully contain the query.

Expected exactly one unmatched query row.

---

## 16. Left mixed

One annotation contains query, another only partially overlaps.

Emit only the qualifying match.

No unmatched row.

---

## 17. Within vs contains direction A

```text
Q [10,20)
A [0,100)
```

Expected:

```text
within   = True
contains = False
```

---

## 18. Within vs contains direction B

```text
Q [0,100)
A [10,20)
```

Expected:

```text
within   = False
contains = True
```

---

## 19. Equality satisfies both

```text
Q [10,20)
A [10,20)
```

Expected both `contains` and `within` true.

---

## 20. Within vs min_overlap distinction

Include at least one case where a query-fraction threshold passes but within fails.

---

## 21. Same strand

Within + same explicit strand passes.

---

## 22. Opposite strand

Within + opposite strand fails under `use_strand=True`.

---

## 23. Missing strand

Within geometry + missing strand fails in stranded mode.

---

## 24. Empty annotation

Inner → empty.

Left → one unmatched row per query.

---

## 25. Empty query

Always empty.

---

## 26. Metadata preservation

Verify exact coord/annotation metadata preservation.

---

# Backend strategy

## Bedtools

The current non-normative placeholder may use:

```text
-F 1.0
```

Inspect carefully what `-F` means for the actual `-a/-b` orientation.

Do NOT preserve it simply because the observed direction appears close.

Task 6D correctness is defined by:

```text
a_start <= q_start
AND
a_end >= q_end
```

not by a Bedtools flag.

If native Bedtools behavior is proven exactly equivalent, it may remain.

However, for consistency with Tasks 6A–6C, prefer:

```text
ordinary overlap candidates
→ shared within predicate
```

unless there is a strong reason otherwise.

Remove old placeholder flags from the `within` overlap path if they are no longer needed.

---

# Polars-Bio

Use pinned Polars-Bio 0.35.1 behavior only as candidate generation unless an exact containment primitive exists and is proven equivalent.

Preferred:

```text
pb.overlap
→ shared within_keep_mask
```

Preserve:

* zero-based coordinate metadata;
* row identity;
* error propagation;
* deterministic ordering;
* canonical output mapping.

---

# Candidate generation

True within relationships imply ordinary positive overlap for valid non-empty canonical intervals.

Therefore ordinary overlap is a complete candidate generator.

Do not build query × annotation Cartesian products.

---

# Empty inputs

Explicitly verify:

## Inner

```text
empty query → empty
empty annotation → empty
both empty → empty
```

## Left

```text
empty query → empty

non-empty query + empty annotation
→ exactly one unmatched row per query
```

Reuse established reconstruction machinery.

---

# Ordering

Filtering must preserve:

```text
query input order
→ annotation input order
```

Do not sort by:

* interval size;
* nesting depth;
* coordinates;
* strand.

---

# Metadata and helpers

No helper columns may leak.

Preserve:

* canonical column order;
* canonical dtypes;
* metadata values;
* missing values;
* duplicate identity.

No `_1`, `_2`, row-id, suffix, or temporary Bedtools fields in final output.

---

# Documentation changes

Task 6D makes `within` normative.

Update at minimum:

* `SPEC.md`
* `docs/engine-contract.md`
* `docs/implementation-notes.md`
* `PLAN.md`

Document explicitly:

> `within` means the query interval is fully contained within the annotation interval.

Formal predicate:

```text
a_start <= q_start
AND
a_end >= q_end
```

Also document:

* equality allowed;
* directionality;
* inverse relationship with `contains`;
* distinction from `min_overlap`;
* strand composition;
* inner/left behavior.

Remove stale wording describing `within` as placeholder/non-normative.

Do not make closest normative yet.

---

# UI

Do not redesign the UI.

If `within` is already selectable, preserve it.

Correct ambiguous or backwards wording if present.

Preferred user-facing copy:

> Query within annotation

or:

> Return annotations that fully contain each query interval.

Be careful: because output rows contain query + annotation, phrasing should not imply the annotation itself is being returned “within” something if that reverses direction.

---

# Explicit non-goals

Do NOT implement:

* final closest/nearest semantics;
* reciprocal containment options;
* percentage containment;
* new min_overlap behavior;
* opposite-strand modes;
* parser changes;
* canonical-coordinate changes;
* dependency upgrades;
* performance optimization;
* UI redesign.

Do not start Task 6E.

---

# Review loop

Use two independent Pi subagent reviewers if available.

## Reviewer 1 — genomic semantics

Check:

* direction is annotation contains query;
* equality qualifies;
* shared boundaries qualify;
* query-contains-annotation fails;
* partial overlap fails;
* touching fails;
* inverse relation to `contains` is correct;
* distinction from `min_overlap`;
* left semantics;
* strand composition.

## Reviewer 2 — implementation/test quality

Check:

* one shared `within` predicate;
* no mistaken `-f/-F` orientation;
* no Cartesian generation;
* duplicates/order/metadata preserved;
* empty input handling;
* contains remains unchanged;
* closest remains untouched;
* stale placeholder docs removed.

Resolve all BLOCKER and MAJOR findings.

---

# Acceptance criteria

Task 6D is complete only when:

1. `within` is explicitly defined as query fully contained by annotation;
2. formal predicate is `a_start <= q_start && a_end >= q_end`;
3. equal intervals qualify;
4. shared-left-boundary cases qualify;
5. shared-right-boundary cases qualify;
6. query-contains-annotation does not qualify;
7. partial overlaps do not qualify;
8. touching intervals do not qualify;
9. chromosome constraint remains respected;
10. one query within multiple annotations preserves multiplicity;
11. duplicates preserve identity;
12. left mode reconstructs non-qualifying queries exactly once;
13. inverse relationship with `contains` is explicitly tested;
14. equality satisfying both `contains` and `within` is tested;
15. `within` is distinguished from `min_overlap`;
16. `min_overlap` is not applied in within mode;
17. strand composes by logical AND;
18. missing strand follows Task 6B semantics;
19. metadata preserved;
20. deterministic ordering preserved;
21. Bedtools independently passes explicit fixtures;
22. Polars-Bio independently passes the same fixtures;
23. differential parity passes;
24. empty-input behavior canonical;
25. SPEC/engine-contract updated;
26. no closest semantics implemented;
27. full repository suite has zero unexpected FAIL/XPASS.

---

# Final verification

Before completion:

1. inspect full diff vs `origin/main`;
2. run focused within contract tests;
3. run Bedtools within parity;
4. run Polars-Bio within parity;
5. run differential within parity;
6. run within + strand cases;
7. run contains-vs-within inversion tests;
8. run within-vs-min_overlap distinction tests;
9. run empty-input tests;
10. run full parity suite;
11. run full repository suite twice;
12. report exact PASS/XFAIL/XPASS/FAIL/SKIP;
13. manually inspect A/B direction fixtures;
14. verify contains implementation remains unchanged;
15. verify closest remains untouched;
16. verify docs and implementation agree exactly.

---

# Git discipline

Use:

`task-6d-within-semantics`

Prefer logical commits such as:

```text
test: define query-within-annotation contract
feat: implement backend-independent within predicate
docs: lock down within semantics
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
* final mathematical `within` definition;
* directionality explanation;
* relationship to `contains`;
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
* remaining Task 6E backlog;
* explicit confirmation that final closest semantics were not implemented.

Do not begin Task 6E.
