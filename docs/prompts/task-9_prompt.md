Task 8 is complete.

Before manual GUI acceptance, perform a narrowly scoped **pre-release housekeeping pass**.

This is NOT a new scientific milestone.

Do not change genomic semantics, engine behavior, benchmark implementation, parsing, normalization, or Streamlit layout.

The goal is to remove non-UI release inconsistencies now so that the subsequent manual acceptance review can focus exclusively on the GUI.

---

# Preconditions

First finish Task 8 normally:

1. push `task-8-deployment-docs-benchmark`;
2. open PR against `main`;
3. let all GitHub CI jobs run, including the new Docker/reproducibility job;
4. report exact CI outcome;
5. if all required checks are green, merge using the repository's normal convention;
6. fast-forward local `main`;
7. verify `main == origin/main`;
8. verify working tree clean.

Only then create:

`release-prep-0.1.0`

Do not perform this work on the Task 8 branch.

---

# 1. Version alignment

AnnotateR currently has inconsistent version metadata:

- `pyproject.toml`: `0.1.0`
- application settings: `1.0.0`
- no Git tag;
- no GitHub Release.

The intended first public release SHALL be prepared as:

`0.1.0`

Align all existing version displays/metadata to `0.1.0`.

Audit at minimum:

- `pyproject.toml`
- application/version settings
- About/footer text if versioned
- README
- QUICKSTART
- citation/release metadata
- Docker labels if any
- docs containing explicit version claims

Do not introduce multiple independent version constants if one source of truth can reasonably be reused.

Do NOT create a tag or GitHub Release yet.

The actual `v0.1.0` tag happens only after manual GUI acceptance.

---

# 2. License provenance audit — do not guess

There is currently a contradiction:

- root `LICENSE` says BSD-3-Clause;
- README badge and/or app footer have claimed GPLv3;
- `pyproject.toml` does not currently resolve the inconsistency.

Before editing license declarations, inspect Git history.

Determine:

1. when the root `LICENSE` first appeared;
2. which license it contained originally;
3. when GPL wording first appeared in README/footer;
4. whether any commit message, documentation, package metadata, or project history explicitly records a deliberate license change;
5. whether the old R implementation carries license headers or metadata;
6. whether there is evidence that one declaration is merely stale copy.

Produce a concise evidence table:

```text
Artifact | First relevant commit | License shown | Notes
```

Do not infer legal intent from which license is more convenient.

Do not replace one license with another unless repository history provides a clear provenance-based answer.

---

# 3. License resolution policy

If history establishes clearly that:

- BSD-3-Clause was the original/project license;
- GPL wording appeared later only as inconsistent badge/footer copy;
- no deliberate relicensing event exists;

then align user-facing metadata to BSD-3-Clause.

If history instead establishes GPLv3 as the deliberate project license and the BSD file is the inconsistent artifact, report that evidence before changing anything.

If provenance is ambiguous or conflicting:

STOP license normalization and report:

`MAINTAINER DECISION REQUIRED`

with the exact evidence.

Do not make a legal/relicensing decision autonomously.

All other pre-release housekeeping may continue.

---

# 4. Once a license is established

Only after provenance supports the choice, make these consistent:

- root `LICENSE`
- README license badge/text
- Streamlit footer/About
- `pyproject.toml` license metadata where appropriate
- `CITATION.cff`
- any package/repository metadata under version control

Search the entire repository for stale mentions of:

```text
GPL
GPLv3
BSD
BSD-3-Clause
license
licence
```

Verify no contradictory user-facing declaration remains.

Do not modify third-party license notices.

---

# 5. Citation metadata

Audit `CITATION.cff`.

Preserve only confirmed facts.

Before the actual release:

- title: AnnotateR
- repository URL: current AnnotateR repository
- confirmed authors/contributors only
- confirmed ORCIDs only
- confirmed license only after license decision
- version may be aligned to `0.1.0` only if repository convention treats this as software metadata rather than claiming a published release
- do not invent DOI
- do not invent publication
- do not invent release date

If CFF best practice would make adding version/date premature before tagging, leave those fields absent and document that they will be added during the release step.

---

# 6. Legacy R implementation

Do NOT delete the old R implementation during this pass.

Audit these reported legacy files:

- `.Rprofile`
- `app/annotater.R`
- `app/app.R`
- `app/www/*`
- `renv.lock`
- `docs/polars-bio_manual.pdf`

Determine for each whether it is:

- historical AnnotateR implementation;
- still referenced by current docs/code;
- current runtime dependency;
- obsolete generated/reference artifact.

The current Python/Streamlit production image must continue to exclude unused legacy files.

For clearly historical R app files, add minimal documentation indicating that they are retained temporarily for historical/reference purposes pending post-acceptance cleanup.

Do not reorganize them into `legacy/` yet unless the move is completely reference-safe and clearly beneficial.

Preferred outcome for this pass:

```text
retain
document
exclude from production
decide final deletion/move after GUI acceptance
```

---

# 7. `docs/polars-bio_manual.pdf`

Determine why this PDF is tracked.

If it is merely a downloaded copy of upstream documentation and current primary links already exist in `docs/references.md`, report it as a candidate for removal.

Do not delete it automatically unless:

- nothing references it;
- no project-specific annotation exists in it;
- the authoritative upstream documentation is already linked;
- removal cannot reduce reproducibility.

If uncertain, retain for now.

---

# 8. Release metadata audit

Inspect current state of:

- Git tags;
- GitHub Releases;
- package version;
- Docker tag conventions;
- changelog/history if present.

Do NOT publish anything.

Prepare a short release plan for after manual GUI acceptance:

```text
1. apply any final GUI polish
2. full test suite
3. Docker smoke
4. align final release metadata
5. tag v0.1.0
6. create GitHub Release
7. deploy approved image
8. post-deployment smoke test
```

---

# 9. Changelog

If the repository already maintains a changelog, prepare the unreleased/0.1.0 section so it accurately summarizes the completed modernization.

Do not create an elaborate changelog system if none exists unless repository conventions call for one.

A useful first-release summary may mention:

- canonical genomic coordinate contract;
- Bedtools and Polars-Bio parity;
- overlap/left/min_overlap/strand/contains/within/closest;
- Streamlit integration;
- reproducible Docker deployment;
- benchmark infrastructure.

Keep implementation history concise.

---

# 10. Repository hygiene

Perform another narrowly scoped release hygiene check for:

- tracked `.pi` runtime artifacts;
- benchmark temporary files;
- generated synthetic datasets;
- Python caches;
- `.DS_Store`;
- editor files;
- secrets;
- credentials;
- local paths;
- obsolete ZIPs;
- test output artifacts;
- Docker build artifacts.

Do not perform unrelated code cleanup.

---

# 11. Documentation consistency

Search user-facing docs for stale claims including:

```text
Experimental
results may differ
GPL
BSD
1.0.0
0.1.0
old repository URL
annotator
annotater
placeholder
non-normative
```

Resolve only genuine stale release/documentation inconsistencies.

Do not rewrite scientific documentation unnecessarily.

---

# 12. No UI redesign

Do not alter:

- Streamlit layout;
- spacing;
- widget grouping;
- chart appearance;
- labels purely for aesthetic reasons;

unless required to correct version/license factual metadata.

Manual UI acceptance will happen immediately after this task.

---

# 13. No scientific changes

Absolutely do not change:

- overlap semantics;
- min_overlap;
- strand;
- contains;
- within;
- closest;
- canonical schemas;
- parsers;
- engine implementation;
- parity fixtures.

If an issue is discovered, report it separately.

---

# Verification

Run:

1. focused metadata/docs checks as appropriate;
2. existing static/lint checks;
3. full repository test suite;
4. verify Docker configuration remains unchanged except factual metadata if required;
5. inspect `git diff origin/main`;
6. search repository again for contradictory license/version strings;
7. verify working tree clean after commit.

No benchmark rerun is required unless benchmark code was accidentally touched.

No scientific parity changes should exist.

---

# Deliverable

Return:

- branch;
- base commit;
- commits;
- files changed;
- exact version strings found before;
- exact version strings after;
- license provenance evidence table;
- final license decision OR `MAINTAINER DECISION REQUIRED`;
- every license declaration changed, if any;
- citation metadata disposition;
- legacy-file inventory;
- recommendation for each legacy file;
- `docs/polars-bio_manual.pdf` disposition;
- repository hygiene findings;
- release plan for `v0.1.0`;
- exact test counts;
- confirmation that UI layout was not changed;
- confirmation that scientific semantics were not changed.

Do not create the `v0.1.0` tag.
Do not create a GitHub Release.
Do not deploy a release yet.