You are working on **AnnotateR**.

Tasks 1–5 are complete and merged.

Begin **Task 6 — Extended interval semantics**, but implement **Task 6A only: `min_overlap`**.

Do not implement strand-aware matching, contains, within, or closest semantics in this PR.

The purpose of Task 6A is to define, document, test, and implement one backend-independent meaning for AnnotateR's existing `min_overlap` parameter.

---

# Start state

Start from the current clean `main` after Task 5 has been merged and CI has passed.

Before editing:

1. `git fetch origin`
2. fast-forward local `main`
3. verify `main == origin/main`
4. verify working tree clean
5. create:

`task-6a-min-overlap-semantics`

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
11. focused Bedtools and Polars-Bio engine tests

Consult the pinned/version-matched primary documentation for:

* Bedtools `intersect -f/-F/-r/-e`;
* Polars-Bio 0.35.1 overlap behavior.

Do not infer semantics from the parameter name alone.

---

# Normative decision for Task 6A

AnnotateR's single `min_overlap` parameter SHALL mean:

> **minimum fraction of the query interval that must be covered by one annotation interval for that query/annotation pair to qualify as a match.**

It applies to the **query interval only**.

It is NOT:

* fraction of the annotation;
* reciprocal overlap;
* either-side overlap;
* total coverage accumulated across multiple annotation rows.

For a query interval `Q=[q_start,q_end)` and annotation interval `A=[a_start,a_end)`:

```text
overlap_length =
    max(
        0,
        min(q_end, a_end) - max(q_start, a_start)
    )

query_length =
    q_end - q_start

query_overlap_fraction =
    overlap_length / query_length
```

The pair qualifies iff:

```text
overlap_length > 0

AND

query_overlap_fraction >= min_overlap
```

Coordinates are canonical **0-based half-open** intervals.

Each query/annotation pair is evaluated independently.

Multiple annotations MUST NOT have their coverage summed to satisfy the threshold.

---

# Parameter contract

`min_overlap` may be:

```text
None
```

meaning ordinary overlap with no fractional threshold,

or a numeric value in:

```text
0.0 <= min_overlap <= 1.0
```

Define and test validation explicitly.

Recommended behavior:

* `None` → ordinary overlap;
* `0.0` → equivalent to ordinary positive overlap;
* `1.0` → the query must be fully contained within a single annotation interval;
* negative values → error;
* values > 1 → error;
* NaN → error;
* ±infinity → error;
* boolean values should not silently be accepted as numeric fractions.

Use one consistent exception type appropriate to the existing public API.

Do not silently clamp invalid values.

---

# Important distinction from `contains` / `within`

Do not conflate Task 6A with Task 6C/6D.

For example:

```text
query      [10,20)
annotation [5,20)
min_overlap=1.0
```

qualifies because 100% of the **query** is covered.

That happens to resemble query-within-annotation for this pair, but `min_overlap` remains a fractional-overlap operation.

`contains` and `within` still require their own explicit predicates and later tasks.

Do not implement them here.

---

# Important distinction from reciprocal overlap

Example:

```text
query      [10,20)     length 10
annotation [10,110)    length 100
```

Overlap length = 10.

Therefore:

```text
query fraction = 10 / 10 = 1.0
```

and the pair qualifies for:

```text
min_overlap = 1.0
```

even though only 10% of the annotation is covered.

That is intentional.

AnnotateR's `min_overlap` is query-relative, not reciprocal.

Add a regression test for this distinction.

---

# Primary architectural goal

The semantic definition must live at the AnnotateR contract level.

Both engines must satisfy:

```text
same canonical inputs
+ same min_overlap
→ same canonical results
```

Do not allow backend-specific definitions such as:

```text
Bedtools → -f
Polars-Bio → whatever the library happens to call min overlap
```

unless those implementations are demonstrated to satisfy the exact same contract.

Backend mechanisms are implementation details.

---

# Preferred implementation strategy

First evaluate whether `min_overlap` can be implemented safely as a **shared canonical post-filter** over ordinary overlap pairs.

This is likely preferable because it:

* makes the semantic rule backend-independent;
* avoids reliance on subtly different backend fraction options;
* keeps Bedtools and Polars-Bio behavior identical;
* allows direct testing from canonical coordinates.

A sensible architecture is:

```text
canonical inputs
      ↓
ordinary backend overlap
      ↓
canonical matched pairs
      ↓
shared AnnotateR min_overlap filter
      ↓
left reconstruction if required
      ↓
canonical output
```

However, do not force this architecture if inspection demonstrates a cleaner equivalent solution.

Whatever implementation you choose, prove backend parity with tests.

---

# Left-mode semantics

This is critical.

For:

```text
how="left"
```

the threshold is part of determining whether the query has a qualifying match.

Example:

```text
query Q1
annotation A1 overlaps Q1
but overlap fraction < min_overlap
```

Then for AnnotateR left mode, Q1 is considered **unmatched** unless some other annotation passes the threshold.

Therefore:

* if zero annotation rows pass the threshold:

  * emit exactly one unmatched row for that query;
  * `has_overlap=False`;
  * all annotation fields canonical missing;
* if one annotation passes:

  * emit that matched row only;
* if multiple annotations individually pass:

  * emit each passing match;
* failing annotation rows are not emitted.

Do not produce both:

```text
failed matched row
+
unmatched row
```

for the same query.

Duplicate query identity must remain preserved.

---

# Required explicit fixtures

Build contract/parity tests before or alongside implementation.

At minimum include the following.

## 1. Exact full overlap

```text
query      [10,20) length 10
annotation [10,20) overlap 10
fraction = 1.0
```

Must pass thresholds:

* 0
* 0.5
* 1.0

---

## 2. Exactly half overlap

```text
query      [10,20) length 10
annotation [15,25) overlap 5
fraction = 0.5
```

Expected:

```text
min_overlap=0.49 → match
min_overlap=0.50 → match
min_overlap=0.51 → no match
```

The equality case verifies `>=`, not `>`.

---

## 3. One-base overlap

```text
query      [10,20) length 10
annotation [19,30) overlap 1
fraction = 0.1
```

Expected:

```text
0.10 → match
>0.10 → no match
```

---

## 4. Touching intervals

```text
query      [10,20)
annotation [20,30)
```

Overlap = 0.

No match even when:

```text
min_overlap=0.0
```

`min_overlap=0` must not turn touching intervals into matches.

Ordinary positive overlap remains required.

---

## 5. Annotation larger than query

```text
query      [10,20)
annotation [0,100)
```

Fraction of query = 1.0.

Must match at threshold 1.0.

This demonstrates query-relative semantics.

---

## 6. Query larger than annotation

```text
query      [0,100)
annotation [10,20)
```

Overlap = 10.

Fraction of query = 0.1.

Expected:

```text
0.1 → match
0.11 → no match
```

---

## 7. Reciprocal distinction

Explicitly show that annotation coverage is irrelevant.

Example:

```text
query      length 10
annotation length 100
overlap    10
```

`min_overlap=1.0` → match.

Do not accidentally implement Bedtools `-r`.

---

## 8. Multiple annotation rows must not aggregate

Example:

```text
query [0,100)

annotation A [0,30)   fraction .30
annotation B [30,60)  fraction .30
```

At:

```text
min_overlap=0.5
```

neither qualifies.

Do NOT sum `.30 + .30`.

Inner result must contain zero rows.

Left result must contain exactly one unmatched query row.

---

## 9. One qualifying and one failing annotation

Example:

```text
query [0,100)

A overlap = 25%
B overlap = 75%
threshold = 50%
```

Output contains only B.

No unmatched row.

---

## 10. Multiple qualifying annotations

Both qualifying matches must remain.

Preserve multiplicity and deterministic annotation input order.

---

## 11. Duplicate queries

Identical biological query rows with different row identity must be handled independently.

Left reconstruction must preserve both.

---

## 12. Duplicate annotations

Duplicate qualifying annotations must produce duplicate result rows according to input multiplicity.

No deduplication.

---

## 13. Metadata

Verify metadata remains byte/semantically identical through threshold filtering.

The new semantic filter must not:

* change metadata dtypes unnecessarily;
* reorder metadata columns;
* alter missing values;
* leak helper columns.

---

# Validation tests

Test invalid thresholds:

```text
-0.01
1.01
NaN
+inf
-inf
True
False
```

Decide whether integer `0` / `1` are acceptable numeric equivalents and document the choice.

Do not let Bedtools or Polars-Bio perform validation differently.

Validation should happen before backend execution where practical.

Add a test demonstrating invalid `min_overlap` does not invoke either backend.

---

# Backend parity requirements

Run the same contract fixtures against:

```text
BedtoolsEngine
PolarsBioEngine
```

Both must independently satisfy explicit expected results.

Also include differential comparison.

Do not use Bedtools output as the oracle.

Do not xfail a backend merely because its native API implements a different fraction model.

Adapt the engine or use the shared canonical implementation.

---

# Bedtools implementation

Current historical behavior maps `min_overlap` to:

```text
bedtools intersect -f
```

Do not preserve this mechanically just because it exists.

Determine whether using native `-f` remains appropriate under the new architecture.

If using `-f`:

* verify exact parity against the explicit mathematical fixtures;
* ensure left reconstruction behaves correctly after thresholding;
* ensure validation is shared.

If a shared post-filter gives a simpler and more backend-independent implementation, prefer that.

Avoid applying both native filtering and canonical filtering redundantly unless there is a demonstrated reason.

---

# Polars-Bio implementation

Do not invent Polars-Bio semantics from API names.

Use ordinary canonical overlap pairs and enforce AnnotateR's query-fraction contract explicitly unless pinned Polars-Bio 0.35.1 provides a mechanism proven to be exactly equivalent.

Keep:

```text
coordinate_system_zero_based=True
```

behavior intact.

Do not reintroduce global configuration.

---

# Error behavior

Invalid threshold:

```text
→ explicit validation error
```

Backend failure:

```text
→ propagated backend error
```

Valid zero qualifying matches:

```text
→ valid empty result for inner
→ canonical unmatched row(s) for left
```

These three cases must remain distinguishable.

---

# Canonical ordering

After filtering:

```text
query input order
→ annotation input order among qualifying matches
```

must remain unchanged.

Do not re-sort by:

* overlap fraction;
* overlap length;
* genomic position.

Threshold filtering removes rows only.

It does not redefine ordering.

---

# Documentation changes

Update the normative documentation because Task 6A resolves a previously explicit ambiguity.

At minimum update:

* `SPEC.md`
* `docs/engine-contract.md`
* `docs/implementation-notes.md`
* `PLAN.md` status/progress according to repository convention

`SPEC.md` should no longer say the single `min_overlap` parameter is ambiguous after this task.

Record explicitly:

> `min_overlap` is the minimum fraction of the canonical query interval covered by a single annotation interval.

Also record:

* inclusive threshold comparison (`>=`);
* valid domain `[0,1]`;
* ordinary positive overlap still required;
* no reciprocal requirement;
* no aggregation across annotation rows.

This is a genuine normative contract change/clarification and belongs in SPEC.

---

# Explicit non-goals

Do NOT implement in Task 6A:

* `use_strand=True` semantics;
* contains;
* within;
* closest/nearest final semantics;
* reciprocal overlap option;
* annotation-relative minimum fraction;
* “either side” fraction semantics;
* aggregation of coverage across multiple annotations;
* UI redesign;
* performance benchmarking;
* new dependency upgrades;
* parser changes;
* canonical coordinate changes.

Do not add new user-facing knobs for:

```text
query_fraction
annotation_fraction
reciprocal
```

Task 6A defines the existing single parameter only.

---

# Review loop

Use independent Pi subagents if available.

## Reviewer 1 — genomic semantics

Ask them specifically to verify:

* half-open overlap arithmetic;
* denominator is query length;
* equality threshold uses `>=`;
* touching intervals never match;
* one-base boundary cases;
* no aggregation across annotations;
* reciprocal distinction;
* left semantics after filtering.

## Reviewer 2 — implementation/test quality

Ask them to verify:

* both engines use exactly one contract;
* invalid values rejected before backend invocation;
* no duplicate reconstruction bugs;
* ordering preserved;
* no metadata corruption;
* no hidden Bedtools-specific definition;
* no Task 6B+ scope creep.

Resolve all BLOCKER and MAJOR findings.

---

# Acceptance criteria

Task 6A is complete only when:

1. `min_overlap` has one explicit backend-independent normative definition;
2. the denominator is the query interval length;
3. comparison is `fraction >= min_overlap`;
4. valid domain is explicitly tested/documented;
5. touching intervals remain non-matches at `min_overlap=0`;
6. full, half, one-base, and boundary overlaps are tested;
7. annotation-size asymmetry is tested;
8. reciprocal behavior is explicitly excluded/tested;
9. overlap from multiple annotation rows is not aggregated;
10. inner semantics are correct;
11. left semantics after filtering are correct;
12. duplicates/multiplicity are preserved;
13. deterministic ordering is preserved;
14. metadata is preserved;
15. both engines independently pass the same expected fixtures;
16. differential parity passes;
17. invalid thresholds do not silently reach backend-specific behavior;
18. SPEC ambiguity is resolved and documentation updated;
19. no Task 6B/6C/6D/6E feature was implemented;
20. full repository suite has zero unexpected FAIL/XPASS.

---

# Final verification

Before completion:

1. inspect full diff vs `origin/main`;
2. run focused min-overlap contract tests;
3. run Bedtools min-overlap parity;
4. run Polars-Bio min-overlap parity;
5. run differential min-overlap parity;
6. run full parity suite;
7. run full repository test suite twice;
8. report exact:

   * PASS
   * XFAIL
   * XPASS
   * FAIL
   * SKIP
9. manually inspect threshold equality cases;
10. manually inspect left-mode zero-qualifying-match case;
11. verify no strand/contains/within/closest production changes;
12. verify normative docs match implementation exactly.

---

# Git discipline

Use:

`task-6a-min-overlap-semantics`

Prefer logical commits such as:

```text
test: define minimum query-overlap contract
feat: implement backend-independent min-overlap filtering
docs: lock down min-overlap semantics
```

Do not manufacture commits unnecessarily.

Open the PR only after independent review findings are resolved.

Do not merge automatically unless that is the established repository workflow.

---

# Final report

Return:

* branch;
* base commit;
* commits;
* files changed;
* final mathematical `min_overlap` definition;
* validation policy;
* implementation architecture;
* Bedtools implementation strategy;
* Polars-Bio implementation strategy;
* inner behavior;
* left behavior;
* duplicate/multiplicity behavior;
* exact focused test counts;
* exact full parity counts;
* exact repository-wide PASS/XFAIL/XPASS/FAIL/SKIP;
* reviewer findings and resolutions;
* SPEC/engine-contract changes;
* acceptance criteria status one by one;
* remaining Task 6B–6E backlog;
* explicit confirmation that strand/contains/within/closest semantics were not implemented.

Do not begin Task 6B.
