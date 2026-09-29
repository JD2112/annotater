# AnnotateR User Manual — Documentation Architecture Plan

**Status:** Proposal for maintainer review (pre-implementation)
**Date:** 2026-09
**Scope:** Documentation architecture only. No manual pages, no MkDocs
installation, no application changes, and no CI workflow exist yet as a
result of this plan.

**Authoritative sources this plan is grounded in:** `SPEC.md`
(normative scientific contract), `docs/engine-contract.md` (engine
contract), the current Streamlit UI (`streamlit_app/streamlit_app.py`,
`streamlit_app/core/engine_registry.py`,
`streamlit_app/config/settings.py`), the parser/normalization/schema code
(`streamlit_app/core/parsers.py`, `normalization.py`, `schema.py`,
`chromosome.py`), `docs/references.md` (external standards), and the
bundled fixtures in `data/examples/`. No user-facing semantics in this
plan are inferred from memory; where a behavior was verified against code,
the section says so.

---

## 1. Target audiences

| Audience | Needs | Where they are served |
|---|---|---|
| **Primary: researcher / bioinformatician** | Annotate genomic intervals through the web interface; knows BED/GFF/VCF loosely; must not need AnnotateR internals | Getting Started, Preparing Your Data, Annotation Operations, Using AnnotateR, Results and Export, Examples, Troubleshooting, FAQ |
| **Secondary: computational user** | Precise coordinate semantics, operation definitions, result schema, backend equivalence, reproducibility | Same pages, but with precise definitions, 1-base examples, the full result-schema page, and links into Technical Reference (SPEC, engine contract, benchmark) |
| **Tertiary: maintainer / developer** | Architecture, deployment, benchmark, implementation record | Technical Reference section (links into existing `docs/*.md` and `SPEC.md`); never mixed into the user journey |

Design rule: a user page must be understandable without opening any
`docs/*.md` developer file; a developer link at the bottom of a user page
("See the engine contract § 8.x") is allowed and encouraged, but the page
must be self-sufficient.

---

## 2. Recommended documentation stack

**Markdown sources + MkDocs + Material for MkDocs**, published on
**GitHub Pages** at `https://pyrevo.github.io/annotater/`.

### 2.1 Assessment against AnnotateR's actual needs

| Requirement | How the stack satisfies it |
|---|---|
| Version-controlled Markdown | All manual sources are plain `.md` in the repo, next to the existing `docs/*.md`; existing developer docs can be included in the site unchanged |
| Navigation | `mkdocs.yml` `nav:` gives a static, reviewable sidebar; the exact hierarchy is in § 6 |
| Search | Material's built-in full-text search plugin (ships with the theme, no extra package) |
| Tables | Standard Markdown/HTML tables render natively |
| Admonitions | Material admonitions (`!!! note`, `!!! warning`) for "valid zero result" vs "configuration error" and similar |
| Screenshots | Static PNGs under `docs/assets/screenshots/` (policy in § 9) |
| Diagrams | Monospace fenced-code interval diagrams (recommended; § 8) plus one optional Mermaid workflow figure |
| Code examples | Fenced code blocks; fixture files link to `data/examples/` in the repo |
| Links to primary specifications | Relative links to in-repo docs; GitHub-raw links to `SPEC.md`; external standards centralized in `docs/references.md` |
| GitHub integration | `edit_uri` ("Edit this page" → GitHub), GitHub Actions deployment, Issues link |
| Low maintenance burden | One build command (`mkdocs build`), one Python dependency (`mkdocs-material`), no Sphinx extension ecosystem, no Jupyter runtime |
| Future software-paper linkage | Stable per-page URLs (§ 16) that a paper can cite; the site itself is a citable artifact via the GitHub Release it is linked from |

### 2.2 Comparison against alternatives (AnnotateR-specific)

- **Sphinx:** AnnotateR has no Python API to document with autodoc and
  no notebook workflow; Sphinx would add heavy configuration
  (`conf.py`, extension pinning, theme theming) for pure narrative
  documentation and makes the docs build heavier than the app itself.
  Rejected.
- **Quarto:** Quarto's advantage is literate Jupyter execution and
  typesetting. AnnotateR's examples are *uploads into a Streamlit app*,
  not notebook cells; nothing in the manual requires embedded execution.
  Rejected.
- **Plain GitHub Markdown:** Already works for the current developer
  docs and stays in use for them. But it gives a researcher arriving from
  SciLifeLab Serve no single entry point, no search, no navigation, and
  no visual identity — exactly the "publication-quality manual" gap this
  plan closes. The manual cannot be "README + several .md files" because
  the primary audience will not read a repo.

**Recommendation: confirm MkDocs Material.** It is the only candidate
that covers navigation, search, admonitions, tables, and GitHub Pages in
a single build with one dependency, over Markdown sources that keep the
existing `docs/` files in place.

### 2.3 Plugin policy

No plugin zoo. Allowed additions beyond the theme:

1. `mermaid2` (optional, only if maintainers approve the single workflow
   figure in Mermaid; § 8.3). Everything else — search, tables,
   admonitions, dark mode — is in the theme.
2. If Mermaid is declined, zero plugins; the workflow diagram becomes a
   committed SVG or a monospace flow.

---

## 3. Rationale (summary)

- The manual's content is scientific narrative + UI walkthrough, not API
  reference → Markdown + Material is sufficient;
- Existing developer docs are already Markdown in `docs/` → same build
  can host them under Technical Reference with no duplication;
- Low maintenance is a hard constraint for a two-person project → one
  dependency, one build command, PR-time build validation;
- GitHub Pages + `main` deployment keeps docs continuously current and
  gives a stable URL for the README, SciLifeLab Serve, the Release, and a
  future software paper.

---

## 4. Layer responsibilities

| Layer | Answers | Must NOT do |
|---|---|---|
| **README.md** (repo landing) | What is AnnotateR, why use it, what it supports, 3-minute start, **where the full documentation is** (new badge/link) | Not become the manual; drop detailed option tables and coordinate tables once the manual exists (REDUCE) |
| **QUICKSTART.md** (developer fast path) | 5–10 min from clone/install to first local run, test command, dev-environment notes | Not explain semantic edge cases; it is for people running the code, not scientists using the app. Gets one pointer to the manual |
| **User Manual** (new, the deliverable) | Everything in § 5: file preparation, coordinate conventions, operation choice, option meaning, result interpretation, export, examples, troubleshooting, FAQ | Not duplicate developer docs; not restate SPEC verbatim (links to it); not depend on screenshots for meaning |
| **Technical / Developer docs** (existing `docs/*.md`, `SPEC.md`, `PLAN.md`) | Architecture, engine contract, benchmark, deployment, implementation record, references | Not be the normal user path; surfaced via the Technical Reference section of the site |

Overlap rule: when the same fact (e.g., "backends are interchangeable")
appears in all layers, README and QUICKSTART carry the one-sentence
version, the manual carries the user-facing explanation page, and
SPEC/engine-contract remain the normative source. The manual page links
down, never copies normative text.

---

## 5. Final sitemap

34 user pages + 7 technical-reference items.

```text
Home (index)

Getting Started
├── What is AnnotateR?
├── Quick start (use the app: upload → run → download)
└── The AnnotateR workflow (pipeline: upload → parse/normalize →
    annotate → canonical result → export; where each stage is in the UI)

Preparing Your Data
├── Query coordinates vs annotation features
├── Supported file formats
│     (BED · GFF3 · GTF · VCF · CSV/TSV/custom tables)
├── Coordinate systems (0-based half-open model, per-format conversion)
├── Chromosome identifiers (UCSC/Ensembl, auto-convert, mismatches)
└── Strand information (what strand is, missing strand, per-format)

Annotation Operations
├── Choosing an operation (decision aid — the section's front door)
├── Overlap
├── Minimum overlap (min_overlap)
├── Contains
├── Within
├── Closest (distance, ties, distance column)
├── Strand-aware annotation
└── Join behavior: keep all rows (left) vs matched only (inner)

Using AnnotateR
├── Uploading files (both uploaders, previews, custom column mapping)
├── Choosing an annotation engine (Bedtools vs Polars-Bio)
├── Configuring the analysis (sidebar: coordinates, chromosomes,
│     advanced options — one page, exact UI names)
├── Feature filtering (GFF/GTF feature types, default = gene)
└── Running the annotation (run button states, invalidation of stale results)

Results and Export
├── Understanding the results page (metrics, Show filter, result table)
├── Result columns and provenance (coord_*/annot_*, has_overlap,
│     distance, missing values)
├── Matched vs unmatched rows (incl. zero-result interpretation)
├── Downloading and exporting results (CSV/TSV/Excel, annotated VCF)
└── Charts and gene list

Examples (all with tiny deterministic fixtures)
├── Example 1: BED query against GFF3 gene annotations (overlap, left)
├── Example 2: Minimum-overlap filtering
├── Example 3: Strand-aware annotation of variants
├── Example 4: contains vs within on the same two intervals
└── Example 5: Finding the closest gene to variants (closest)

Reference for users
├── Troubleshooting
├── FAQ
└── Limitations

Technical Reference (developer material; deeper navigation allowed)
├── Scientific semantics and engine contract (wrapper page → SPEC.md,
│     docs/engine-contract.md)
├── Backend parity and benchmark (→ docs/benchmark.md)
├── Architecture (→ docs/architecture.md)
├── Deployment (→ docs/deployment.md)
├── Implementation notes (→ docs/implementation-notes.md)
├── External references (→ docs/references.md)
└── Legacy implementation (→ docs/legacy.md)
```

Depth check (primary audience, max 2–3 levels):

- supported formats → Home → **Preparing Your Data → Supported file
  formats** (2)
- operation choice → Home → **Annotation Operations → Choosing an
  operation** (2)
- result interpretation → Home → **Results and Export → Understanding
  the results page** (2)

---

## 6. Exact proposed MkDocs navigation

`mkdocs.yml` at the repo root; `docs_dir: docs`.

```yaml
site_name: AnnotateR
site_description: Genomic Coordinate Annotation Tool
docs_dir: docs
site_url: https://pyrevo.github.io/annotater/
edit_uri: edit/main/docs/

theme:
  name: material
  primary: "#006DAE"          # = streamlit_app/config/settings.py THEME.primaryColor
  scheme: default             # light by default, dark toggle available
  icon:
    favicon: assets/favicon.svg   # 🧬 glyph, matching the app's page icon
  features:
    - navigation.sections
    - navigation.top
    - content.code.copy
    - search.highlight
    - toc.follow

markdown_extensions:
  - admonition
  - tables
  - toc:
      permalink: true
  - pymdownx.details          # collapsible "show me the exact example rows"
  - pymdownx.highlight

nav:
  - Home: index.md
  - Getting Started:
      - What is AnnotateR?: getting-started/what-is-annotater.md
      - Quick start: getting-started/quick-start.md
      - The AnnotateR workflow: getting-started/workflow.md
  - Preparing Your Data:
      - Query coordinates vs annotation features: preparing-your-data/query-vs-annotation.md
      - "Supported file formats (BED, GFF3, GTF, VCF, CSV/TSV)": preparing-your-data/supported-formats.md
      - "Coordinate systems (0-based / 1-based)": preparing-your-data/coordinate-systems.md
      - "Chromosome identifiers (chr1 vs 1)": preparing-your-data/chromosome-identifiers.md
      - "Strand information": preparing-your-data/strand-information.md
  - Annotation Operations:
      - Choosing an operation: operations/choosing-an-operation.md
      - "Overlap": operations/overlap.md
      - "Minimum overlap (min_overlap)": operations/min-overlap.md
      - "Contains": operations/contains.md
      - "Within": operations/within.md
      - "Closest (nearest)": operations/closest.md
      - "Strand-aware annotation": operations/strand-aware.md
      - "Join behavior: left vs inner": operations/join-behavior.md
  - Using AnnotateR:
      - "Uploading files": using/uploading-files.md
      - "Choosing an annotation engine (Bedtools vs Polars-Bio)": using/engines.md
      - "Configuring the analysis": using/configuring.md
      - "Feature filtering": using/feature-filtering.md
      - "Running the annotation": using/running.md
  - Results and Export:
      - "Understanding the results page": results/results-page.md
      - "Result columns and provenance": results/result-columns.md
      - "Matched vs unmatched rows": results/matched-unmatched.md
      - "Downloading and exporting results": results/export.md
      - "Charts and gene list": results/charts-gene-list.md
  - Examples:
      - "BED query against GFF3 annotations": examples/bed-vs-gff3.md
      - "Minimum-overlap filtering": examples/min-overlap.md
      - "Strand-aware annotation": examples/strand.md
      - "Contains vs within": examples/contains-within.md
      - "Finding the closest feature": examples/closest.md
  - Troubleshooting: troubleshooting.md
  - FAQ: faq.md
  - Limitations: limitations.md
  - Technical Reference:
      - "Scientific semantics and engine contract": technical/scientific-contract.md
      - "Backend parity and benchmark": benchmark.md
      - "Architecture": architecture.md
      - "Deployment": deployment.md
      - "Implementation notes": implementation-notes.md
      - "External references": references.md
      - "Legacy implementation": legacy.md
```

Notes:

- Existing `docs/{architecture,engine-contract,benchmark,deployment,
  implementation-notes,references,legacy}.md` are included **in place**
  (no copy), so there is exactly one maintained copy of each. `SPEC.md`
  and `PLAN.md` live at the repo root and are **not** site pages; the
  `technical/scientific-contract.md` wrapper page carries a short,
  user-readable summary of the contract and links to both files on
  GitHub. `engine-contract.md` is folded under the same wrapper (linked
  second) rather than getting a seventh top-level technical entry —
  it is read only by people who have already read the SPEC.
- Page titles deliberately embed search synonyms (see § 6.1).

### 6.1 Search terminology plan

Users will search for synonyms, not our exact labels. Titles and H2s are
chosen so Material's search hits the natural terms:

| User may search for | Where the term appears in a title/H2 |
|---|---|
| annotation, annotate | "What is AnnotateR?", "Annotation Operations", "Annotation engine" |
| intersection, intersect | H2 on overlap page: "Overlap (interval intersection)" |
| overlap, overlapping | Overlap page title; "Minimum overlap" page |
| nearest, nearest gene | Closest page title: "Closest (nearest)" |
| closest | Closest page title; Example 5 title |
| containment, contains | Contains/Within page titles + H2 "Contains vs within: a directional pair" |
| BED, GFF, GFF3, GTF, VCF | Supported file formats page title (all five) + one H2 per format |
| strand, stranded | "Strand information", "Strand-aware annotation" |
| chromosome, chr1, chromosome naming | "Chromosome identifiers (chr1 vs 1)" |
| coordinates, coordinate system | "Coordinate systems (0-based / 1-based)" |
| 0-based, 1-based | coordinate-systems page title and H2 "Why touching intervals are not overlaps" |
| export, download | "Downloading and exporting results" |
| has_overlap | "Result columns and provenance" |

No keyword stuffing: each term appears once in a title and naturally in
one or two headings; the FAQ additionally covers phrased questions
("Why are touching intervals not overlaps?") for long-tail search.

---

## 7. Per-page purpose and key contents

### Home (`index.md`)

One screen: what AnnotateR is (2 sentences from the app's own
caption), a link to the live app (SciLifeLab Serve, once deployed) and
to Quick start, the five supported formats as chips, and links to the
three most-landed topics (Supported formats, Choosing an operation,
Results page). No feature bloat.

### Getting Started

**What is AnnotateR?** Purpose page. What it does (annotate genomic
intervals against a feature set in the browser), who it is for, the two
interchangeable backends in one paragraph, what it is NOT (not a
database, no persistence, single-user, no account). Links: workflow,
quick start, limitations.

**Quick start (use the app).** The researcher's 5-minute path: open the app
(local or deployed) → upload the two bundled example files (linked as
GitHub raw URLs from `data/examples/`, since hosted users do not have a
local checkout) → click **Run annotation** → look at the results →
download CSV. Explicitly *not* an install guide (that is
QUICKSTART.md's job for developers); a one-line pointer to it.
Screenshots S1 (upload state) and S3 (results) only.

**The AnnotateR workflow.** The pipeline, as it actually is in the
code: upload → format detection → parsing + normalization (chromosome
standardization, coordinate conversion to the canonical 0-based half-open
model) → interval operation on the chosen engine → canonical result →
display/export. One figure (workflow diagram, § 8.3). Each stage names
the UI region where the user sees it. This page is the map the rest of
the manual hangs on.

### Preparing Your Data

**Query coordinates vs annotation features.** The two roles. Query =
the intervals you want to annotate (your coordinates/variants);
annotation = the reference features you annotate against (genes,
exons…). One file per role; the same format can play either role (a BED
file can be the annotation file). Why provenance prefixes (`coord_` /
`annot_`) exist, foreshadowing the results pages. UI names: "Query
coordinates" and "Annotation features" uploaders.

**Supported file formats.** One H2 per format: BED, GFF3, GTF, VCF,
CSV/TSV/custom tables. Per format (verified against
`parsers.py`/`normalization.py`): required fields; optional metadata and
which GFF/GTF attributes are extracted (ID, Name, gene_id, gene_name,
transcript_id, gene_type, gene_biotype, Parent); source coordinate
convention; what AnnotateR converts; strand handling (BED column 6,
GFF/GTF column 7, VCF: none); typical real-world sources (UCSC/BioMart
downloads for custom tables); common errors (wrong delimiter, header in
BED, malformed VCF header/sample counts). External specs are **linked**
to `docs/references.md` entries, never reproduced. Upload-extension
table: query accepts `.bed .txt .tsv .csv .vcf`; annotation accepts
`.gtf .gff .gff3 .bed .txt .tsv .csv` (from the file uploaders — note
this asymmetry and explain: VCF is a query-only input in v0.1.0).

**Coordinate systems.** First-class page (§ 12 requirements):
- canonical model: 0-based half-open `[start, end)`, valid interval
  `start >= 0`, `end > start` (SPEC § 5);
- per-format source conventions table: BED 0-based half-open (no
  conversion); GFF3/GTF 1-based inclusive (`start := start − 1`,
  `end` unchanged); VCF `POS` 1-based, span from REF length or
  `INFO/END`; custom tables: user-declared, default 0-based;
- concrete one-base examples: GFF `101–200` → `[100, 200)`; VCF
  `POS=100 REF=A` → `[99, 100)`; VCF `POS=100 REF=ACGT` → `[99, 103)`;
  GFF `101–101` (1 bp) → `[100, 101)`;
- what "Auto-detect" in the UI actually means (verified from
  `normalization.py::coordinate_system_for`): for known formats the
  system is **fixed by the format specification** and the selector does
  not reinterpret them; the selector's 0-based/1-based choice declares
  the system for **custom files** (default 0-based);
- why touching intervals are not overlaps (half-open math:
  `[10,20)` and `[20,25)` share no base);
- where coordinates appear in results/exports: canonical 0-based
  half-open in CSV/TSV/Excel; the **annotated VCF export reconstructs
  1-based POS** (POS = coord_start + 1) — so exports are in the source
  convention of the format they are written in;
- admonition: do not "fix" GFF/BED numbers by hand before upload.

**Chromosome identifiers.** Styles (UCSC `chr1` / Ensembl `1`, the two
auto-convert styles; NCBI accession pattern is recognized but not a
convertible target in v0.1.0 — verified from `chromosome.py`), the
"Auto-convert if needed" behavior (when both styles are detected
differently, both files are standardized to UCSC style in the UI),
"Manual specification" target styles (UCSC / Ensembl / Keep original),
and what happens when names cannot be reconciled (warning; rows on
differently-named chromosomes simply never match — cross-chromosome
pairs never qualify for any operation).

**Strand information.** What strand is; where it comes from per format
(BED col 6, GFF/GTF col 7, VCF: not parsed → strand is missing for VCF
queries); canonical values `+`, `-`, or missing; the decisive rule (also
SPEC § 8.3): with strand matching on, a pair qualifies only if **both**
rows carry explicit equal strands; missing strand is **never a
wildcard** and unknown-vs-unknown is not a match. Link to the
strand-aware operation page.

### Annotation Operations

**Choosing an operation (decision aid).** The section front door and
the mandatory decision aid. Layout:

1. A four-question decision block (monospace or styled list), exactly
   the shape proposed in the brief, refined with the repo's semantics:

   ```text
   Want every feature that intersects the query by at least one base?
     → overlap
   …but only if a feature covers at least a fraction of the query?
     → overlap + minimum overlap (min_overlap)
   The annotation must lie completely inside the query?
     → contains      (query contains annotation)
   The query must lie completely inside the annotation?
     → within        (annotation contains query)
   No intersection needed — which annotation is nearest, even far away?
     → closest
   ```

2. A direction mnemonic table — the contains/within disambiguation,
   which quality criterion 4 makes non-negotiable:

   | Operation | Containing interval | Contained interval | Mnemonic |
   |---|---|---|---|
   | contains | **the query** | the annotation | "my regions, what features fit inside them" |
   | within | **the annotation** | the query | "my points, what feature sits around them" |

   with the identity note: identical intervals satisfy **both**, and the
   two predicates are directional inverses (SPEC 8.4/8.5).

3. "Modifiers, not modes": `min_overlap` (overlap mode only) and strand
   (applies to **all** modes) change qualification; left/inner changes
   which rows you see, not what qualifies (cross-link join page).

4. A compact matrix: operation × (overlap required? touching qualifies?
   min_overlap applies? strand applies? distance column?) — this matrix
   is the page users will bookmark.

Cross-links: the same decision block is referenced (not duplicated) from
the workflow page and the FAQ.

**Overlap.** Definition (positive half-open intersection, ≥ 1 base;
SPEC 8.1 / engine-contract § 4), the overlap + touching monospace
diagrams, one-base example, "multiple annotations → multiple rows"
note, link to min_overlap and join behavior.

**Minimum overlap.** The exact fraction-of-query rule (SPEC 8.2):
formula in plain words + monospace min_overlap diagrams; denominator is
the **query** length; inclusive threshold; per-pair evaluation (no
accumulation across annotations — also a FAQ entry); `0` = ordinary
overlap; UI slider appears only in overlap mode (verified from
`streamlit_app.py::_min_overlap_for`); left-mode behavior (a query whose
matches all fail the threshold appears once, unmatched).

**Contains.** Definition per SPEC 8.4 with the diagram; "explicitly NOT
min_overlap = 1.0" callout with the two counterexamples from the SPEC
(`Q [10,20), A [0,100)` vs `Q [0,100), A [10,20)`); boundary equality
qualifies; direction mnemonic repeated once; strand composes by AND.

**Within.** Mirror of contains (SPEC 8.5), its own diagram; the SPEC
counterexample `Q [10,20), A [5,15)` (min_overlap 0.5 passes, within
fails); the shared H2 "Contains vs within: a directional pair" lives on
this page and is linked from both; note that the two are never aliases
and equality satisfies both.

**Closest.** The normative distance definition (SPEC 8.6): exact integer
gap `max(0, a_start − q_end, q_start − a_end)`; the full closest
diagram set — overlapping: 0, touching: 0, one-base gap: 1, large gap
(e.g. 75), ties (all tied-nearest returned, no arbitrary pick, in
annotation input order); same-chromosome candidates only; strand
applied **before** selection; `distance` column is added to results
(≥ 0 integer; missing for unmatched left rows); `has_overlap` means
"an annotation was attached" here, not "they overlap"; min_overlap /
contains / within do not participate. This is the page where users
learn why touching ≠ overlap but touching distance = 0.

**Strand-aware annotation.** User-level page for the sidebar checkbox:
what turning it on does in each operation (AND-composition with the
interval predicate; for closest, pre-selection filtering so a nearer
opposite-strand feature cannot suppress a farther same-strand one); the
missing-strand rule (never a wildcard); the UI label's effect on the
"Advanced options" group header ("strand required").

**Join behavior: left vs inner.** "Keep all query rows (left join)" vs
"Matched rows only (inner join)" (exact UI labels). Left = every query
appears; unmatched exactly once with missing annotation fields and
`has_overlap = False`. Inner = only qualifying pairs; a query with no
qualifying annotation disappears entirely (zero rows possible). Decision
guidance: left if you need a complete downstream table of your input;
inner if you only want matches. This page is the authoritative home for
the left/inner difference (quality criterion: FAQ and troubleshooting
link here, they do not re-explain).

### Using AnnotateR

**Uploading files.** Both uploaders, accepted extensions, size limits
(app default 500 MB; SciLifeLab Serve platform cap 100 MB — link
Limitations), the preview panels (first 10 rows, canonical coordinates,
row count, detected format), and the **custom column mapping** flow
(chrom/start/end selectboxes, "None (single positions)" → end =
start + 1, declared coordinate system). Screenshot S1 lives on this
page (quick start links to it; one copy, one home).

**Choosing an annotation engine (Bedtools vs Polars-Bio).** Central
message, verbatim the brief's: **They are interchangeable execution
backends for the supported AnnotateR contract.** The user normally
chooses by environment/preference/characteristics, never by biology:
identical input + options ⇒ same canonical result, schema, order, and
exports (parity is test-enforced; link benchmark). Bedtools = external
binary (needs `bedtools` installed; the app's default); Polars-Bio =
in-process (no binary). An unavailable backend shows an explicit error
and the app does **not** silently fall back (verified from
`engine_registry.py`). Prohibited implications are listed as explicit
"this page does not say" notes: neither backend is more scientifically
correct, native backend options do not define AnnotateR semantics,
outputs are not expected to differ. Performance: one short,
benchmark-anchored paragraph (workload-dependent; Polars-Bio generally
faster for pair-producing operations at small–medium size; closest is a
shared canonical path with near-identical timing) + link.

**Configuring the analysis.** Sidebar tour with exact UI names:
"Query coordinates" / "Annotation coordinates" (Auto-detect vs
declaring 0-based/1-based for custom files — link coordinate-systems
page), "Chromosome ID handling" (Auto-convert / Manual + Target style —
link chromosome page), "Advanced options" (strand checkbox; min_overlap
slider, overlap mode only). Screenshot S2 (sidebar) here.

**Feature filtering.** The "Filter by feature type" multiselect: applies
to GFF/GTF annotation files only (filters the `feature` column);
options list (gene, transcript, exon, CDS, 5UTR, 3UTR, start_codon,
stop_codon); **default selection is `gene`** (verified from the UI —
this must be prominently documented: a user who uploads a GTF and
expects all features will otherwise get gene-only results); empty
selection = all features; a filter matching nothing warns and does not
run.

**Running the annotation.** The "Run annotation" button: enabled only
when both files are usable (custom query files additionally need the
mapping applied); configuration-signature invalidation (changing any
option clears stored results — you never see stale results); valid
zero-match is an info message, not an error; engine errors are shown
labeled, never as empty results (SPEC 9.2).

### Results and Export

**Understanding the results page.** Anatomy: provenance caption
(engine · operation · join), four metrics (Query rows, Result rows,
Matched rows, Unmatched rows — with the exact meaning of each), the
Show filter (All / Matched only / Unmatched only — it narrows the
displayed table **and the downloads** without mutating the canonical
result), the result table.
Screenshot S3 here.

**Result columns and provenance.** The user-facing schema page
(§ 14): core columns `coord_chr/coord_start/coord_end`,
`annot_chr/annot_start/annot_end`, `has_overlap`; why the
`coord_`/`annot_` prefixes exist (a column can come from only one
input); metadata preserved deterministically as
`coord_<name>`/`annot_<name>`; deterministic column order; matched rows;
unmatched left rows carry canonical missing in **every** `annot_*`
field; the closest `distance` column (nullable integer); no internal row
IDs or backend artifacts ever appear (and the old `coord_chrom_1`-style
columns from pre-parity exports are explicitly *not* the current
format). One small example table (§ 14.2).

**Matched vs unmatched rows.** Row multiplicity rules: one query ↔ N
qualifying annotations = N rows; unmatched query = exactly one row;
duplicate input rows are preserved, never collapsed; row order (query
input order, then annotation input order). The zero-result
interpretation lives here: with a left join, zero *matched* rows is a
valid biological outcome (see Troubleshooting for the decision path);
with an inner join, an empty table means "nothing qualified".

**Downloading and exporting results.** CSV / TSV / Excel buttons
(export exactly what the Show filter displays); file naming; the
**Annotated VCF** button (only when the query was VCF): reconstructs
1-based `POS` and writes matched annotations into `INFO` — unmatched
rows' missing annotations are simply absent from INFO; missing values
export as the VCF `.`; and the gene-list exports (.txt / .csv /
clipboard) for g:Profiler/Enrichr/DAVID/STRING. Screenshot S4 here.

**Charts and gene list.** What each chart shows and what it is for:
feature-type pie (only when a `feature` column exists), top-15
chromosome bar, top-10 gene bar + gene list. Explicitly
exploratory/summary, not part of the canonical result.

### Examples (inventory in § 10)

### Reference for users

**Troubleshooting** — § 11. **FAQ** — § 12. **Limitations** — user
reading of the README "Limitations": supported formats only; 32-bit
coordinate cap on the Bedtools backend (unreachable in real data);
in-memory processing; closest returns all ties (no k>1, no signed
upstream/downstream); single-user, no persistence; Serve 100 MB upload
cap; amd64-only production image; no strand in VCF queries.

### Technical Reference

`technical/scientific-contract.md`: a ~1-page user/developer bridge —
what "canonical result" means, the five operations in a table (one line
each), determinism, parity — then links to `SPEC.md` (GitHub raw),
`docs/engine-contract.md`, `docs/benchmark.md`, `docs/references.md`.
Everything else is the existing file included in place (see nav).
Nothing in this section is rewritten or duplicated.

---

## 8. Scientific diagram inventory

### 8.1 Recommended format: monospace fenced code blocks

| Format | Verdict |
|---|---|
| **Monospace text diagrams (fenced code)** | **Primary.** Precise to the base, diff-able in review, trivially updated, identical in light/dark, zero build dependency, copy-pasteable by users. Interval geometry is one-dimensional; monospace columns align perfectly for it. |
| Mermaid | Not suited to base-precise geometry (flowchart nodes are boxes, not intervals). One optional exception: the linear *workflow* figure (boxes/arrows only) — see 8.3. |
| Committed SVG | Fallback only if maintainers reject both monospace and Mermaid for the workflow figure; otherwise not introduced in v0.1.0. |
| HTML/CSS | Rejected: not diff-able, theme-fragile, harder to keep in sync with the text. |

Rule: every interval diagram is a fenced `text` block of two labeled
lines on a shared base scale, with explicit base numbers where a
one-base example matters. Diagrams live *with* their page (inline), not
in a shared assets folder, so they cannot drift from the prose.

### 8.2 Inventory (8 diagrams, all monospace unless noted)

| # | Diagram | Page | What it must show |
|---|---|---|---|
| D1 | overlap | operations/overlap | `Query: [----------)` / `Annotation:    [----------)` intersecting; label the shared bases; a second mini-row for the 1-base overlap `[10,20)` vs `[19,20)` |
| D2 | touching vs overlap | operations/overlap (and coordinate-systems) | `[10,20)` vs `[20,25)` sharing only the boundary point; "no base belongs to both → not an overlap"; contrast with D1 |
| D3 | min_overlap | operations/min-overlap | two rows: annotation covering < 50% of query (fails at 0.5) and ≥ 50% (passes); shade/mark the query fraction actually covered; denominator is the query, visually |
| D4 | contains | operations/contains | `Query: [----------------)` / `Annotation:    [------)` — annotation strictly inside query; plus a "boundary equality qualifies" mini-row (shared left edge) |
| D5 | within | operations/within | `Query:        [------)` / `Annotation: [----------------)` — query strictly inside annotation; boundary-equality mini-row |
| D6 | identical intervals | operations/within (H2 "directional pair") | one interval pair; "satisfies contains AND within" |
| D7 | closest distance set | operations/closest | five mini-rows on one scale: overlap → 0; touching (`a_start == q_end`) → 0; one-base gap → 1; large gap (75 bases between) → 75; and a tie row (two annotations at the same distance, both returned) |
| D8 | strand eligibility | operations/strand-aware | three rows: `+`/`+` qualifies; `+`/`-` excluded; `+`/missing excluded (missing ≠ wildcard); plus a closest-mode note: opposite-strand nearer feature cannot suppress a farther same-strand one |

(Workflow figure, optional, counted separately in 8.3.)

### 8.3 Workflow figure

The pipeline figure on "The AnnotateR workflow" is the only candidate
for Mermaid (boxes and arrows only — no geometry). Decision is left to
maintainers (§ 18): Mermaid via the single optional `mermaid2` plugin,
or a one-off committed SVG. A monospace flow (as in
`docs/architecture.md § 2`) is the zero-dependency fallback and is
acceptable.

---

## 9. Screenshot inventory and policy

### 9.1 Minimum set: 4 screenshots (not 5)

| # | File | Content | Where used |
|---|---|---|---|
| S1 | `upload.png` | Initial app **with both example files uploaded and previews visible** (merges proposed 1+2: the empty state adds no information the text can't convey, and a second shot of the same region is maintenance) | Quick start; Uploading files (one copy, linked from the other) |
| S2 | `configure.png` | Sidebar with "Advanced options" expanded and a non-default state visible (strand on → label shows "(strand required)"), so the screenshot doubles as documentation of that behavior | Configuring the analysis |
| S3 | `results.png` | Results page: provenance caption, four metrics, Show filter, result table with at least one matched and one unmatched row (use left join on the example files) | Understanding the results page |
| S4 | `downloads.png` | "Download results" buttons + open "Charts and gene list" expander | Downloading and exporting results |

The proposed fifth standalone screenshot (standalone "configuration/
sidebar" in default state) is **dropped** — S2 covers the sidebar and
adds the advanced-options state. Every screenshot is used at most
twice (primary page + one cross-page link).

### 9.2 Policy

- **Purpose:** screenshots explain the *layout and workflow of the app*,
  never interval semantics (diagrams D1–D8 own that) and never option
  definitions (prose owns that). If a screenshot's information could be
  stated in prose + one UI name, drop it.
- **Storage:** `docs/assets/screenshots/`, referenced from pages as
  `![...](../assets/screenshots/<name>.png)`; one PNG per state, no
  annotated composites (annotations age badly).
- **Naming:** lowercase, no dates, state-named (`upload.png`,
  `configure.png`, `results.png`, `downloads.png`), so a refresh is a
  same-name replacement.
- **Capture spec (fixed to make refreshes consistent):** 1440×900
  viewport, light theme (matches the app default), **no browser
  chrome**, app at a deterministic state built from the bundled
  `data/examples/` files only (deterministic content ⇒ screenshots are
  reproducible from the repo).
- **Update rule:** screenshots are captured during Phase 6; any UI
  change that alters layout or the captured widget states must update
  the affected PNG in the same PR (enforced by a line in the docs
  section of `AGENTS.md` added in Phase 1). Text must never depend on a
  screenshot for correctness: each screenshot is accompanied by a
  caption naming the exact UI controls.
- No screenshots captured during this planning task.

---

## 10. End-to-end example inventory

All five examples are complete (files → settings → run → expected
result), tiny, deterministic, and each answers a real scientific
question. Fixtures: E1 reuses the bundled `data/examples/` files
(they ship in the Docker image and are the app's own convention); the
other examples use new ≤ 4-row fixtures placed in `data/examples/`
with `example_` names (open decision on placement: see § 21). The
bundled `example_variants.vcf` stays as the *format* example for VCF
input (documented on the supported-formats page); E5 gets a dedicated
closest fixture so every distance regime is teachable.

| # | User question | Query | Annotation | Operation | Options | Expected conceptual result | Fixtures |
|---|---|---|---|---|---|---|---|
| E1 | "Which genes/exons overlap my list of regions?" | `example_coordinates.bed` (6 regions) | `example_annotations.gff3` (genes + exons) | overlap | left join; feature filter = gene **and** exon (must be changed from the gene-only default — the example deliberately teaches that) | 6 matched rows — region1, region3, and regionX each match **two** features (the gene and one exon: ENSE001, ENSE003, ENSE005) — plus 3 unmatched rows with missing `annot_*` (region2, region4, regionY); teaches N-matches-per-query. Row counts verified against the bundled fixtures; final values confirmed by a real run in Phase 4 | **already bundled** |
| E2 | "Keep only annotations covering at least half of my regions" | 3-row BED: one region fully covered, one 40%-covered, one 60%-covered | 3-row BED annotations | overlap + min_overlap | min_overlap = 0.5, inner join | exactly 2 rows (the 60% and 100%); the 40% region vanishes (inner) — same rerun shown with left join to contrast one unmatched row | **new** `example_min_overlap_coordinates.bed` / `example_min_overlap_annotations.bed` |
| E3 | "Which genes are on the same strand as my regions?" | 3-row BED query with explicit `+`/`-` rows | 3-row GFF3 annotation with one same-strand, one opposite-strand, and one missing-strand (`.`) overlapping gene | overlap | run **twice**: strand off, then strand on; left join | off: 3 matched rows (all geometric overlaps); on: only the same-strand pair qualifies — the opposite-strand and missing-strand genes are excluded (missing strand is not a wildcard); all 3 query rows remain under left join, 2 of them unmatched. Teaches the whole SPEC 8.3 strand rule in one minimal pair of runs | **new** `example_strand_coordinates.bed` / `example_strand_annotations.gff3` |
| E4 | "What's the difference between contains and within, concretely?" | **one** 3-row BED file played as the query | the **same** file played as the annotation (also demonstrates "the same format can be either role") | run **twice**: contains, then within | inner join | Rows A `[0,100)`, B `[40,60)` (inside A), C `[200,300)`: contains returns the pairs where the query contains the annotation (A⊇A, A⊇B, C⊇C); within returns the pairs where the annotation contains the query (A⊇A, B⊂A, C⊇C). The directionally distinctive rows — A⊇B appears only in the contains run, B⊂A only in the within run — are the takeaway; the identical-interval row C appears in **both** runs (D6). Final pair list confirmed by a real run in Phase 4 | **new** `example_contains_within.bed` |
| E5 | "For each variant, which gene is nearest, and how far away?" | 4-variant VCF: three on chr1 (one inside a gene, one 50 bp from a gene, one exactly midway between two genes), one on a chromosome with no annotations | 3-gene GFF3 on chr1 | closest | left join; also exercises the **Annotated VCF** export (query is VCF) | Teaches every D7 regime: overlapping variant → distance 0; 50-bp variant → distance 50; tie variant → **two** rows, same distance (all ties returned, no arbitrary pick); empty-chromosome variant → one unmatched row, missing `distance`. Final numbers confirmed by a real run in Phase 4 | **new** `example_closest_variants.vcf` / `example_closest_annotations.gff3` |

Each example page layout: question → the two files (path + full inline
content, since ≤ 3 rows) → exact sidebar settings → expected result as a
small table (or row summary) → "what this taught" one-liner. Expected
results in the manual will be produced by actually running the app
during Phase 4 (never hand-written), and the same inputs/expectations
are pinned in `tests/` where practical, so examples stay reproducible.

---

## 11. Troubleshooting structure

One page, organized as **symptom → likely cause → fix**, grouped:

**1. Upload and parsing**
- "Could not parse …" / file not recognized → wrong extension/content
  (e.g., GFF with `.csv` extension is fine by content; a BED with a
  header line is not), delimiter issues in custom tables → fix: check
  the format table, re-export from the source.
- Custom file: "map the columns" expander is blocking the run → apply
  the mapping (or choose "None (single positions)").
- Upload rejected as too large → app `MAX_FILE_SIZE_MB` (500) vs SciLifeLab
  Serve platform cap (100 MB) → split the file or run locally.

**2. Coordinate and chromosome problems (the zero-matches zone)**
- Wrong coordinate system declared for a custom file (1-based data
  declared 0-based) → off-by-one everywhere; re-declare and re-run.
- Chromosome naming mismatch (`chr1` vs `1`) with "Keep original" →
  nothing matches; use Auto-convert or Manual.
- NCBI accessions vs other styles → not convertible in v0.1.0; rename
  upstream.
- "No qualifying annotations were found" → **the decision callout
  (admonition)**: with a left join, zero *matched* rows while your
  query rows are present is a **valid biological zero-result**; with an
  inner join you see an empty table. Checklist to tell the two apart:
  (a) do the two files share any chromosome names *after* the
  announced conversion? (b) do intervals actually co-locate (spot-check
  one query against the annotation file)? (c) is the feature filter
  still the default `gene` when your annotation has e.g. only `exon`
  rows? (d) strand on + missing strand in one file ⇒ guaranteed zero
  matches. Only after (a)–(d) pass is "biologically none overlap"
  the answer.

**3. Option-related surprises**
- Strand on → zero or fewer matches (missing strand is not a wildcard).
- min_overlap > 0 → fewer matches (threshold is per annotation, no
  accumulation; inclusive; query-relative).
- Unexpectedly *many* rows → one query matches N annotations; use the
  Show filter.
- Expected an overlap, got touching → touching is distance 0 but not
  an overlap (D2; use closest if you want touching included).
- Expected matches but `contains`/`within` returned few → direction
  check (the D4/D5/D6 pair).

**4. Engine and environment**
- "Bedtools is unavailable in this environment" → the binary is
  missing locally / not in the deployment; choose Polars-Bio (no
  silent fallback happens; that is deliberate).
- Engine error during the run → real failure, never an empty valid
  result; report the labeled message (developers see the traceback).

**5. Results and export**
- "Unmatched" rows look odd → see Matched vs unmatched rows (one
  unmatched row per unmatched query, by design).
- Duplicate result rows → duplicate *input* rows or multiple matching
  annotations; duplicates are preserved, never collapsed.
- Multiple closest rows for one query → ties are all returned by
  design.
- Left vs inner gives different tables → link to the join page (the
  authoritative explanation lives there).
- Run is very slow → large inputs make `closest` the most expensive
  operation on **both** backends (shared canonical path; benchmark:
  ~2–4 min per engine at 100k×1M scale); pair-producing operations
  scale better; split the file or reduce the annotation set. Link:
  Limitations.
- Missing Excel button → openpyxl not installed (local run).
- VCF export: `.` values and POS shifted by one vs your file →
  expected (VCF missing values; canonical start + 1 = POS).

---

## 12. FAQ proposal

Questions that do not duplicate a troubleshooting symptom and that
answer a *concept*. Refinement of the proposed list: keep, add one
(feature-filter default — verified to be a real user trap), remove one
(candidate: "difference between left and inner" → that has an
authoritative page; FAQ keeps a one-line answer + link).

1. **Which engine (Bedtools or Polars-Bio) should I use?** —
   Interchangeable; pick by environment (binary availability) or
   preference; identical results guaranteed. Link: engines page.
2. **Why do I get multiple result rows for one query?** — One row per
   qualifying annotation (and per tied-nearest in closest). Link:
   matched/unmatched.
3. **Why are touching intervals not overlaps?** — Half-open boundary
   math, one-base example, D2; closest sees them at distance 0.
4. **Why can `closest` return several annotations for one query?** —
   Ties are all returned, deliberately, in annotation input order; no
   arbitrary one-tie pick.
5. **What does `has_overlap = False` mean?** — Left-join unmatched row
   (or, in closest mode: "no annotation was attached"). Link:
   result columns.
6. **Does `min_overlap` add up coverage from several annotations?** —
   No; each pair is judged alone; a small annotation covering 100% of
   itself but 20% of the query fails at 0.5.
7. **What happens when strand is missing?** — Off: irrelevant. On: the
   row can never form a stranded match (not a wildcard).
8. **Why do my BED and GFF numbers look different even for the same interval?** —
   0-based half-open vs 1-based inclusive; the conversion is explicit at
   parse time; after normalization everything is the same model. Link:
   coordinate systems.
9. **Why did my GTF annotation return only genes?** — The feature
   filter defaults to `gene`; select the types you need or clear the
   filter.
10. **Are Bedtools and Polars-Bio results guaranteed identical?** — Yes,
    for every supported operation (test-enforced parity); the backend
    changes where computation runs, never what is returned.

---

## 13. Existing-document reuse / migration matrix

| File | Class | Action |
|---|---|---|
| `README.md` | **REDUCE AFTER MANUAL EXISTS** | Trim the options/coordinate tables into one paragraph + "Full documentation →" badge (Phase 1); keep landing-page role. Fix the Documentation table to point at the manual site. |
| `QUICKSTART.md` | **KEEP AS-IS** (plus one pointer line to the manual in Phase 1) | Developer fast path; its option descriptions are short enough that duplication with the manual is acceptable for v0.1.0; re-trim only if drift appears. |
| `SPEC.md` | **HISTORICAL/NORMATIVE DEVELOPER ONLY → LINK FROM MANUAL** | Unchanged; the technical wrapper page links to it (GitHub raw). Never copied into site pages. |
| `PLAN.md` | **HISTORICAL/DEVELOPER ONLY** | Unchanged; not linked from the manual; may be archived later post-parity. |
| `docs/architecture.md` | **LINK FROM MANUAL** | Included in the site in place under Technical Reference (nav); no rewrite. |
| `docs/engine-contract.md` | **LINK FROM MANUAL** | Not a separate nav entry; linked second from `technical/scientific-contract.md`; included in the site so search reaches it. |
| `docs/references.md` | **LINK FROM MANUAL** (canonical external-reference hub) | Included in the site in place; user pages link to the *external* URLs via this file's entries, never copy specs. |
| `docs/implementation-notes.md` | **HISTORICAL/DEVELOPER ONLY** | Included in the site under Technical Reference (searchability), never referenced by user pages except where a user-visible fact needs a "why" footnote. |
| `docs/deployment.md` | **LINK FROM MANUAL** (maintainer) | Included in the site in place; user pages only link it from Limitations/Troubleshooting (upload caps, amd64). |
| `docs/benchmark.md` | **LINK FROM MANUAL** | Included in the site in place; the engines page and technical section link to it. |
| `docs/legacy.md` | **HISTORICAL/DEVELOPER ONLY** | Included in the site under Technical Reference; no user-page references. |
| `docs/release-plan-0.1.0.md` | **KEEP AS-IS** (process record) | Not in site nav; not linked from the manual. |
| `docs/polars-bio_manual.pdf` | **ALREADY REMOVED** (see `docs/legacy.md`) | Nothing to do; the online Polars-Bio docs in `references.md` remain authoritative. |
| *(audit extra)* `docs/FUTURE_FEATURES.md` | **CANDIDATE FOR REMOVAL** | Stale (lists VCF as unmerged feature-branch work and Polars-Bio integration as future, both done). Out of this plan's scope; flagged for a maintainer decision. |
| *(audit extra)* `docs/*.resolved` | **HISTORICAL/DEVELOPER ONLY** | Retained scratch; not in site nav. |
| *(audit extra)* `data/examples/annotated_coordinates.csv` | **CANDIDATE FOR REMOVAL / REGENERATION** | Stale pre-canonical sample export: its columns still carry leaked `coord_chrom_1`-style backend suffixes, i.e. exactly the artifact the canonical schema forbids. Either regenerate it from a real run or delete it; do not let it survive into the manual era. |

Maintenance rule adopted: **one maintained copy per fact** — user prose
lives in the manual, normative prose in SPEC/engine-contract, developer
records in `docs/`; cross-links in both directions; README/QUICKSTART
carry at most one-sentence versions.

---

## 14. Result-schema documentation design

### 14.1 Page structure (`results/result-columns.md`)

1. The core column table (7 columns + `distance` in closest mode):
   name, meaning, type, present when.
2. **Why the prefixes exist** — one paragraph: `coord_*` can only come
   from your coordinate file, `annot_*` only from the annotation file;
   both inputs can have a `name` column, and the result stays
   unambiguous.
3. **Metadata preservation** — every extra input column is preserved
   as `coord_<name>` / `annot_<name>` in input order; nothing is
   dropped, nothing is renamed beyond the prefix.
4. **Matched vs missing** — matched rows carry a valid annotation
   interval in every `annot_*` field; unmatched left rows carry
   missing in *every* `annot_*` field (coordinates and metadata alike);
   `has_overlap` is the single boolean that distinguishes the two.
   In closest mode, `has_overlap` means "an annotation was attached"
   (including separated rows), and unmatched rows additionally have a
   missing `distance`.
5. **Distance** — integer ≥ 0, exact base count of the gap (cross-link
   closest page + D7).
6. **What you will never see** — internal row IDs, backend sentinels
   (`.`, `-1`), library-suffixed columns (`_1`, `_2`, `_right`); the
   old-style `coord_chrom_1` columns in any pre-v0.1 export are legacy
   artifacts, not the current format.
7. **Determinism** — same inputs + options ⇒ same table, same column
   order, same row order, on both backends (reproducibility note for
   the computational audience).

### 14.2 The small example table (design; exact values verified in Phase 4)

Query: 2 BED rows (region A on chr1 with `name`, region B on chr2).
Annotation: 2 GFF3 genes. Result (left join, overlap):

| coord_chr | coord_start | coord_end | coord_name | annot_chr | annot_start | annot_end | annot_feature | annot_gene_id | has_overlap |
|---|---|---|---|---|---|---|---|---|---|
| chr1 | 100000 | 100500 | regionA | chr1 | 50000 | 150000 | gene | GENE1 | True |
| chr2 | 200000 | 200300 | regionB | — (missing) | — | — | — | — | False |

Caption: "Region B had no qualifying annotation: one row, all
`annot_*` fields missing, `has_overlap=False`."

---

## 15. Coordinate-system documentation design

Covered in full as the `preparing-your-data/coordinate-systems.md` page
(spec in § 7). Structural commitments:

- The page leads with the canonical model, not with formats: "AnnotateR
  computes and exports in one model: 0-based half-open `[start, end)`.
  Everything else is converted at the door."
- Per-format conversion table (BED: none; GFF3/GTF: `start − 1`; VCF:
  span rule then `start − 1`; custom: declared, default 0-based) with
  one worked one-base example per format, including the 1-base
  interval edge case.
- "Auto-detect vs manual" subsection states the verified truth: known
  formats are interpretation-fixed by specification; the selector only
  *declares* custom files' system.
- "Why touching intervals are not ordinary overlaps" subsection with D2
  and the half-open one-base argument, and a forward link to closest
  (where touching is distance 0).
- "Coordinates in your results" subsection: exports carry canonical
  0-based half-open values; the annotated VCF export is the one place a
  format convention is reconstructed (POS = start + 1, 1-based).
- Admonition against hand-adjusting source coordinates.

---

## 16. Publication readiness, stable URLs, versioning

**Stack URL:** `https://pyrevo.github.io/annotater/`. Stable per-page
URLs follow directly from the nav (e.g.
`…/annotater/operations/choosing-an-operation/`); Material trailing-slash
URLs + `site_url` make them canonical. These URLs are suitable for:

- README badge ("Documentation ↗");
- the SciLifeLab Serve app listing/README;
- the GitHub Release `v0.1.0` body;
- a future JOSS-style software paper (cites the site and per-page URLs).

**Versioning decision for v0.1.0: latest-only documentation.** No
versioned docs site, no `version/` branch strategy, no docs-version
selection widget. Rationale: one release exists; the repo itself keeps
every past version of every page in git history (any old URL can be
reconstructed from a tag); introducing MkDocs versioned-nav or a docs
artifact pipeline now is infrastructure with no reader. **Trigger to
revisit:** the first breaking semantic change (post-0.1.0); then adopt
Material's `version:` + `extra` version selector and keep one
historical version per major release. The site footer will carry
"Version 0.1.0" (Material footer text) so readers always know what they
are reading.

---

## 17. GitHub Pages deployment design

(Design only — no workflow file is created in this task.)

- **Workflow:** one `docs.yaml` (`.github/workflows/docs.yaml`), modeled
  on the standard Material GitHub-Pages template, two jobs:
  1. `build` — always: checkout → Python 3.12 → `pip install
     -r docs/requirements-docs.txt` → `mkdocs build --strict` (strict:
     warnings, including broken internal links, fail the build) →
     upload Pages artifact (`actions/upload-pages-artifact`).
  2. `deploy` — needs `build`, `if: github.ref == 'refs/heads/main'
     && github.event_name == 'push'`, `environment: github-pages` with
     `url: ${{ steps.deployment.outputs.page_url }}`
     (`actions/deploy-pages@v4`).
- **Triggers:** `push` to `main` with path filters (`docs/**`,
  `mkdocs.yml`, `docs/requirements-docs.txt`, the workflow file) plus
  `pull_request` on the same paths (build-only validation — every PR
  touching docs gets a strict build) plus `workflow_dispatch` for
  manual re-deploys.
- **Source branch / deploy point:** `main` only. No tag-based docs for
  v0.1.0 (consistent with the latest-only decision in § 16); the
  `v0.1.0` tag's docs are the commit's `docs/` contents.
- **Timing:** the workflow lands in Phase 7 but **deployment activates
  with v0.1.0**: the repo Settings → Pages must be switched to "GitHub
  Actions" first; per the release plan, docs publication is added as an
  explicit step in `docs/release-plan-0.1.0.md` (after the tag, before
  or concurrent with the app deployment) and verified with one real
  fetch of the live URL.
- **Failure policy:** `--strict` in both PR and main builds; a broken
  link or missing page blocks merge/deploy.

---

## 18. Documentation dependencies

**Recommendation: a dedicated `docs/requirements-docs.txt`** (matching
the repo's existing `requirements.txt` / `requirements-dev.txt`
convention; a `pyproject` optional group is rejected because
`pyproject.toml` describes the *application* and docs tooling is not an
app install path).

Minimal contents (pinned in Phase 1):

```text
mkdocs-material==9.*
mermaid2==0.*          # only if maintainers approve the Mermaid workflow figure;
                       # otherwise omitted — the theme alone is sufficient
```

`mkdocs` itself comes in as `mkdocs-material`'s dependency. No other
plugins, no `pymdown-extensions` (the extensions used — admonition,
tables, toc, details, highlight, emoji — are bundled with
mkdocs-material). Build is verified in CI (`mkdocs build --strict`), so
the file is the only docs dependency surface to maintain.

---

## 19. Visual identity

- **Site name:** `AnnotateR`.
- **Tagline (`site_description`):** "Genomic Coordinate Annotation
  Tool" — the app's own `Settings.DESCRIPTION`; the site header then
  reads exactly like the app tab title.
- **Logo/favicon:** the app's `st.set_page_config(page_icon="🧬")` is
  the existing brand mark. Reuse it as an emoji-based `favicon.svg`
  (a few lines of SVG text) — no new logo is generated, no asset
  hunting. No header logo beyond the site name (avoids a design system).
- **Theme:** Material defaults with `primary: #006DAE` — the exact
  `primaryColor` from `settings.py THEME` — so the docs accent matches
  the app's sidebar/buttons. Light scheme by default with the built-in
  dark toggle. No custom font, no custom CSS (the app's typography
  polish is app-scoped and must not leak into a docs theme).
- **Tables/code:** Material defaults; interval diagrams are monospace
  fenced blocks (§ 8); `content.code.copy` enabled for fixture snippets.
- Footer: authors (matching the app footer), "Version 0.1.0", license
  (BSD-3-Clause), and the GitHub link.

---

## 20. Implementation phases

Ordered so that each phase is independently reviewable and no phase
depends on an unapproved design decision:

1. **Phase 1 — Skeleton and validation.** Branch `docs-website-skeleton`
   (or fold into manual implementation as maintainers prefer). Create
   `mkdocs.yml` (nav exactly as § 6), `docs/requirements-docs.txt`,
   `docs/index.md`, all section directories with placeholder pages,
   favicon; verify `mkdocs build --strict` locally. Add the
   "screenshots must be refreshed on UI changes" line to `AGENTS.md`.
   README/QUICKSTART get the manual pointer lines (manual link points
   at the in-repo plan until Phase 7 publication).
2. **Phase 2 — Getting Started + Preparing Your Data.** Five data-prep
   pages + three getting-started pages; coordinate-system page and
   format pages written against the verified parser/normalization
   behavior; external links via `references.md` entries.
3. **Phase 3 — Annotation Operations + scientific diagrams.** All seven
   operation pages, the decision aid (choosing-an-operation), and
   diagrams D1–D8 in their final monospace form. This is the
   scientifically most sensitive phase — each page's definitions are
   checked line-by-line against SPEC § 7–8 and engine-contract
   § 4–12 during review.
4. **Phase 4 — Using AnnotateR + Results/Export + Examples.** Five
   using-pages, five results pages (incl. the § 14 schema table), five
   example pages; **run every example in the app and paste the real
   outputs**; new E2/E4 fixtures added to `data/examples/` with the
   same PR; pin example expectations in tests where practical.
5. **Phase 5 — Troubleshooting, FAQ, Limitations + Technical
   Reference integration.** Troubleshooting/FAQ/Limitations pages;
   `technical/scientific-contract.md` wrapper; include existing
   developer docs in the nav; verify every cross-link with
   `--strict`.
6. **Phase 6 — Screenshot capture + visual QA.** Capture S1–S4 per the
   § 9.2 spec from a deterministic state; visual pass (light + dark),
   table/diagram rendering, search spot-checks of the § 6.1 terms.
7. **Phase 7 — Docs CI + GitHub Pages publication.** `docs.yaml` per
   § 17; PR validation green; switch Pages source; deploy on the
   v0.1.0 release commit (gated on § 16 decision); flip README badge to
   the live URL; verify from the Release, Serve listing, and README.

Phase 2/3 can be one PR each; 4/5 may be split per page group. No phase
modifies application code except adding the tiny example fixtures to
`data/examples/` (Phase 4, explicitly scoped as documentation assets).

---

## 21. Open maintainer decisions

1. **Mermaid vs SVG vs monospace for the single workflow figure**
   (§ 8.3). Default if no objection: monospace, zero plugins.
2. **Example fixture placement:** `data/examples/` (recommended —
   ships in the image, app convention) vs `docs/assets/examples/`.
3. **Stale artifacts:** delete or regenerate
   `data/examples/annotated_coordinates.csv` (leaked legacy
   `coord_chrom_1`-style columns); disposition of the stale
   `docs/FUTURE_FEATURES.md` (update or delete). Both are separate
   small PRs outside the manual.
4. **Docs publication timing:** with the v0.1.0 tag (recommended,
   § 16/§ 17) vs slightly after; and whether `pull_request` docs-build
   validation should be a required check for all PRs or docs-path-only
   (recommended: docs-path-only).
5. **Feature-filter default (`gene`)** is documented as-is in the
   manual (verified UI behavior). Confirm that is intended for v0.1.0
   (i.e., no UI change) — if the default should become "all features",
   that is an app change outside this plan.
6. **README reduction depth** in Phase 1: minimal (pointer + docs table
   row) vs aggressive (also cut the operations/coordinate tables).
   Recommended: aggressive, since the manual owns those tables.

---

## Appendix A — Verification record (for this plan)

Facts in this plan verified against the repository (not memory):

- UI labels, help text, defaults (engine default Bedtools; feature
  filter default `gene`; min_overlap slider only in overlap mode;
  "Auto-detect" semantics; join labels; Show filter; upload extensions;
  button enablement; stale-result invalidation) — `streamlit_app.py`,
  `engine_registry.py`, `settings.py`.
- Per-format coordinate systems and VCF span rule —
  `normalization.py`, `parsers.py`, `architecture.md § 4`.
- Chromosome styles and auto-convert target (UCSC) —
  `chromosome.py`, `streamlit_app.py`.
- GFF/GTF extracted attributes — `parsers.py::GFFParser._parse_attributes`.
- Canonical result column contract, ordering, missing-value rules —
  `schema.py`, SPEC § 6/7, engine-contract § 3/8.
- Bundled fixtures and the stale sample export — `data/examples/`.
- `docs/polars-bio_manual.pdf` already deleted — `docs/legacy.md`.
- Benchmark characterizations (closest = shared path; pair ops
  workload-dependent) — `docs/benchmark.md`.

## Appendix B — Review passes performed on this plan

Two review passes were run on the draft; structural fixes were applied
in place, no manual prose was written.

**Pass 1 — User-documentation review (first-time bioinformatician).**
Checks: find-what-to-upload, query-vs-annotation clarity, operation
choice, result interpretation, zero-match troubleshooting. All five are
covered by a dedicated page within two nav levels. Findings fixed:
(a) quick start must link example files as GitHub raw URLs (hosted
users have no checkout); (b) added a "run is very slow" troubleshooting
entry (large inputs / `closest` cost); (c) screenshot references were
inconsistent (5 numbered shots vs the 4-shot policy) — unified to S1–S4;
(d) the Show-filter description was self-contradictory ("cosmetic") —
corrected: it narrows the displayed table *and the downloads* without
mutating the canonical result (verified against
`streamlit_app.py::render_results_section`/`_render_downloads`).

**Pass 2 — Technical/scientific review (SPEC, engine contract, code,
fixtures).** Findings fixed:
(a) E3 originally claimed the bundled files demonstrate strand
filtering — they do not (every matching pair in the fixtures is
same-strand); redesigned E3 with a dedicated strand fixture.
(b) E5 originally claimed the bundled VCF shows a tie, a 50-bp case, and
an unmatched (chrY) variant — none of which exist in
`example_variants.vcf` (all five variants are on chr1/chr2/chrX with at
least one chr1 annotation; no chrY variant); redesigned E5 with a
dedicated closest fixture covering all D7 regimes.
(c) E1 expected result recomputed against the fixtures: with gene+exon
selected, region1/region3/regionX each match two features (6 matched
rows), not 5.
(d) E4 pair expectations made explicit (A⊇B only in contains, B⊂A only
in within, identical C in both) and flagged for confirmation by a real
run in Phase 4.
(e) Confirmed against code: "Auto-detect" semantics (known formats are
interpretation-fixed; the selector only declares custom files), VCF is
query-only (annotation uploader extensions), feature-filter default
`gene`, engine default Bedtools, auto-convert target UCSC, GFF/GTF
extracted attribute list, canonical column contract. No other
structural issues; all normative statements in the plan point at SPEC
§ 5–8 / engine-contract § 4–12 rather than restating them.