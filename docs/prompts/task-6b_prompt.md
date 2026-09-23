You are working on **AnnotateR**.

Tasks 1–5 and Task 6A are complete and merged.

Implement **Task 6B only: strand-aware overlap semantics**.

Do not implement `contains`, `within`, or final `closest/nearest` semantics in this PR.

The purpose of Task 6B is to define, document, test, and implement one backend-independent meaning for the existing `use_strand` option.

---

# Start state

Start from the current clean `main` after Task 6A has been merged and CI has passed.

Before editing:

1. `git fetch origin`
2. fast-forward local `main`
3. verify `main == origin/main`
4. verify working tree clean
5. create:

`task-6b-strand-semantics`

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
10. `streamlit_app/core/normalization.py`
11. complete `tests/parity/`
12. focused Bedtools and Polars-Bio engine tests
13. Task 6A min-overlap tests

Consult the pinned/version-matched primary documentation for:

* Bedtools strand-aware intersection (`-s`);
* Polars-Bio 0.35.1 strand-related overlap options, if any;
* BED/GFF/GTF strand semantics from the normative references in `docs/references.md`.

Do not rely solely on model memory.

---

# Normative decision for Task 6B

AnnotateR's `use_strand` SHALL mean:

## `use_strand=False`

Strand does not participate in match qualification.

A query/annotation pair may match based solely on the selected interval predicate and other active options.

This preserves current ordinary behavior.

## `use_strand=True`

A query/annotation pair qualifies only if:

1. both rows have an explicit canonical strand;
2. query strand is either `"+"` or `"-"`;
3. annotation strand is either `"+"` or `"-"`;
4. query strand == annotation strand;
5. the interval predicate also qualifies.

Formally:

```text
strand_match(Q, A) =
    Q.strand ∈ {"+", "-"}
    AND
    A.strand ∈ {"+", "-"}
    AND
    Q.strand == A.strand
```

and:

```text
qualifies =
    interval_predicate(Q, A)
    AND
    strand_match(Q, A)
```

when `use_strand=True`.

---

# Missing/unknown strand semantics

The following are NOT wildcards:

```text
pd.NA
None
"."
""
missing strand column
```

When `use_strand=True`, a row with unknown/missing strand cannot form a stranded match.

Examples:

```text
query "+"
annotation "+"
→ match if interval predicate matches
```

```text
query "+"
annotation "-"
→ no match
```

```text
query "+"
annotation "."
→ no match
```

```text
query "."
annotation "+"
→ no match
```

```text
query missing
annotation missing
→ no match
```

Do not silently treat `"."` as either strand.

---

# Canonical strand representation

Task 2 already defines canonical strand semantics.

Re-read that contract before editing.

At the canonical layer:

```text
"+"
"-"
missing
```

are the only meaningful states.

If source formats use `"."`, convert it according to the canonical missing-value policy before engine semantics are evaluated.

Do not introduce a fourth canonical `"."` state merely for Bedtools compatibility.

Backend serialization may temporarily require `"."`, but that is not the public/canonical value.

---

# Important architectural principle

Strand semantics belong to AnnotateR, not to Bedtools.

Do not define correctness as:

> whatever `bedtools -s` happens to do.

Instead:

1. define explicit expected fixtures;
2. test both engines independently against them;
3. optionally use backend-native stranded operations only if they are proven equivalent to the AnnotateR contract.

A shared post-filter is acceptable and may be preferable if it provides clearer backend parity.

---

# Preferred architecture

Evaluate whether strand qualification should be implemented as a shared canonical pair filter, analogous to Task 6A `min_overlap`.

Conceptually:

```text
canonical inputs
      ↓
ordinary backend relation
      ↓
canonical candidate pairs
      ↓
shared AnnotateR strand predicate
      ↓
other shared predicates such as min_overlap
      ↓
left reconstruction
      ↓
canonical result
```

This has several advantages:

* exact same meaning for both engines;
* missing-strand behavior is independent of backend quirks;
* easier composition with `min_overlap`;
* easier testing.

However, if native backend strand filtering is retained, prove exact parity against all fixtures below.

Do not use native backend behavior merely because it already exists.

---

# Composition with Task 6A `min_overlap`

Task 6B must explicitly verify that strand and `min_overlap` compose by logical AND.

Example:

```text
query:      [10,20), strand="+"
annotation: [15,25), strand="+"
min_overlap=0.5
```

overlap fraction = 0.5 and strand matches → qualifies.

Same coordinates with annotation strand `"-"`:

```text
min_overlap passes
strand fails
→ no match
```

Same strand but overlap fraction below threshold:

```text
strand passes
min_overlap fails
→ no match
```

Do not establish precedence where one option bypasses the other.

---

# Left-mode semantics

When `how="left"` and `use_strand=True`, strand qualification determines whether a query has any qualifying matches.

Example:

```text
query Q "+"
annotation A "-"
coordinates overlap
```

The interval overlap exists, but the stranded match does not.

Therefore Q is unmatched.

Canonical left output:

```text
query fields preserved
annotation fields = missing
has_overlap = False
```

exactly once for that query if no other annotation passes both interval and strand predicates.

If another annotation `B "+"` qualifies:

```text
emit Q-B matched row
do not emit unmatched Q row
```

---

# Required explicit fixtures

Build expected-result fixtures independent of backend output.

## 1. Same positive strand

```text
query      [10,20) "+"
annotation [15,25) "+"
```

Expected:

```text
use_strand=False → match
use_strand=True  → match
```

---

# 2. Same negative strand

```text
query      [10,20) "-"
annotation [15,25) "-"
```

Expected match in stranded mode.

---

# 3. Opposite strand

```text
query      [10,20) "+"
annotation [15,25) "-"
```

Expected:

```text
use_strand=False → match
use_strand=True  → no match
```

Repeat the inverse `"-"` vs `"+"`.

---

# 4. Query missing strand

Query overlaps an explicit annotation strand.

Expected:

```text
use_strand=False → match
use_strand=True  → no match
```

---

# 5. Annotation missing strand

Same expectation.

---

# 6. Both missing strand

Intervals overlap.

Expected:

```text
use_strand=False → match
use_strand=True  → no match
```

Unknown == unknown is NOT a stranded match.

---

# 7. `"."` source value

Use at least one format/input fixture where strand `"."` occurs historically.

Verify normalization produces canonical missing strand.

Then verify stranded matching does not treat it as `"+"`, `"-"`, or wildcard.

---

# 8. One query, two annotation strands

```text
query Q "+"

annotation A "+"
annotation B "-"
```

Both coordinates overlap.

Expected stranded result:

```text
Q-A only
```

Unstranded result:

```text
Q-A
Q-B
```

---

# 9. Duplicate annotations

Two identical `"+"` annotations must yield two matched rows.

Do not deduplicate.

---

# 10. Duplicate queries

Two identical biological `"+"` queries with distinct row identity remain distinct.

Preserve multiplicity/order.

---

# 11. Left mismatch only

```text
query Q "+"
annotation A "-"
```

with coordinates overlapping.

`how="left", use_strand=True`

Expected exactly one unmatched Q row.

---

# 12. Left mixed match/mismatch

```text
query Q "+"
annotations:
A "-"
B "+"
```

Expected:

```text
Q-B
```

No unmatched Q row.

---

# 13. Different chromosome

No match regardless of strand.

Strand must not create matches where interval/chromosome predicate fails.

---

# 14. Touching intervals

```text
Q [10,20) "+"
A [20,30) "+"
```

No match regardless of same strand.

Half-open interval semantics remain authoritative.

---

# 15. min_overlap + strand pass

Explicit case where both pass.

---

# 16. min_overlap pass / strand fail

Expected no match.

---

# 17. strand pass / min_overlap fail

Expected no match.

---

# 18. min_overlap + strand left reconstruction

A query may have geometrical overlaps but zero rows passing both filters.

Expected exactly one unmatched query row in left mode.

---

# Missing strand column

Explicitly decide API behavior when `use_strand=True` but one or both input DataFrames do not contain a strand field.

Preferred behavior:

Treat missing strand values/columns as canonical unknown strand and therefore produce no stranded matches, rather than crashing or silently disabling strand filtering.

However, inspect existing schema/API assumptions before implementation.

Whatever rule is chosen must:

* be identical for both engines;
* be explicit in SPEC/engine-contract;
* be covered by tests;
* not silently change `use_strand=True` into unstranded mode.

---

# Validation

Canonical explicit strand values other than:

```text
"+"
"-"
missing
```

must not reach backend semantics unnoticed.

Determine whether canonical validation already rejects values such as:

```text
"?"
"*"
"plus"
"1"
```

If it does, add/preserve tests.

If validation is incomplete, add the smallest engine-neutral validation required by the existing canonical contract.

Do not broaden this task into parser redesign.

---

# Backend implementation strategy

## Bedtools

Current BedtoolsEngine may serialize strand into BED6 and call:

```text
-s
```

Do not assume that this should remain the final implementation.

Compare native `-s` behavior against the normative fixtures, especially:

* missing `"."`;
* missing strand column;
* left unmatched behavior;
* composition with `min_overlap`.

If native `-s` exactly satisfies the contract, it may be retained.

If it introduces backend-specific behavior, prefer ordinary overlap + shared canonical strand filtering.

Avoid redundant native + post filtering unless justified.

---

# Polars-Bio

Inspect pinned Polars-Bio 0.35.1 strand capabilities.

Do not invent behavior from latest docs.

If no exact equivalent exists, use ordinary canonical overlaps and the same shared strand predicate.

Keep Task 4 coordinate-system isolation intact.

Do not mutate global Polars-Bio state.

---

# Ordering and metadata

Strand filtering removes non-qualifying rows only.

It MUST NOT alter:

* query input order;
* annotation input order;
* duplicate multiplicity;
* metadata values;
* metadata dtypes;
* canonical column order.

Do not sort by strand.

---

# Error behavior

A valid stranded search with zero qualifying rows is biological no-match.

It is NOT an error.

Malformed canonical strand values are validation errors.

Backend failures still propagate according to Tasks 4–5.

Keep these distinct.

---

# UI behavior

Do not redesign the UI.

Inspect how the existing `use_strand` option is exposed.

If the current UI already passes a boolean correctly, no UI change is needed.

If copy/help text incorrectly describes the semantics, update text minimally.

Do not introduce new strand controls.

---

# Documentation changes

Task 6B resolves a normative ambiguity.

Update at minimum:

* `SPEC.md`
* `docs/engine-contract.md`
* `docs/implementation-notes.md`
* `PLAN.md`

Document explicitly:

```text
use_strand=False:
strand ignored

use_strand=True:
both rows must have explicit + or -
and the strands must be equal
```

Also document:

* missing/unknown strand is not wildcard;
* unknown-vs-unknown is not a match;
* strand composes with `min_overlap` by logical AND;
* left mode treats geometrical-but-wrong-strand overlap as unmatched.

Correct any stale pre-Task-6B docstrings claiming engines lack strand support.

---

# Explicit non-goals

Do NOT implement:

* opposite-strand mode;
* strand wildcard mode;
* `contains`;
* `within`;
* final closest/nearest semantics;
* strand-specific distance semantics;
* transcript-aware orientation logic;
* paired-end orientation;
* feature-direction transformations;
* parser redesign;
* UI redesign;
* new dependencies;
* performance benchmarking.

Only same-strand qualification for the existing boolean `use_strand`.

---

# Review loop

Use two independent Pi subagent reviewers if available.

## Reviewer 1 — genomic semantics

Check:

* `+`/`+`;
* `-`/`-`;
* opposite strands;
* missing strand;
* `"."`;
* unknown-vs-unknown;
* half-open boundaries unchanged;
* left semantics;
* composition with min_overlap.

## Reviewer 2 — implementation quality

Check:

* same rule for both engines;
* no accidental backend-specific semantics;
* row identity/order;
* metadata preservation;
* no global state;
* validation;
* no Task 6C+ scope creep;
* stale strand documentation removed.

Resolve all BLOCKER/MAJOR findings.

---

# Acceptance criteria

Task 6B is complete only when:

1. `use_strand=False` explicitly means strand ignored;
2. `use_strand=True` requires explicit same strand;
3. `+`/`+` passes;
4. `-`/`-` passes;
5. opposite strands fail;
6. missing query strand fails in stranded mode;
7. missing annotation strand fails;
8. both missing fail;
9. `"."` is not treated as wildcard;
10. missing strand-column behavior is explicit and backend-independent;
11. duplicates/multiplicity preserved;
12. left mismatch becomes exactly one unmatched row when no qualifying annotation exists;
13. mixed same/opposite annotation case returns only qualifying matches;
14. half-open boundaries unchanged;
15. strand and `min_overlap` compose with logical AND;
16. metadata preserved;
17. deterministic ordering preserved;
18. Bedtools independently satisfies explicit expected fixtures;
19. Polars-Bio independently satisfies the same fixtures;
20. differential parity passes;
21. normative documentation updated;
22. stale strand documentation corrected;
23. no contains/within/closest semantics implemented;
24. full suite has zero unexpected FAIL/XPASS.

---

# Final verification

Before completion:

1. inspect full diff vs `origin/main`;
2. run focused strand contract tests;
3. run Bedtools strand parity;
4. run Polars-Bio strand parity;
5. run differential strand parity;
6. run combined `strand + min_overlap` tests;
7. run full parity suite;
8. run full repository suite twice;
9. report exact PASS/XFAIL/XPASS/FAIL/SKIP;
10. manually inspect missing-strand left cases;
11. verify no contains/within/closest production changes;
12. verify docs and implementation agree exactly.

---

# Git discipline

Use:

`task-6b-strand-semantics`

Prefer logical commits such as:

```text
test: define strand-aware matching contract
feat: implement backend-independent same-strand filtering
docs: lock down strand semantics
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
* final `use_strand` definition;
* missing/unknown-strand policy;
* implementation architecture;
* Bedtools implementation strategy;
* Polars-Bio implementation strategy;
* interaction with `min_overlap`;
* inner behavior;
* left behavior;
* duplicate/multiplicity behavior;
* exact focused test counts;
* exact full parity counts;
* exact repository-wide PASS/XFAIL/XPASS/FAIL/SKIP;
* reviewer findings and resolutions;
* SPEC/engine-contract changes;
* acceptance criteria status one by one;
* remaining Task 6C–6E backlog;
* explicit confirmation that contains/within/closest semantics were not implemented.

Do not begin Task 6C.
