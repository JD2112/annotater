# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Moved repository root documentation and specification files (`AGENTS.md`, `PLAN.md`, `QUICKSTART.md`, `SPEC.md`) into a top-level `assets/` directory.
- Updated repository URLs, clone paths, and documentation links from `pyrevo/annotater` to `JD2112/annotater`.
- Fixed CODEOWNERS syntax to correctly list multiple default owners on a single line (`* @JD2112 @pyrevo`).
- Added `CHANGELOG.md` tracking all commits and project versions.

## [0.1.0-rc1] - 2026-09-29

### Added
- Published release candidate container image `ghcr.io/pyrevo/annotater:0.1.0-rc1` to GitHub Container Registry (GHCR).
- Dual interchangeable execution backends: **Bedtools** (reference binary) and **Polars-Bio** (in-process) with test-enforced parity.
- Canonical coordinate data model: 0-based half-open intervals `[start, end)` with automatic conversion from 1-based formats at parse boundary.
- Five genomic annotation operations with parity across backends:
  - `overlap` (with optional minimum query overlap fraction `min_overlap`)
  - `contains` (query contains annotation feature)
  - `within` (query feature is within annotation feature)
  - `closest` (nearest feature with canonical gap distance calculation)
  - `strand-aware` matching (same-strand filter)
- Join behavior: `left` (preserve unmatched query coordinates) and `inner` joins.
- Multi-format parser support: BED, GFF3, GTF, VCF, CSV/TSV with chromosome ID normalization (UCSC, Ensembl, NCBI).
- Interactive Streamlit web interface with real-time summary cards, preview tables, chromosome distribution charts, gene list clipboard copy, and CSV/TSV/Excel/VCF exports.
- Publication-quality documentation site using MkDocs Material, comprehensive user manual, tutorials, and scientific contract specifications.
- Parity harness test suite and reproducible benchmarking framework (`benchmarks/benchmark_engines.py`).
- CI workflows for automated pytest across Python 3.12 (macOS and Ubuntu), GHCR container builds, and docs deployment.

### Commits in 0.1.0-rc1 (107 commits)
- `4f15384` - 2026-09-30 (Massimiliano Volpe): Merge pull request #26 from pyrevo/docs-journal-readiness-fixes
- `34f5104` - 2026-09-30 (pyrevo): docs: correct final journal-readiness issues
- `a659035` - 2026-09-30 (Massimiliano Volpe): Merge pull request #25 from pyrevo/docs-final-wording-fixes
- `d202db4` - 2026-09-30 (pyrevo): docs: document local Docker execution with GHCR image in README
- `d95e367` - 2026-09-30 (pyrevo): docs: rewrite README for a scientific-software audience
- `b558269` - 2026-09-29 (pyrevo): docs: record published GHCR release candidate 0.1.0-rc1
- `7269b47` - 2026-09-29 (Massimiliano Volpe): Merge pull request #24 from pyrevo/release-ghcr-0.1.0-rc1
- `672cacf` - 2026-09-29 (pyrevo): docs: document GHCR release-candidate images
- `e71121a` - 2026-09-29 (pyrevo): ci: publish AnnotateR release candidates to GHCR
- `fea08e7` - 2026-09-29 (Massimiliano Volpe): Merge pull request #23 from pyrevo/docs-user-manual-v0.1.0
- `fdc4992` - 2026-09-29 (pyrevo): docs: fix three pre-existing self-anchors (double-dash slugs) in deployment/benchmark
- `d078e80` - 2026-09-29 (pyrevo): ci: build the docs site on every PR; deploy to GitHub Pages behind a repo var
- `a840f2d` - 2026-09-29 (pyrevo): docs: add the v0.1.0 user manual as an MkDocs + Material site
- `841013f` - 2026-09-29 (pyrevo): docs: add v0.1.0 user-manual fixtures with parity-tested expected results
- `000c9c8` - 2026-09-29 (pyrevo): docs: add user-manual documentation architecture plan (docs/manual-plan.md)
- `2ef49ea` - 2026-09-29 (Massimiliano Volpe): Merge pull request #22 from pyrevo/release-ui-typography-0.1.0
- `75eee0e` - 2026-09-29 (pyrevo): polish: raise small supporting typography 1-2px toward the footer size
- `74e529d` - 2026-09-29 (Massimiliano Volpe): Merge pull request #21 from pyrevo/release-ui-polish-0.1.0
- `3683d74` - 2026-09-29 (pyrevo): fix: address release UI review findings
- `644d0ad` - 2026-09-29 (pyrevo): docs: document the supported developer-toolbar configuration
- `12ebeca` - 2026-09-29 (pyrevo): test: cover final UI interaction states
- `f8f6eb1` - 2026-09-29 (pyrevo): feat: polish Streamlit release workflow
- `fb82ccb` - 2026-09-29 (Massimiliano Volpe): Merge pull request #20 from pyrevo/chore/repo-hygiene-publish
- `d8caaef` - 2026-09-29 (pyrevo): chore: repository hygiene for publication
- `2debe8e` - 2026-09-28 (Massimiliano Volpe): Merge pull request #19 from pyrevo/release-prep-0.1.0
- `050a11e` - 2026-09-28 (pyrevo): docs: resolve AnnotateR license as BSD-3-Clause
- `78a4c8a` - 2026-09-28 (pyrevo): docs: add pre-release housekeeping guidelines for Task 8
- `f68dab6` - 2026-09-28 (pyrevo): Task 9: pre-release 0.1.0 housekeeping (version alignment, legacy inventory, release plan)
- `5278a24` - 2026-09-28 (pyrevo): docs: add pre-release housekeeping guidelines for Task 9
- `fd24818` - 2026-09-28 (Massimiliano Volpe): Merge pull request #18 from pyrevo/task-8-deployment-docs-benchmark
- `3af1d91` - 2026-09-28 (pyrevo): ci: fix benchmark smoke step line-continuation
- `867164e` - 2026-09-25 (pyrevo): Task 8: publication-quality documentation, citation metadata, release audit
- `fcb5b52` - 2026-09-25 (pyrevo): Task 8: reproducible linux/amd64 deployment image and in-container smoke
- `999955f` - 2026-09-25 (pyrevo): Task 8: parity-gated engine benchmark and packaged comparator
- `aec841d` - 2026-09-25 (pyrevo): docs: add comprehensive deployment, documentation, and benchmarking guidelines for Task 8
- `88bab12` - 2026-09-25 (Massimiliano Volpe): Merge pull request #17 from pyrevo/task-7-streamlit-integration
- `28939ac` - 2026-09-25 (pyrevo): docs: use neutral wording for the Polars-Bio engine (no unbenchmarked performance claims)
- `f7c7b4e` - 2026-09-25 (pyrevo): polish: clarify that the VCF export is only offered for VCF coordinate input
- `a687bc1` - 2026-09-25 (pyrevo): docs: update user workflow after engine parity
- `e610c37` - 2026-09-25 (pyrevo): test: add streamlit backend integration coverage
- `40799f6` - 2026-09-25 (pyrevo): feat: unify backend selection and result flow in the Streamlit app
- `dba0111` - 2026-09-25 (pyrevo): feat: add explicit engine registry for backend selection
- `2d9a30d` - 2026-09-25 (pyrevo): feat: add Task 7 prompt for Streamlit integration and backend selection
- `04935d6` - 2026-09-25 (Massimiliano Volpe): Merge pull request #16 from pyrevo/task-6e-closest-semantics
- `baf30fa` - 2026-09-25 (pyrevo): feat: backend-independent canonical closest semantics (Task 6E)
- `0a75160` - 2026-09-24 (pyrevo): feat: implement final backend-independent `closest` / `nearest` semantics for Task 6E
- `a71da4a` - 2026-09-24 (Massimiliano Volpe): Merge pull request #15 from pyrevo/task-6d-within-semantics
- `f2c29f8` - 2026-09-24 (pyrevo): docs: lock down within semantics (Task 6D)
- `e198a46` - 2026-09-24 (pyrevo): feat: backend-independent query-within-annotation semantics (Task 6D)
- `ccc3a2d` - 2026-09-24 (pyrevo): test: define the query-within-annotation contract (Task 6D)
- `70eccee` - 2026-09-24 (pyrevo): feat: implement backend-independent `within` semantics for Task 6D
- `c0ba6fb` - 2026-09-24 (Massimiliano Volpe): Merge pull request #14 from pyrevo/task-6c-contains-semantics
- `f3cfffa` - 2026-09-24 (pyrevo): docs: lock down contains semantics (Task 6C)
- `db87ed4` - 2026-09-24 (pyrevo): feat: backend-independent query-contains-annotation semantics (Task 6C)
- `0cba78f` - 2026-09-24 (pyrevo): test: define the query-contains-annotation contract (Task 6C)
- `8ab5d73` - 2026-09-23 (pyrevo): feat: implement backend-independent `contains` semantics for Task 6C
- `cc5f7b9` - 2026-09-23 (Massimiliano Volpe): Merge pull request #13 from pyrevo/task-6b-strand-semantics
- `2ddab9b` - 2026-09-23 (pyrevo): chore: resolve reviewer findings (Task 6B review round)
- `e11ac00` - 2026-09-23 (pyrevo): docs: lock down strand semantics (Task 6B)
- `de3a861` - 2026-09-23 (pyrevo): feat: backend-independent same-strand filtering (Task 6B)
- `6883ef4` - 2026-09-23 (pyrevo): test: define strand-aware matching contract (Task 6B)
- `8f70923` - 2026-09-23 (pyrevo): feat: implement Task 6B - strand-aware overlap semantics
- `7e3de2c` - 2026-09-23 (Massimiliano Volpe): Merge pull request #12 from pyrevo/task-6a-min-overlap-semantics
- `4ee33c2` - 2026-09-23 (pyrevo): fix: gate min_overlap post-filter to overlap mode (Task 6A review)
- `37f6721` - 2026-09-23 (pyrevo): docs: lock down min-overlap semantics
- `f24c3f7` - 2026-09-23 (pyrevo): feat: backend-independent min-overlap semantics for both engines
- `9820f94` - 2026-09-23 (pyrevo): test: define the minimum query-overlap contract and validation tests
- `061f0e3` - 2026-09-23 (pyrevo): feat: implement Task 6A - define and document min_overlap semantics
- `f0e39f6` - 2026-09-23 (Massimiliano Volpe): Merge pull request #11 from pyrevo/task-5-bedtools-contract-cleanup
- `0433427` - 2026-09-22 (pyrevo): docs: close remaining engine deviations B1-B5 (Task 5)
- `8dfeca3` - 2026-09-22 (pyrevo): test: retire resolved Bedtools parity xfails (B1-B5)
- `26fd65c` - 2026-09-22 (pyrevo): fix: keep use_strand functional in the identity-only serialization
- `10b6aa5` - 2026-09-22 (pyrevo): test: add focused BedtoolsEngine regression tests (Task 5)
- `3519075` - 2026-09-22 (pyrevo): fix: rewrite BedtoolsEngine result adapter to satisfy the canonical contract (Task 5)
- `07cf4f8` - 2026-09-22 (pyrevo): feat: add Task 5 prompt for Bedtools contract cleanup and resolution of parity deviations
- `4068c1e` - 2026-09-22 (Massimiliano Volpe): Merge pull request #10 from pyrevo/task-4-polars-bio-contract-compliance
- `1f7c458` - 2026-09-22 (pyrevo): Record Task 4 completion in implementation notes and PLAN
- `c669a19` - 2026-09-22 (pyrevo): Remove resolved Polars-Bio xfail markers (Task 4)
- `b3ea112` - 2026-09-22 (pyrevo): Rewrite PolarsBioEngine to satisfy the canonical result contract (Task 4)
- `79d4dae` - 2026-09-22 (pyrevo): feat: add Task 4 prompt for PolarsBioEngine compliance with AnnotateR contract
- `705d37a` - 2026-09-22 (Massimiliano Volpe): Merge pull request #9 from pyrevo/task-3-engine-parity-harness
- `5667ec8` - 2026-09-22 (pyrevo): Add systematic Bedtools <-> Polars-Bio parity harness (Task 3)
- `b79efef` - 2026-09-22 (pyrevo): Fix canonical adapter crash on all-matched frames with bool annot_* columns (S1)
- `0a6f9a4` - 2026-09-22 (pyrevo): docs: add Task 3 prompt for systematic Bedtools ↔ Polars-Bio parity harness
- `96211b6` - 2026-09-22 (pyrevo): docs: add Task 3 prompt for systematic Bedtools ↔ Polars-Bio parity harness
- `3cfeca9` - 2026-09-22 (Massimiliano Volpe): Merge pull request #8 from pyrevo/task-2.5-dependency-runtime-audit
- `7fd185c` - 2026-09-22 (masvo): Docs/metadata consistency: pinning policy is Task 2.5's, not SPEC's; Python 3.12 is the tested runtime
- `114b8d8` - 2026-09-22 (masvo): Task 2.5 review resolution: Docker baseline, strict xfails, dependency disposition, references
- `9047d56` - 2026-09-21 (masvo): Task 2.5: dependency/runtime/reference audit
- `cf99c40` - 2026-09-21 (pyrevo): docs: add prompts for Task 2 and Task 2.5 outlining requirements and goals
- `f8a6c1a` - 2026-09-21 (pyrevo): docs: add GENCODE GTF format reference and remove Paseo documentation
- `9e5ff47` - 2026-09-21 (pyrevo): fix: address independent review findings (Task 2 follow-up)
- `dc31303` - 2026-09-21 (pyrevo): fix: reject malformed matched rows in canonical result validation
- `7bb98b4` - 2026-09-21 (pyrevo): fix: preserve VCF FILTER semantics and source metadata (Task 2 review)
- `b333ae1` - 2026-09-21 (pyrevo): docs: record canonical contract details established by Task 2
- `c4886dc` - 2026-09-21 (pyrevo): feat: canonical schemas and backend-independent normalization (Task 2)
- `6667297` - 2026-09-21 (pyrevo): test: canonical schema/normalization contract tests (Task 2)
- `f8b2dd2` - 2026-09-21 (pyrevo): feat: add initial implementation for Task 2 - canonical schemas and backend-independent normalization
- `28526af` - 2026-09-21 (Massimiliano Volpe): Merge pull request #7 from pyrevo/spiffy-monkey
- `121cb49` - 2026-09-21 (pyrevo): docs: restore M0 artifacts and untrack .pi runtime state (Task 1 review fixes)
- `a917adb` - 2026-09-21 (pyrevo): fix: make package importable and tests runnable from repository root (PLAN Task 1)
- `c8bf225` - 2026-09-21 (pyrevo): fix: correct spelling of 'annotater' in documentation files
- `9e8e5d2` - 2026-09-21 (pyrevo): fix: restore .DS_Store entry in .gitignore and add .pi to ignored files
- `a3b96ec` - 2026-09-21 (pyrevo): feat: add detailed agent instructions and specifications for Polars-Bio parity initiative
- `02122f1` - 2026-09-21 (pyrevo): feat: add documentation for agents, issue tracker, and triage labels
- `a560421` - 2026-09-21 (Massimiliano Volpe): Merge pull request #6 from pyrevo/feature/polars-bio
- `cb4527d` - 2026-09-21 (pyrevo): fix: harden polars-bio engine and parser paths

## [0.1.0-alpha.2] - 2025-12-11

### Added
- Streamlit interactive web application for genomic coordinate annotation against GFF3/GTF/BED.
- Pybedtools integration for core intersect calculations.
- VCF query format support and VCF result export.
- Gene list extraction and clipboard integration with external tools (e.g. DAVID).
- Results filtering based on overlap status and feature attribute parsing (Name, ID).

### Commits in 0.1.0-alpha.2 (21 commits)
- `377eeb9` - 2025-12-11 (Jyotirmoy Das): Merge pull request #5 from pyrevo/feature/vcf-support
- `ee93ef0` - 2025-12-10 (Massimiliano Volpe): feat(ci): add polars-bio
- `3e6717b` - 2025-12-10 (Massimiliano Volpe): ci: add features
- `5e65843` - 2025-12-09 (Massimiliano Volpe): feat: Add robust VCF export functionality
- `0b56f29` - 2025-12-09 (Massimiliano Volpe): feat: Restore VCF support with 0-based coordinate fix
- `d9d43cc` - 2025-12-09 (Massimiliano Volpe): Merge pull request #4 from pyrevo/feature/streamlit-app
- `1f00ce9` - 2025-12-09 (Massimiliano Volpe): Merge main into my-feature, resolving conflicts
- `8b206f1` - 2025-12-05 (Massimiliano Volpe): feat: Add copy to clipboard for gene lists and update DAVID link
- `88906c7` - 2025-12-05 (Massimiliano Volpe): fix: Correct column mapping logic for bedtools output
- `7d0e758` - 2025-12-05 (Massimiliano Volpe): fix: Keep more columns from GFF files in bedtools operation
- `7ba8b88` - 2025-12-05 (Massimiliano Volpe): fix: Prioritize annotation gene names over coordinate names
- `2621d2c` - 2025-12-05 (Massimiliano Volpe): fix: Extract Name and ID attributes from GFF3 files
- `8802851` - 2025-12-05 (Massimiliano Volpe): fix: Improve results filtering and gene name detection
- `c9bd44f` - 2025-12-05 (Massimiliano Volpe): feat: Add results filter for overlap status
- `314440b` - 2025-12-05 (Massimiliano Volpe): fix: Improve column naming and add overlap indicator
- `434f106` - 2025-12-05 (Jyotirmoy Das): Merge pull request #2 from pyrevo/feature/streamlit-app
- `3f2283e` - 2025-12-05 (Massimiliano Volpe): fix: Correct pybedtools cleanup method
- `6b66079` - 2025-12-05 (Massimiliano Volpe): docs: Add new features to How to Use section
- `7b26639` - 2025-12-05 (Massimiliano Volpe): docs: Add future features roadmap
- `3a18fa3` - 2025-12-05 (Massimiliano Volpe): feat: Add biologist-friendly features
- `524c493` - 2025-12-05 (Massimiliano Volpe): feat: Add Streamlit web application for genomic coordinate annotation

## [0.1.0-alpha.1] - 2025-06-30

### Added
- Initial developer prototype and containerized configuration for SciLifeLab Serve deployment.

### Commits in 0.1.0-alpha.1 (3 commits)
- `65054bb` - 2025-06-30 (Massimiliano Volpe): Merge pull request #1 from JD2112/devel
- `d0aca6b` - 2025-06-27 (jd2112): Updated and launched on serve
- `a5fc572` - 2025-06-27 (jd2112): first devel version

## [0.0.1] - 2024-05-09

### Added
- Initial project scaffold and repository initialization.

### Commits in 0.0.1 (1 commit)
- `2fc8261` - 2024-05-09 (Massimiliano Volpe): Initial commit
