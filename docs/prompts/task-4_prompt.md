You are working on **AnnotateR**.

Tasks 1, 2, 2.5, and 3 are complete and merged.

Implement **PLAN Task 4 only: make `PolarsBioEngine` satisfy the AnnotateR engine contract for the currently covered parity surface**.

Task 3 established the executable parity harness and the deviation inventory.

Your job is now to remove the known Polars-Bio deviations one by one, preserving the canonical contract and turning justified strict xfails into normal passing tests.

Do not redesign Bedtools behavior in this task unless a shared engine-neutral fix is strictly necessary.

---

# Start state

Start from the current clean `main` after Task 3 / PR #9 has been merged.

Before editing:

1. `git fetch origin`
2. update local `main` with fast-forward only
3. verify `main == origin/main`
4. verify working tree clean
5. create a dedicated branch:

`task-4-polars-bio-contract-compliance`

Do not work directly on `main`.

---

# Mandatory reading

Read in this order:

1. `AGENTS.md`
2. `SPEC.md`
3. `PLAN.md` — Task 4 only
4. `docs/architecture.md`
5. `docs/engine-contract.md`
6. `docs/references.md`
7. `docs/implementation-notes.md`
8. `streamlit_app/core/schema.py`
9. `streamlit_app/core/normalization.py`
10. `streamlit_app/core/annotator.py`
11. the complete `tests/parity/` suite
12. existing `tests/test_engine_contract.py`

Use the pinned environment established by Task 2.5:

* Python 3.12
* Bedtools 2.31.1
* pybedtools 0.12.1
* Polars 1.44.2
* Polars-Bio 0.35.1

For Polars-Bio behavior, consult the version-matched primary references from `docs/references.md`.

Do not rely solely on model memory or latest unversioned docs.

---

# Goal

Make Polars-Bio conform to AnnotateR’s canonical engine contract for the Task 3 parity surface.

The desired flow is:

```text
canonical query dataframe
canonical annotation dataframe
        ↓
PolarsBioEngine
        ↓
raw Polars-Bio result
        ↓
AnnotateR adapter
        ↓
canonical annotation result
```

At the end of Task 4:

* Polars-Bio must consume canonical 0-based half-open intervals correctly;
* raw Polars-Bio output must be adapted deterministically to the canonical result schema;
* internal Polars-Bio/helper artifacts must not leak;
* genuine Polars-Bio backend errors must propagate rather than masquerade as empty biological results;
* every strict xfail whose root cause is fixed must be removed.

---

# Known Task 3 Polars-Bio deviations

Task 3 identified at least:

## P1 — non-canonical Polars result schema

Current non-empty Polars-Bio outputs fail canonicalization because of:

* backend suffixes;
* query/annotation provenance ambiguity;
* `pb_row_id`;
* `_1` / `_2` style columns;
* column naming/order not matching the canonical result schema.

## P2 — wrong coordinate-system interpretation

Polars-Bio 0.35.1 defaults to 1-based closed interval semantics when the coordinate system is not explicitly declared.

AnnotateR canonical intervals are 0-based half-open.

This causes cases such as:

```text
query      [10,20)
annotation [20,25)
```

to be incorrectly reported as overlapping.

## P3 — overlap exception swallowing

Current overlap-related engine code may catch backend exceptions and return an empty DataFrame.

This is prohibited because:

```text
backend failure != biologically valid no-overlap result
```

## P4 — nearest exception swallowing

The same class of issue exists for nearest/closest-related backend invocation.

Task 4 should fix the Polars-Bio-side deviations covered by the current contract.

Do not expand into unrelated Bedtools cleanup.

---

# Required implementation order

Work in this order unless concrete evidence shows a dependency requires a small reordering.

## 1. Fix P1 first — canonical Polars result adapter

Do not patch test expectations around raw Polars-Bio output.

Introduce or refactor one clear adapter boundary that maps Polars-Bio output into the canonical AnnotateR result contract.

The adapter must use explicit knowledge of the input schemas and configured Polars-Bio suffix behavior.

Do not infer query-vs-annotation provenance from vague suffix heuristics if explicit mapping can be used.

Prefer deterministic configuration such as explicit suffixes in the Polars-Bio call where supported.

The adapter must produce the canonical core columns:

```text
coord_chr
coord_start
coord_end
annot_chr
annot_start
annot_end
has_overlap
```

plus deterministic metadata provenance:

```text
coord_<query_metadata>
annot_<annotation_metadata>
```

It must remove internal/backend artifacts such as:

* `pb_row_id`
* `_1`
* `_2`
* `_right`
* temporary row-identity helpers

unless a helper is still required internally before final canonicalization.

No backend-private column may remain in the public canonical output.

---

# 2. Preserve row identity explicitly

Do not reconstruct result ordering by genomic coordinate sorting.

The canonical contract uses input identity/order.

Introduce stable query and annotation row identities internally as needed.

These IDs must:

* survive backend processing sufficiently to reconstruct output;
* preserve duplicate query rows;
* preserve duplicate annotation rows;
* preserve multiplicity for one-to-many and many-to-many overlaps;
* never appear in the final canonical result.

For left-mode reconstruction, unmatched duplicate queries must remain distinct input rows even when all biological fields are identical.

---

# 3. Fix P2 — explicitly configure Polars-Bio coordinate semantics

Polars-Bio must be invoked in a way that interprets AnnotateR canonical intervals as:

```text
0-based half-open
```

Use the official Polars-Bio 0.35.1 mechanism documented in project references.

Task 2.5 empirically verified that:

```python
pb.set_option("datafusion.bio.coordinate_system_zero_based", True)
```

restores correct half-open behavior.

However, do not blindly mutate global library state without considering isolation.

Evaluate the narrowest safe mechanism supported by Polars-Bio.

Requirements:

* AnnotateR calls must use correct coordinate semantics;
* tests must not depend on execution order;
* one test changing Polars-Bio options must not poison another test;
* behavior must remain deterministic across repeated runs.

If the Polars-Bio API only exposes global configuration, isolate/reset it appropriately and document the constraint.

Add/retain a regression test specifically for touching half-open intervals.

---

# 4. Implement correct inner-overlap adaptation

For inner mode:

* emit only query/annotation match rows;
* preserve query input order;
* preserve annotation input order within each query according to the canonical contract;
* preserve multiplicity;
* preserve metadata;
* set `has_overlap=True`;
* return zero rows for genuine no-match input;
* distinguish zero rows from backend failure.

All Task 3 inner-overlap xfails attributable to P1/P2 should become PASS.

Remove corresponding `xfail` markers once fixed.

Do not leave an xfail on a passing case.

---

# 5. Implement AnnotateR left semantics

Do not assume Polars-Bio `overlap_output="left"` means AnnotateR left-outer semantics.

AnnotateR left mode requires:

* all query rows preserved;
* matched queries may emit multiple rows;
* unmatched queries emit exactly one row;
* unmatched annotation fields are canonical missing values;
* `has_overlap=False` on unmatched rows;
* duplicate unmatched query inputs remain distinct;
* deterministic query input order.

If Polars-Bio does not directly provide this semantics, reconstruct it explicitly using stable query identity.

The reconstruction should conceptually be:

```text
all canonical queries
        +
matched overlap rows
        ↓
identify query IDs with no matches
        ↓
append exactly one canonical unmatched row per unmatched query ID
        ↓
restore deterministic canonical ordering
```

Do not infer unmatched rows from biological-value equality.

---

# 6. Fix P3 — propagate overlap backend errors

Remove broad exception swallowing around Polars-Bio overlap execution.

Do not convert:

```text
backend exception
```

into:

```text
empty DataFrame
```

unless the backend explicitly returns an empty but valid result without raising.

Use a project-specific exception only if the repository already has an appropriate exception abstraction and wrapping adds useful context.

If wrapping:

* preserve the original exception as cause;
* do not erase diagnostic information.

Tests must distinguish:

* valid no-match;
* malformed/invalid invocation;
* backend failure.

---

# 7. Fix P4 — propagate nearest backend errors

Apply the same principle to the Polars-Bio nearest/closest path.

Do not redesign full nearest semantics beyond what is already specified/tested.

This task should remove exception swallowing and satisfy existing contract coverage.

If nearest parity itself belongs to a later task, keep the implementation change limited to error propagation and currently normative behavior.

---

# 8. Canonicalize only at the proper boundary

Do not spread canonical output naming logic across:

* parser;
* UI;
* backend call;
* test utilities.

The engine should have one clear result-adaptation path before returning public output.

Reuse `canonicalize_annotation_result()` where appropriate rather than duplicating schema enforcement.

However, do not abuse the canonicalizer to hide malformed backend mapping.

The adapter must first map the backend result correctly; canonicalization should validate/enforce the contract afterward.

---

# 9. Remove strict xfails incrementally

Use the Task 3 parity harness as the Definition of Done.

After each root-cause fix:

1. run the smallest affected parity subset;
2. observe expected XPASS caused by `strict=True`;
3. inspect why it now passes;
4. remove only the corresponding xfail marker;
5. rerun tests.

Do not remove xfails in bulk merely because counts changed.

Every removed xfail must correspond to a verified fixed deviation.

If fixing P1 exposes a deeper semantic failure previously masked by canonicalization, replace the old xfail reason with the newly identified root cause rather than pretending the case is solved.

---

# 10. Preserve Bedtools behavior

Task 3 also identified Bedtools deviations:

* B1 empty-input left behavior;
* B2/B3 metadata round-trip losses/retyping;
* B4 raw left sentinels;
* B5 `to_dataframe` failure swallowing.

These are not the primary scope of Task 4.

Do not fix them unless:

* a shared engine-neutral canonical-layer defect must be corrected for Polars-Bio compliance;
* and the change does not alter intended Bedtools semantics unexpectedly.

Otherwise leave them as xfails / backlog items for Task 5 or the plan-defined Bedtools cleanup task.

---

# 11. Preserve parser and normalization semantics

Do not change:

* BED/GFF/GTF/VCF parsing;
* canonical coordinate conversion;
* metadata preservation rules;
* result-schema normative definitions

unless Task 4 exposes a genuine contradiction in the Task 2 contract.

If such a contradiction appears, stop and report it rather than silently redefining the contract.

---

# 12. Add focused regression tests where needed

The Task 3 harness should remain the primary acceptance surface.

Add new unit tests only where they isolate implementation-specific risk better than the parity suite.

Useful targeted regression areas may include:

* Polars raw suffix mapping;
* stable row-ID removal;
* duplicate query identity;
* duplicate annotation identity;
* global coordinate-option isolation/reset;
* backend exception propagation.

Avoid duplicating the full parity matrix in engine-unit tests.

---

# Explicit non-goals

Do NOT in Task 4:

* rewrite BedtoolsEngine broadly;
* fix all B1-B5 deviations;
* redesign parsers;
* redesign normalization;
* change canonical scientific semantics;
* implement UI/UX work;
* benchmark performance;
* optimize memory usage;
* add new file formats;
* broadly upgrade dependencies;
* expand the parity matrix unnecessarily;
* weaken parity tests to match implementation;
* treat raw Polars-Bio output as the public API.

---

# Review loop

Use independent Pi subagents if available.

Reviewer 1: genomic/contract correctness.

Ask specifically:

* Are canonical intervals always passed to Polars-Bio as 0-based half-open?
* Are touching intervals correctly non-overlapping?
* Are duplicates/multiplicity preserved?
* Does left mode preserve each unmatched query exactly once?
* Is result ordering based on input identity rather than coordinate sorting?
* Are metadata provenance prefixes correct?
* Do backend-specific artifacts leak?

Reviewer 2: error-handling / implementation quality.

Ask specifically:

* Are exceptions still swallowed?
* Is global Polars-Bio configuration safely isolated?
* Are temporary row IDs collision-safe and removed?
* Are suffix mappings deterministic?
* Are any xfails removed without proving the defect fixed?
* Did any Bedtools or parser behavior change unintentionally?

Classify:

* BLOCKER
* MAJOR
* MINOR
* NOTE

Resolve all BLOCKER/MAJOR findings.

---

# Acceptance criteria

Task 4 is complete only when:

1. Polars-Bio consumes canonical 0-based half-open coordinates correctly;
2. touching intervals no longer produce false overlaps;
3. non-empty Polars overlap results can be converted to canonical output;
4. canonical query/annotation provenance is correct;
5. no backend suffix/helper columns leak;
6. duplicate rows and multiplicity are preserved;
7. inner overlap parity cases covered by Task 3 pass where semantics are implemented;
8. left mode preserves every unmatched query exactly once;
9. canonical missing annotation values are correct;
10. canonical deterministic row ordering is satisfied;
11. overlap backend exceptions propagate;
12. nearest backend exceptions propagate;
13. valid no-match remains distinguishable from backend failure;
14. every fixed strict xfail is removed;
15. any remaining Polars xfails have updated, accurate root-cause reasons;
16. no unrelated Bedtools cleanup was performed;
17. no parser/normalization semantics changed;
18. full parity suite has no unexpected FAIL/XPASS;
19. full repository test suite has no unexpected FAIL/XPASS.

---

# Final verification

Before completion:

1. inspect full diff vs `origin/main`;
2. verify parser/normalization files are unchanged unless explicitly justified;
3. verify BedtoolsEngine has not been broadly refactored;
4. run focused Polars parity tests;
5. run entire parity suite;
6. run full repository test suite twice;
7. report exact:

   * PASS
   * XFAIL
   * XPASS
   * FAIL
   * SKIP
8. inspect every remaining Polars xfail manually;
9. verify no backend-private columns survive canonical output;
10. verify touching intervals with Polars-Bio are non-overlapping;
11. verify duplicate query/annotation fixtures preserve multiplicity;
12. verify deliberate backend failure raises rather than returns a biological empty result.

---

# Git discipline

Keep Task 4 on one dedicated branch.

Prefer logical commits, for example:

```text
fix: adapt polars-bio output to canonical schema
fix: enforce zero-based half-open polars semantics
fix: propagate polars backend failures
test: remove resolved parity xfails
docs: update engine deviation inventory
```

Do not manufacture unnecessary commits.

Open the PR only after review findings are resolved.

Do not merge automatically unless that is the repository's established workflow.

---

# Final report

Return:

* branch;
* base commit;
* commits;
* files changed;
* P1 resolution;
* P2 resolution;
* P3 resolution;
* P4 resolution;
* exact adapter strategy;
* coordinate-system configuration strategy;
* row-identity/order strategy;
* left reconstruction strategy;
* exception propagation strategy;
* xfails removed, grouped by root cause;
* remaining Polars xfails and why;
* Bedtools deviations intentionally left untouched;
* exact focused parity counts;
* exact complete parity counts;
* exact full-suite PASS/XFAIL/XPASS/FAIL/SKIP counts;
* reviewer findings and resolutions;
* acceptance criteria status one by one;
* later-task backlog;
* explicit confirmation that Task 5 was not started.
