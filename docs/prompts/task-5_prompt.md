You are working on **AnnotateR**.

Tasks 1, 2, 2.5, 3, and 4 are complete and merged.

Implement **Task 5 only: Bedtools contract cleanup and closure of the remaining parity deviations**.

Task 4 eliminated all Polars-Bio xfails and brought PolarsBioEngine into compliance with the currently covered canonical contract.

The full suite now has exactly **5 strict xfails**, all attributed to known Bedtools-side deviations B1–B5.

Your job is to remove those remaining Bedtools deviations without changing the canonical contract or starting the extended semantic work scheduled for Task 6.

---

# Start state

Start from the current clean `main` after Task 4 has been merged and CI has passed.

Before editing:

1. `git fetch origin`
2. fast-forward local `main`
3. verify `main == origin/main`
4. verify working tree clean
5. create:

`task-5-bedtools-contract-cleanup`

Do not work directly on `main`.

---

# Mandatory reading

Read in this order:

1. `AGENTS.md`
2. `SPEC.md`
3. `PLAN.md`
4. `docs/architecture.md`
5. `docs/engine-contract.md`
6. `docs/references.md`
7. `docs/implementation-notes.md`
8. `streamlit_app/core/schema.py`
9. `streamlit_app/core/normalization.py`
10. `streamlit_app/core/annotator.py`
11. complete `tests/parity/`
12. `tests/test_engine_contract.py`
13. `tests/test_polars_bio_engine.py`

Treat `SPEC.md` and `docs/engine-contract.md` as normative.

Do not redefine the contract to match current Bedtools quirks.

---

# Current known remaining deviations

Task 3/4 identified the remaining Bedtools issues:

## B1 — empty-input left behavior

BedtoolsEngine drops or mishandles query rows in left mode when one side is empty.

The canonical contract requires:

* all query rows preserved in left mode;
* exactly one unmatched result row per unmatched query input row;
* unmatched annotation fields canonical missing;
* `has_overlap=False`.

## B2 — missing metadata sentinel leakage

Bedtools raw left output may expose sentinel values such as:

```text
.
```

where AnnotateR requires canonical missing values.

Sentinel values must not leak into canonical output.

## B3 — lossy metadata round-trip / retyping

Bedtools temporary-file serialization/deserialization may change metadata types, for example:

```text
string "1"
→ numeric 1.0
```

or otherwise lose exact user metadata representation.

The canonical contract requires deterministic metadata preservation.

## B4 — raw Bedtools left sentinels

Raw `bedtools intersect -loj` style sentinels such as:

```text
.
-1
```

must be adapted to the canonical missing-value representation before public output.

This overlaps with B2 but must be handled structurally rather than with brittle value heuristics.

## B5 — `to_dataframe()` failure swallowing

Current Bedtools execution may catch pybedtools/Pandas conversion failures and return an empty DataFrame.

This violates the error contract:

```text
backend/conversion failure
!=
valid biological no-match
```

---

# Goal

Bring `BedtoolsEngine` into compliance with the same canonical result contract already satisfied by `PolarsBioEngine` for the covered Task 3/4 parity surface.

At the end of Task 5:

* all 5 remaining strict xfails should be removed because the underlying deviations are actually fixed;
* Bedtools and Polars-Bio should both pass the same ordinary overlap, left, metadata, ordering, boundary, and error-contract tests;
* no backend-specific sentinels or temp-file artifacts should leak into canonical output;
* genuine Bedtools/pybedtools conversion failures must propagate.

---

# Required implementation order

## 1. Reproduce all 5 xfails individually

Before editing production code:

* run each remaining Bedtools xfail independently;
* confirm the exact current failure mode;
* inspect the raw Bedtools/pybedtools result for that case;
* record which layer introduces the deviation:

```text
canonical input
→ temp serialization
→ bedtools
→ pybedtools result
→ dataframe conversion
→ AnnotateR adapter
→ canonicalizer
```

Do not fix anything until you can attribute each deviation.

---

# 2. Fix B1 — empty-input left semantics

BedtoolsEngine must obey canonical left semantics even when:

* annotation input is empty;
* query input is empty;
* both are empty.

For left mode:

* empty query input → empty result;
* non-empty query + empty annotation → one unmatched canonical row per query input row;
* duplicate query rows remain distinct;
* query metadata preserved exactly.

Do not invoke Bedtools unnecessarily if a deterministic canonical result can be produced before the external call.

A small explicit empty-input guard is preferable to relying on undocumented Bedtools/pybedtools behavior.

Do not use biological-value equality to reconstruct identity.

Preserve input row identity explicitly.

---

# 3. Preserve metadata through Bedtools safely

The Bedtools backend uses text serialization as an interoperability boundary.

That boundary must not silently alter metadata semantics.

Design a deterministic round-trip strategy.

Requirements:

* query and annotation metadata preserved;
* missing values preserved as canonical missing after adaptation;
* numeric-looking strings must not silently become numeric unless the canonical schema explicitly requires it;
* booleans/strings/numbers should remain semantically stable;
* duplicate rows remain distinct;
* metadata column order preserved.

Do not depend on Pandas type inference for arbitrary metadata columns if it can corrupt original representation.

Prefer one explicit serialization/deserialization policy.

---

# 4. Fix B2/B4 — canonicalize Bedtools sentinels structurally

Do not globally replace every:

```text
"."
"-1"
```

because those may be legitimate user metadata values.

Distinguish:

* Bedtools-generated sentinel fields for unmatched annotation coordinates/fields;
* actual user metadata containing `"."` or `"-1"`.

Use row identity / known Bedtools output layout / `has_overlap` determination rather than blind global replacement.

For unmatched rows:

* `annot_chr = pd.NA`
* `annot_start = pd.NA`
* `annot_end = pd.NA`
* all `annot_*` metadata = pd.NA
* `has_overlap = False`

For matched rows:

* legitimate annotation metadata values must survive unchanged.

Add regression tests proving that a real user metadata value `"."` remains `"."` on a matched row.

---

# 5. Fix B3 — prevent lossy retyping

Add focused tests with metadata deliberately chosen to catch inference problems:

Query metadata examples:

```text
"00123"
"1"
"1.0"
"NA"
"."
"-1"
True
False
```

Annotation metadata should include equivalent cases.

Verify canonical results preserve intended values/types according to the Task 2 schema policy.

Do not broaden the canonical schema to `object` everywhere merely to avoid thinking about types.

Use explicit metadata handling at the Bedtools boundary.

If exact dtype preservation for heterogeneous arbitrary user metadata is impossible through the current Bedtools text representation, define and document the narrowest deterministic rule consistent with the existing canonical contract.

Do not silently accept lossy behavior.

---

# 6. Fix B5 — propagate conversion/backend errors

Remove broad exception handling around:

* Bedtools execution;
* pybedtools result conversion;
* `to_dataframe()`;

where it converts failure into an empty DataFrame.

Valid no-match must remain a normal empty result.

Actual failure must raise.

If wrapping exceptions:

* use an existing project exception if appropriate;
* preserve the original exception as cause;
* add useful operation context;
* do not replace detailed failures with generic messages.

Add/retain a deterministic regression test that demonstrates conversion failure is distinguishable from a valid zero-match result.

Do not rely on random filesystem or external process failures.

---

# 7. Keep Bedtools output adaptation explicit

The Bedtools backend should have one clear adaptation path from raw external output to canonical AnnotateR output.

Do not distribute cleanup logic across:

* parser;
* UI;
* canonicalizer;
* parity-test utility.

The adapter should know:

* query schema;
* annotation schema;
* expected Bedtools output layout;
* internal row IDs;
* whether a row is matched/unmatched.

Then `canonicalize_annotation_result()` should validate the already-correctly-mapped result.

Do not use the canonicalizer to hide malformed mapping.

---

# 8. Preserve deterministic ordering

Bedtools output order must be normalized to the canonical rule established in Task 2/3.

Use explicit row identity.

Test:

* duplicate queries;
* duplicate annotations;
* one-to-many;
* many-to-many;
* unmatched duplicates in left mode.

Do not coordinate-sort as a substitute for input identity.

---

# 9. Remove xfails one at a time

For each B1–B5 deviation:

1. run the targeted failing test;
2. implement the minimal fix;
3. observe XPASS because xfail is strict;
4. inspect why it now passes;
5. remove that xfail marker only;
6. rerun relevant parity subsets.

Do not delete all five markers in one mechanical sweep.

At the end, there should be **zero Bedtools xfails** on the currently normative parity surface.

---

# 10. Keep Polars-Bio stable

Task 4 is complete.

Do not refactor `PolarsBioEngine` unless a shared engine-neutral change is strictly necessary.

Any shared change must be tested against both engines.

The expected result after Task 5 is:

```text
BedtoolsEngine     PASS
PolarsBioEngine    PASS
```

for the entire Task 3/4 parity surface.

---

# 11. Do not start Task 6

The following remain outside Task 5 unless already normative and already covered by the existing parity contract:

* contains;
* within;
* min_overlap expansion;
* strand semantics expansion;
* closest/nearest full semantic parity;
* performance tuning;
* UI redesign.

In particular, the known `contains/within` placeholder behavior belongs to Task 6.

Do not “fix it while you're here.”

---

# Focused regression tests

Add new Bedtools-specific unit tests only where they isolate boundary risks not already expressed by the parity suite.

Good candidates:

* empty annotation + left;
* sentinel-vs-real-dot distinction;
* numeric-looking string metadata;
* duplicate unmatched rows;
* `to_dataframe()` failure propagation;
* helper row-ID cleanup.

Avoid duplicating the complete parity matrix.

---

# Documentation

Update:

* `docs/implementation-notes.md`
* `PLAN.md` status if that is repository convention

Document:

* Bedtools adapter strategy;
* metadata round-trip policy;
* sentinel handling;
* error propagation behavior;
* closure of B1–B5.

Also update any stale statement saying those issues remain unresolved.

Do not rewrite SPEC unless a genuine normative ambiguity is discovered.

---

# Review loop

Use two independent Pi subagent reviews if available.

Reviewer 1 — contract/genomic semantics:

Check:

* left semantics with empty inputs;
* duplicate preservation;
* matched vs unmatched sentinel handling;
* half-open interval behavior unchanged;
* deterministic ordering;
* no canonical schema drift.

Reviewer 2 — serialization/error handling:

Check:

* metadata round-trip;
* numeric-looking strings;
* real `"."` / `"-1"` metadata;
* dtype stability;
* exception propagation;
* no broad `try/except`;
* no temp/internal columns leaking.

Classify:

* BLOCKER
* MAJOR
* MINOR
* NOTE

Resolve all BLOCKER and MAJOR findings.

---

# Acceptance criteria

Task 5 is complete only when:

1. B1 fixed;
2. B2 fixed;
3. B3 fixed;
4. B4 fixed;
5. B5 fixed;
6. no remaining Bedtools strict xfails on the Task 3 parity surface;
7. Polars-Bio remains fully passing;
8. empty query/annotation matrices behave canonically;
9. left mode preserves each unmatched query exactly once;
10. duplicate/multiplicity semantics remain correct;
11. user metadata `"."`/`"-1"` is distinguishable from Bedtools sentinels;
12. numeric-looking strings are not silently retyped;
13. backend/conversion failures propagate;
14. valid no-match remains distinguishable from failure;
15. no backend-private/internal columns leak;
16. deterministic canonical ordering holds;
17. canonical schema unchanged;
18. parser/normalization behavior unchanged;
19. no Task 6 semantic expansion was implemented;
20. full suite has no unexpected FAIL/XPASS.

---

# Final verification

Before completion:

1. inspect full diff vs `origin/main`;
2. verify `PolarsBioEngine` has not been unnecessarily changed;
3. verify parser/normalization files unchanged unless explicitly justified;
4. run each former B1–B5 xfail individually;
5. run complete Bedtools parity suite;
6. run full parity suite;
7. run full repository suite twice;
8. report exact:

   * PASS
   * XFAIL
   * XPASS
   * FAIL
   * SKIP
9. confirm no xfail remains for Bedtools on the covered contract;
10. inspect canonical output for real metadata values `"."`, `"-1"`, `"00123"`;
11. verify deliberate conversion failure raises;
12. inspect docs for stale B1–B5 statements.

---

# Git discipline

Use one Task 5 branch:

`task-5-bedtools-contract-cleanup`

Prefer logical commits such as:

```text
fix: preserve bedtools left semantics for empty inputs
fix: make bedtools metadata round-trip lossless
fix: propagate bedtools conversion failures
test: retire resolved bedtools parity xfails
docs: close remaining engine deviations
```

Do not manufacture unnecessary commits.

Open the PR only after review findings are resolved.

Do not merge automatically unless that is the repository workflow.

---

# Final report

Return:

* branch;
* base commit;
* commits;
* files changed;
* B1 resolution;
* B2 resolution;
* B3 resolution;
* B4 resolution;
* B5 resolution;
* exact Bedtools adapter/serialization strategy;
* empty-input strategy;
* sentinel-handling strategy;
* metadata type-preservation strategy;
* error-propagation strategy;
* xfails removed;
* remaining xfails, if any, with justification;
* exact focused Bedtools parity counts;
* exact full parity counts;
* exact repository-wide PASS/XFAIL/XPASS/FAIL/SKIP counts;
* reviewer findings and resolutions;
* acceptance criteria status one by one;
* Task 6 backlog;
* explicit confirmation that Task 6 was not started.
