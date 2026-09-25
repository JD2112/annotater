You are working on **AnnotateR**.

Tasks 1–6E are complete and merged.

Implement **Task 7 only: Streamlit integration, backend-selection parity, user-visible validation, and a controlled UI polish pass**.

The scientific/backend contract is now stable:

```text id="pm4yxm"
same canonical input
+ same options
+ Bedtools or Polars-Bio
→ same canonical result
```

Task 7 must expose that reliably in the Streamlit app.

Do not change genomic semantics in this task.

---

# Start state

Start from the current clean `main` after Task 6E has been merged and CI has passed.

Before editing:

1. `git fetch origin`
2. fast-forward local `main`
3. verify `main == origin/main`
4. verify working tree clean
5. create:

`task-7-streamlit-integration`

Do not work directly on `main`.

---

# Mandatory reading

Read in this order:

1. `AGENTS.md`
2. `SPEC.md`
3. `PLAN.md` — Task 7
4. `docs/architecture.md`
5. `docs/engine-contract.md`
6. `docs/references.md`
7. `docs/implementation-notes.md`
8. `streamlit_app/streamlit_app.py`
9. `streamlit_app/config/settings.py`
10. parser / normalization modules
11. `streamlit_app/core/annotator.py`
12. complete `tests/parity/`
13. existing Streamlit/AppTest tests
14. README / QUICKSTART user-facing workflow

Treat Tasks 1–6E as complete contracts.

Do not reopen their semantics unless an actual contradiction is found.

---

# Primary goal

The Streamlit UI must make Bedtools and Polars-Bio interchangeable execution backends.

For identical user input and options:

```text id="5bfh01"
Upload
  ↓
same parsing
  ↓
same canonical normalization
  ↓
engine selector
  ├─ Bedtools
  └─ Polars-Bio
  ↓
same canonical result contract
  ↓
same preview / metrics / download structure
```

Changing engine must not change:

* parser selection;
* coordinate interpretation;
* metadata handling;
* operation semantics;
* result schema;
* exported content semantics;
* visible error policy.

Only the execution backend should change.

---

# Task 7 scope

Implement:

1. backend selection integration;
2. parser/backend decoupling verification;
3. full propagation of operation controls;
4. user-visible validation/errors;
5. result/download parity;
6. Streamlit AppTest coverage;
7. controlled aesthetics/usability improvements.

Do not modify scientific semantics.

---

# 1. Backend selector

The UI must expose a clear backend selector for:

```text id="scd9yq"
Bedtools
Polars-Bio
```

Prefer concise user-facing labels such as:

```text id="3vx2l7"
Annotation engine
○ Bedtools
○ Polars-Bio
```

or an equivalent accessible control.

Do not expose internal class names.

The selected backend must map deterministically to:

```text id="g2jkf7"
BedtoolsEngine
PolarsBioEngine
```

No hidden fallback.

If an engine cannot initialize, show an explicit error.

Do not silently switch to the other backend.

---

# 2. Parser/backend independence

Audit the complete UI flow for any remaining logic like:

```text id="yw2ec4"
if use_polars_bio:
    parse differently
```

or equivalent backend-dependent parsing.

Remove such coupling.

The pipeline must be:

```text id="7l0i50"
input file
→ detect/parse format
→ canonical normalize
→ choose backend
```

not:

```text id="ubyd65"
choose backend
→ choose parser
```

Add tests proving identical parsed canonical input reaches either engine.

---

# 3. Operation controls

Expose / preserve the existing supported modes consistently:

```text id="ytgg5k"
overlap
contains
within
closest
```

and relevant options:

```text id="n2iomd"
left / inner
min_overlap
use_strand
```

Do not invent new semantics.

UI controls should reflect the normative contract:

## `min_overlap`

Only meaningful for:

```text id="p166m6"
mode="overlap"
```

When another mode is selected:

* disable or hide the control;
* do not pass stale `min_overlap` unexpectedly;
* provide concise help text if needed.

## strand

`use_strand` applies to all supported relation modes according to the canonical contract.

## closest

If closest is selected:

* result includes canonical `distance`;
* explain briefly that overlap/touch = 0 and ties are all returned if help text exists.

---

# 4. State safety

Audit Streamlit session/widget state.

Changing:

* engine;
* mode;
* input file;
* join type;
* min_overlap;
* strand;

must not leave stale results or stale parameters visible as though they belong to the new configuration.

Prefer explicit invalidation/recomputation behavior.

Do not allow:

```text id="rvgn5o"
old Bedtools result
displayed after switching to Polars-Bio
```

without rerunning.

If the current app already requires an explicit Run button, preserve that interaction unless a clear improvement is needed.

---

# 5. Error handling

User-visible errors must distinguish:

## Invalid user configuration

Examples:

* malformed canonical option;
* unsupported file/input combination;
* missing required input.

Show a concise actionable Streamlit error.

## Backend execution failure

Show:

* which backend failed;
* concise operation context;
* useful message.

Do not dump a giant Python traceback into the normal user UI.

Preserve original exception details in logs/developer context where existing architecture permits.

## Valid zero-match result

This is NOT an error.

Show a valid empty-result state.

Do not use red error messaging for “0 annotations matched”.

---

# 6. Result parity at the UI boundary

For protected fixtures:

```text id="f2r1pm"
same upload
same options
Bedtools
```

and:

```text id="8jckl8"
same upload
same options
Polars-Bio
```

must produce equivalent user-visible data.

Compare:

* row count;
* column order;
* values;
* missing values;
* metadata;
* `has_overlap`;
* `distance` in closest mode;
* download content.

Do not merely assert both runs complete.

---

# 7. Download parity

Audit every result export/download path.

The selected backend must not alter export semantics.

For identical canonical results, downloaded files should be semantically equivalent.

Check:

* CSV/TSV if supported;
* BED-like export if supported;
* VCF export if supported;
* Excel if supported;
* filename generation;
* missing-value rendering;
* column order.

Do not rewrite export architecture unless needed.

Pin at least one AppTest or lower-level integration test proving Bedtools/Polars output downloads are equivalent for the same fixture.

---

# 8. Preview behavior

Input previews and normalized previews must be backend-independent.

Changing engine must not change:

* source preview;
* detected format;
* parsed column names;
* coordinate display conventions;
* metadata preview.

Add a regression test if this was historically coupled.

---

# 9. Streamlit AppTest coverage

Use:

```text id="f22egh"
streamlit.testing.v1.AppTest
```

from the pinned Streamlit version.

Build focused interaction tests.

At minimum cover:

## Backend selector

* Bedtools selectable;
* Polars-Bio selectable;
* selected value reaches correct engine constructor.

## Same-input parity

Run one small fixture through both engines and compare user-visible results.

## Mode switching

Exercise:

* overlap;
* contains;
* within;
* closest.

## min_overlap gating

* visible/enabled for overlap;
* disabled/hidden outside overlap;
* stale value does not affect contains/within/closest.

## strand

* checkbox/toggle reaches engine;
* changing strand invalidates/recomputes appropriately.

## closest

* distance visible;
* ties represented;
* empty/no-candidate state handled.

## errors

* backend failure surfaces as explicit UI error;
* valid zero-result remains non-error.

## state transitions

Switch:

```text id="l1vrak"
Bedtools → Polars-Bio
```

and ensure stale results are not mislabeled/reused.

---

# 10. Controlled UI polish

Improve the aesthetics and usability of the Streamlit interface, but keep this a focused polish pass rather than a redesign.

Goals:

* cleaner visual hierarchy;
* clearer grouping of controls;
* less clutter;
* more consistent spacing;
* better explanatory copy;
* better result-state feedback;
* more professional appearance.

Do not sacrifice accessibility or clarity for decoration.

---

# Suggested page structure

Consider a structure approximately like:

```text id="2up1hl"
AnnotateR
Short one-line description

[1. Upload]
query input
annotation input

[2. Configure]
engine
operation
join behavior
operation-specific options

[3. Run annotation]
primary action

[4. Results]
summary metrics
result preview
download actions
```

Use Streamlit containers/columns where useful.

Do not over-fragment the page.

---

# Engine selector presentation

Make the backend choice understandable without implying different biological results.

Good copy:

```text id="oe2axm"
Annotation engine

Bedtools
Reference implementation

Polars-Bio
High-performance implementation
```

Avoid copy like:

```text id="rpnvqe"
Results may differ
```

because supported semantics are now contractually equivalent.

Do not claim one is universally faster unless benchmark evidence exists.

---

# Operation help text

Use short, precise descriptions.

Suggested wording:

## Overlap

> Return annotation intervals that overlap each query interval.

## Contains

> Return annotations fully contained within each query interval.

## Within

> Return annotations that fully contain each query interval.

## Closest

> Return the nearest annotation interval(s); all equally nearest ties are retained.

---

# min_overlap copy

Suggested:

> Minimum fraction of each query interval that must overlap a single annotation interval.

If UI uses a slider:

* show percent or fraction consistently;
* preserve exact backend value;
* `0` should map cleanly to ordinary overlap according to existing UI/API policy.

Do not introduce semantic transformation bugs in display formatting.

---

# Strand copy

Suggested:

> Require query and annotation to have the same explicit strand.

Optional help:

> Missing strand values do not act as wildcards.

Keep it concise.

---

# Result summary

Add or improve a compact summary area if appropriate.

Useful metrics may include:

```text id="05br7a"
Query rows
Result rows
Matched query rows
Unmatched query rows
Engine
Operation
```

For closest, optionally include:

```text id="ma2nty"
Distance column present
```

Do not invent misleading biological metrics.

---

# Empty-result presentation

Instead of a blank table, show a clear informational state such as:

```text id="3z41hl"
No qualifying annotations were found for the selected operation and options.
```

For left mode where rows survive unmatched, present the canonical result normally.

---

# Result table

Improve readability if needed:

* sensible height;
* horizontal scroll;
* canonical columns first;
* metadata afterward;
* no hidden mutation of data for display.

Do not alter output values merely to make the table prettier.

---

# Download section

Group download controls clearly.

Avoid scattering buttons around the page.

If multiple export formats exist, use one coherent section.

---

# Visual style

Stay within native Streamlit unless the existing app already has a stable custom styling approach.

Prefer:

* spacing;
* headings;
* containers;
* concise captions;
* restrained use of icons;
* consistent labels.

Avoid:

* large blocks of brittle injected CSS;
* hard-coded DOM selectors;
* flashy gradients;
* excessive emojis;
* custom HTML that may break on Streamlit upgrades.

A little CSS is acceptable only if minimal, robust, and justified.

---

# Responsive behavior

The page should remain usable on narrower screens.

Do not create a layout that only works on wide desktop monitors.

Avoid too many side-by-side controls.

---

# Accessibility

Preserve meaningful labels.

Do not rely solely on color.

Do not replace text labels with unexplained icons.

Use Streamlit-native controls where possible.

---

# 11. Remove stale technical copy

Audit README/UI/help text for old statements such as:

* Polars-Bio being experimental;
* contains/within being placeholders;
* closest differences;
* backend result differences;
* parser differences;
* old strand behavior.

Update user-facing documentation to reflect Tasks 1–6E.

Do not overclaim beyond the supported contract.

---

# 12. Backend availability

Decide how the UI handles an unavailable backend dependency.

Requirements:

* no silent fallback;
* clear message;
* unaffected backend remains usable if architecture supports that safely.

Example:

```text id="xj1q3c"
Polars-Bio is unavailable in this environment.
Choose Bedtools or contact the deployment administrator.
```

Do not expose installation commands to ordinary hosted users unless appropriate.

---

# 13. Default backend

Inspect existing behavior and docs before changing defaults.

Do not arbitrarily switch the default engine just because Polars-Bio is newer.

If Bedtools is currently the historical/default backend and no product decision says otherwise, preserve it.

Document the chosen default.

---

# 14. Performance behavior

Do not benchmark or optimize broadly in Task 7.

However:

* avoid recomputing parsing unnecessarily;
* use existing Streamlit caching only if already appropriate;
* do not cache engine results incorrectly across backend/options.

Correct cache keys must include all semantics-affecting inputs.

If current caching is unsafe, fix it.

---

# 15. No scientific changes

This is critical.

Do not modify:

* overlap mathematics;
* `min_overlap`;
* strand semantics;
* contains;
* within;
* closest distance;
* closest tie behavior;
* canonical coordinates;
* canonical result schema;

unless an actual contract violation is discovered.

If one is discovered, report it rather than silently redefining behavior inside the UI task.

---

# 16. Tests must not depend on visual text unnecessarily

Use stable widget labels/keys and semantic assertions.

Do not make AppTests fragile by asserting every heading/caption verbatim unless that text itself is part of the contract.

Prefer checking:

* widget exists;
* selected option;
* state transition;
* dataframe contents;
* error/info state.

---

# Explicit non-goals

Do NOT:

* redesign the entire product;
* introduce a JS frontend;
* replace Streamlit;
* add authentication;
* add analytics;
* add cloud storage;
* add new annotation modes;
* change scientific semantics;
* benchmark backends;
* upgrade dependencies broadly;
* rewrite parsers;
* restructure the entire repo.

---

# Review loop

Use two independent Pi subagent reviewers if available.

## Reviewer 1 — integration / semantic integrity

Check:

* parser is backend-independent;
* UI options map exactly to canonical engine options;
* switching backend cannot change scientific meaning;
* no stale state;
* exports equivalent;
* errors vs zero-result correctly distinguished.

## Reviewer 2 — UX / Streamlit quality

Check:

* control hierarchy;
* labels/help text;
* mode-specific controls;
* result clarity;
* responsive layout;
* accessibility;
* AppTest quality;
* no brittle CSS;
* no over-redesign.

Resolve all BLOCKER and MAJOR findings.

For MINOR UX findings, fix those that materially improve clarity without causing scope creep.

---

# Acceptance criteria

Task 7 is complete only when:

1. backend selector exposes Bedtools and Polars-Bio clearly;
2. backend choice affects execution only;
3. parser/normalization are backend-independent;
4. same input/options produce equivalent user-visible results across engines;
5. canonical column order is preserved;
6. closest `distance` appears identically;
7. downloads are semantically equivalent;
8. all supported modes are wired correctly;
9. `min_overlap` is active only for overlap;
10. strand control maps correctly;
11. changing engine/options cannot silently reuse stale results;
12. backend failure produces clear UI error;
13. valid zero-match produces non-error state;
14. AppTest covers both engines;
15. AppTest covers backend switching;
16. AppTest covers all four modes;
17. AppTest covers min_overlap gating;
18. AppTest covers strand;
19. AppTest covers closest distance;
20. AppTest covers failure vs no-match;
21. no scientific contract was changed;
22. stale pre-Task-6 UI/help text removed;
23. UI visual hierarchy is materially cleaner;
24. controls are logically grouped;
25. result/download area is clearer;
26. responsive usability not degraded;
27. no brittle styling approach introduced;
28. full existing parity suite remains green;
29. full repository suite has zero unexpected FAIL/XPASS;
30. reviewers report no unresolved BLOCKER/MAJOR findings.

---

# Final verification

Before completion:

1. inspect full diff vs `origin/main`;
2. run all Streamlit/AppTest tests;
3. run backend-selection tests;
4. run UI result parity fixtures;
5. run download parity test;
6. test all four modes through UI;
7. test engine switching;
8. test min_overlap enable/disable behavior;
9. test strand;
10. test closest distance;
11. test backend error;
12. test valid zero-result;
13. run full parity suite;
14. run full repository suite twice;
15. report exact PASS/XFAIL/XPASS/FAIL/SKIP;
16. review the rendered app manually if environment permits;
17. inspect narrow-screen layout if feasible;
18. verify no scientific engine behavior changed.

---

# Git discipline

Use:

`task-7-streamlit-integration`

Prefer logical commits such as:

```text id="99j3hs"
test: add streamlit backend integration coverage
feat: unify backend selection and result flow
feat: improve annotation workflow UI
docs: update user workflow after engine parity
```

Do not manufacture unnecessary commits.

Open the PR only after review findings are resolved.

Do not merge automatically unless that is the established repository workflow.

---

# Final report

Return:

* branch;
* base commit;
* commits;
* files changed;
* backend-selection implementation;
* parser/backend-decoupling verification;
* option-to-engine mapping;
* state invalidation strategy;
* result parity verification;
* download parity verification;
* error-handling strategy;
* exact AppTest scenarios;
* UI changes made;
* before/after UX summary;
* any CSS/custom styling introduced and why;
* exact focused UI test counts;
* exact parity-suite counts;
* exact repository-wide PASS/XFAIL/XPASS/FAIL/SKIP;
* reviewer findings and resolutions;
* acceptance criteria status one by one;
* remaining Task 8 backlog;
* explicit confirmation that scientific semantics were not changed.

Do not begin Task 8.
