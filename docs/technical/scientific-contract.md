# Scientific semantics and engine contract

This page is the **user-facing entry point** to the binding technical
documentation. For developers, scientists reviewing semantics, and CI
maintainers, the authoritative documents live in the
[repository](https://github.com/pyrevo/annotater) — they are linked
here, deliberately *not* republished on this site, so there is exactly
one copy of the truth.

## What binds the product

| Document | What it fixes |
|---|---|
| [`SPEC.md`](https://github.com/pyrevo/annotater/blob/main/SPEC.md) | The normative scientific contract: §5 canonical data model (0-based half-open, canonical columns, missing-value semantics), §6 format parsing/normalization, §7 engine contract and **backend parity**, §8 the four relation modes (overlap, contains, within, closest) and their modifiers (the min_overlap fraction rule, the contains/within directional predicates, and the canonical closest distance `max(0, a_start − q_end, q_start − a_end)`), §9 result and export semantics |
| [`docs/engine-contract.md`](https://github.com/pyrevo/annotater/blob/main/docs/engine-contract.md) | The detailed engine-level contract both backends must satisfy, and the allowed/forbidden backend-specific behavior |
| [`docs/architecture.md`](https://github.com/pyrevo/annotater/blob/main/docs/architecture.md) | The result-adapter boundary: why no backend column names leak into the canonical result |

The user-facing pages of this site paraphrase these documents; where
they ever seem to disagree, **the SPEC wins** (see
[AGENTS.md](https://github.com/pyrevo/annotater/blob/main/AGENTS.md)
for the repository's source-of-truth priority order).

## The invariants, in one paragraph

AnnotateR normalizes every input to a canonical 0-based half-open
model at parse time; executes exactly one interval operation on the
selected engine; and returns a canonical result whose columns are
prefixed by provenance (`coord_*` / `annot_*`) with a single canonical
missing value. Both engines — Bedtools and Polars-Bio — are
**contractually required to return identical results** for every
supported operation and option (SPEC §7); that parity is enforced by
the test suite, not by hope
([Backend parity and benchmark](../benchmark.md)).

## Where each technical topic lives

- **Interval semantics and operations** → SPEC §8 (paraphrased with
  diagrams in the [Annotation Operations](../operations/choosing-an-operation.md)
  section).
- **Canonical schema, metadata preservation, missing values** →
  SPEC §5/§9 (paraphrased in
  [Result columns and provenance](../results/result-columns.md)).
- **Parity and performance** → [Backend parity and benchmark](../benchmark.md)
  (the full benchmark methodology is in `docs/benchmark.md` in the
  repo).
- **Deployment, Bedtools availability, TMPDIR, Serve packaging** →
  [Deployment](../deployment.md) (`docs/deployment.md`).
- **External format specifications** (UCSC BED, GFF3, GTF, VCF) →
  [External references](../references.md) (`docs/references.md`).
- **Legacy R implementation and license provenance** →
  [Legacy implementation](../legacy.md) (`docs/legacy.md`).
- **Implementation notes and open items** →
  [Implementation notes](../implementation-notes.md).

## Documentation governance

- The plan that shaped this site (audiences, sitemap, review record) is
  [`docs/manual-plan.md`](https://github.com/pyrevo/annotater/blob/main/docs/manual-plan.md)
  in the repo — a process document, intentionally excluded from the
  site.
- Semantic changes to any of the linked documents must change the
  application (and its tests) in the same task; the docs in this site
  are updated to follow, never to lead.