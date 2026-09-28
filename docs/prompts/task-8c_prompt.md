Continue on the existing branch:

`release-prep-0.1.0`

Do not create another branch.

The license provenance audit correctly concluded that repository history alone was ambiguous and required a maintainer decision.

That decision has now been made.

Both project maintainers/contributors have authorized the license decision, and the maintainer has chosen:

**BSD 3-Clause License (`BSD-3-Clause`)**

Treat this as the explicit current licensing decision for AnnotateR going forward.

Your task is to resolve the repository-wide licensing inconsistency and complete the pre-release housekeeping branch.

Do not change UI layout, scientific semantics, engine behavior, tests, parsers, normalization, benchmark code, deployment behavior, or dependencies.

---

# 1. Canonical license

The canonical license for AnnotateR is:

`BSD-3-Clause`

The existing root `LICENSE` file already contains BSD-3-Clause.

First verify that it is a valid standard BSD 3-Clause license and that its copyright attribution is appropriate for the project.

Do not replace it with MIT, GPL, BSD-2-Clause, or another license.

Do not modify the substantive BSD-3-Clause terms unless correction of project-specific copyright attribution is required.

---

# 2. Copyright attribution

Audit the current copyright line in `LICENSE`.

The provenance audit reported that the current BSD license names J. Das.

AnnotateR has contributions from both project maintainers/authors.

Do not silently invent ownership percentages or institutional ownership.

Use a conservative project-appropriate copyright attribution consistent with confirmed repository authorship.

If the repository provides enough evidence that both named authors should appear as copyright holders, update accordingly.

If copyright ownership is legally ambiguous despite the maintainers agreeing on BSD-3-Clause, preserve the existing copyright attribution and report the issue rather than inventing ownership.

License choice and copyright ownership are separate questions.

---

# 3. README

Replace all GPL/GPLv3 declarations with BSD-3-Clause.

Update:

- license badge;
- License section;
- links to `LICENSE`;
- any other user-facing licensing copy.

The README must unambiguously state that AnnotateR is licensed under BSD-3-Clause.

Do not retain historical GPL wording in current user-facing documentation.

---

# 4. Streamlit application

Replace the current GPLv3 footer/About declaration with:

`BSD-3-Clause`

or an equivalent concise user-facing form such as:

`License: BSD-3-Clause`

Do not otherwise modify the footer or UI layout.

This is factual metadata correction only.

---

# 5. `pyproject.toml`

Add/update standards-compliant project license metadata for BSD-3-Clause.

Use the appropriate modern metadata representation supported by the project's packaging configuration.

Do not introduce conflicting license declarations.

If classifiers are already used and a BSD license classifier is appropriate, keep metadata internally consistent.

Do not perform unrelated packaging changes.

---

# 6. `CITATION.cff`

Set the license field to:

`BSD-3-Clause`

Keep the existing confirmed:

- AnnotateR title;
- repository URL;
- authors;
- confirmed ORCID(s).

Do not add:

- DOI;
- `date-released`;
- publication metadata.

No formal `v0.1.0` release exists yet.

Handle the software version according to the existing pre-release policy: do not imply that the release/tag already exists merely because the working software metadata is aligned to 0.1.0.

---

# 7. Current documentation

Search all current/non-historical documentation for:

- `GPL`
- `GPLv3`
- `GNU General Public License`
- `BSD`
- `BSD-3-Clause`

Update current project documentation so it consistently states BSD-3-Clause.

This includes, where applicable:

- README
- QUICKSTART
- current docs
- package metadata
- application metadata
- citation metadata
- deployment/release documentation

Do not modify historical records merely to rewrite history.

---

# 8. Historical files

The legacy R implementation contains historical GPL statements.

Do NOT silently rewrite historical source headers as though they had always been BSD.

Instead:

1. inspect `app/README.md` / `docs/legacy.md`;
2. document clearly that these files belong to the historical R implementation and retain their historical license/header text;
3. state that the current AnnotateR Python/Streamlit project release is licensed under BSD-3-Clause;
4. avoid implying that historical provenance has been erased.

Do not make legal claims about retroactive relicensing beyond the explicit maintainer decision.

The legacy implementation remains excluded from the production image.

---

# 9. Preserve provenance audit

Do not delete the license provenance findings from:

- `docs/implementation-notes.md`;
- other audit documentation.

Update the conclusion from:

`MAINTAINER DECISION REQUIRED`

to something equivalent to:

`RESOLVED — maintainers selected BSD-3-Clause for the current AnnotateR project/release.`

Record that the decision was made after reviewing the conflicting historical metadata.

Keep the historical evidence table intact.

The goal is transparency, not rewriting repository history.

---

# 10. Release plan

Update:

`docs/release-plan-0.1.0.md`

so license settlement is marked complete.

The remaining release gate should now be:

```text
manual GUI acceptance
→ any approved UI polish
→ full test suite
→ Docker smoke
→ final release metadata
→ tag v0.1.0
→ GitHub Release
→ SciLifeLab Serve deployment
→ post-deployment smoke
```

Do not create the tag or release yet.

---

# 11. Repository-wide consistency check

After edits, search the complete tracked repository.

Classify every remaining occurrence of:

- GPL
- GPLv3
- GNU General Public License
- BSD
- BSD-3-Clause

as either:

A. current licensing metadata — MUST say BSD-3-Clause;

or

B. historical/provenance material — may retain historical GPL wording but MUST be clearly historical and must not appear to describe the current release.

Report every remaining GPL occurrence and why it was intentionally retained.

There must be no ambiguous current GPL declaration.

---

# 12. Version remains 0.1.0

Do not change the version decision from the previous pre-release pass.

Verify:

- `pyproject.toml` = 0.1.0;
- `Settings.VERSION` = 0.1.0;
- `streamlit_app.__version__` resolves to 0.1.0.

Do not tag `v0.1.0`.

---

# 13. Verification

Run:

1. repository-wide license-string audit;
2. version-string audit;
3. packaging metadata validation if an appropriate existing/lightweight command is available;
4. full pytest suite;
5. existing relevant CI/static checks that can be run locally.

Expected scientific baseline:

`853 passed`

Any changed test count must be explained.

No benchmark rerun is required because benchmark code must remain untouched.

No Docker rebuild is required unless packaging/license metadata unexpectedly affects the production build.

---

# 14. Diff review

Before committing:

Inspect the complete diff against the current branch parent.

The diff should contain only:

- license metadata/copy;
- provenance/audit documentation;
- release-plan status;
- any strictly necessary packaging metadata.

There must be zero changes to:

- engines;
- parsers;
- canonical schemas;
- normalization;
- parity fixtures;
- benchmark implementation;
- Streamlit layout;
- deployment behavior.

---

# 15. Commit

Create one small follow-up commit on:

`release-prep-0.1.0`

Suggested message:

`docs: resolve AnnotateR license as BSD-3-Clause`

Do not amend the previous pre-release commit unless repository convention specifically requires it.

---

# Final report

Return:

- branch;
- new commit SHA;
- canonical license;
- root LICENSE disposition;
- copyright attribution disposition;
- every current license declaration changed;
- `pyproject.toml` license metadata;
- `CITATION.cff` license metadata;
- remaining GPL occurrences and why each is historical;
- provenance-audit conclusion update;
- release-plan update;
- final version verification;
- exact pytest counts;
- files changed;
- confirmation that UI layout was unchanged;
- confirmation that scientific semantics were unchanged;
- confirmation that no tag, GitHub Release, or deployment was created.

Do not begin manual GUI changes.
Do not create `v0.1.0`.