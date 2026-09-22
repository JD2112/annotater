# Implementation notes

Living audit log for the Polars-Bio parity initiative. Task 1 recorded the
baseline; this section records the **Task 2.5 dependency/runtime/reference
audit**.

## Task 2.5 — dependency/runtime/reference audit (2026-09-21)

### Supported environment

| Item | Value |
|---|---|
| Python | 3.12.14 (venv at `.venv`, created by `uv` 0.11.8) |
| OS (audit host) | macOS arm64 |
| bedtools | v2.31.1 at `/opt/homebrew/bin/bedtools` (Homebrew, **system mode**) |
| pybedtools | 0.12.1 |
| polars | 1.44.2 |
| polars-bio | 0.35.1 |
| pandas | 3.0.6 |
| numpy | 2.5.3 |
| streamlit | 1.64.0 (native `st.testing.v1.AppTest` works headless) |
| pytest | 9.1.1 (with `pytest-cov` 7.1.0) |

The venv has no `pip` module; it is managed by `uv`. `uv.lock` is committed
alongside the exact-pinned `pyproject.toml` / `requirements.txt` and
`requirements-dev.txt`. `SPEC.md` contains **no normative minimum-Python
requirement**; **Python 3.12 is the currently tested and supported
runtime** established by Task 2.5. The exact dependency pins install on
Python ≥ 3.12 (verified installable under 3.14), so `pyproject.toml`
declares `requires-python = ">=3.12,<3.15"`; CI builds 3.12 and the
production Dockerfile uses `python:3.12-slim`. Python 3.13/3.14 satisfy
the range but are **not** part of the tested CI matrix; 3.10/3.11 cannot
install the pins at all (e.g. `numpy==2.5.3` requires ≥ 3.12).

### pybedtools mode: system binary, not embedded

- `pybedtools.check_for_bedtools()` → `True`; no `set_bedtools_path` was
  ever called. pybedtools 0.12.1 resolves the `bedtools` executable from
  `PATH` at call time (`shutil.which`); the command line observed in a live
  `intersect` was `bedtools intersect -a ... -wb -wa -b ...`.
- There is **no embedded/private bedtools binary** in the venv, and
  pybedtools 0.12.1 exposes no `utils.bedtoolsPath` attribute (removed API).
- Consequence: any environment (developer machine, container, CI) MUST
  install a bedtools binary and put it on `PATH`. CI installs it via
  `apt-get` (Ubuntu) / `brew` (macOS).

### polars-bio 0.35.1 API contract (observed, verified live)

- The historical `polars_bio.io.genomic_intervals.overlap` path **no
  longer exists**; `polars_bio.io` is a module, not a package. The current
  entry point is **top-level `polars_bio.overlap`** (and `nearest`,
  `count_overlaps`, `coverage`, ...).
- `pb.overlap` signature (0.35.1):
  `(df1, df2, suffixes=('_1','_2'), on_cols=None, cols1=['chrom','start','end'],
  cols2=['chrom','start','end'], algorithm='Coitrees', low_memory=False,
  overlap_output='join', distinct_output=False, output_type='polars.LazyFrame', ...)`
- `overlap_output="join"` (default) returns joined pairs with `_1`/`_2`
  suffixes. `overlap_output="left"` returns **only left rows that overlap**
  (confirmed: it is NOT a left outer join — consistent with
  `docs/engine-contract.md` section 6).
- **Coordinate-system behavior (important):** since 0.35.1, polars-bio reads
  a coordinate-system metadata stamp set at I/O time; when metadata is
  missing it falls back to the global session option
  `datafusion.bio.coordinate_system_zero_based`, whose default is **1-based
  (closed intervals)** and it emits a `UserWarning` on every call.
  Upstream spec (biodatageeks/polars-bio,
  `openspec/.../coordinate-system/spec.md`) documents: 0-based = half-open
  `[start, end)`, 1-based = closed `[start, end]`.
  Verified live: with the option explicitly set to `true`, touching
  intervals `[10,20)` vs `[20,25)` produce **0** overlap rows; with the
  default (unset, 1-based), the same inputs produce **1** (wrong, for
  AnnotateR's canonical 0-based data).
- `pb.overlap` accepts pandas DataFrames directly; observed output dtypes:
  `chrom_*` String, `start_*`/`end_*` int64.

### Observed current engine behavior (captured, not fixed)

Fixtures: query `chrA:100-200 (g1)`, `chrA:10-20 (g2)`, `chrA:2000-2100
(g3)`; annotation `chrA:150-250 (f1)`, `chrA:2000-2050 (f2)`.

| Scenario | BedtoolsEngine | PolarsBioEngine |
|---|---|---|
| inner, 1 match + 1 non-match | 2 rows; columns already exactly canonical `coord_*`/`annot_*` + `has_overlap` (bool) | 2 rows; but **both frames get `coord_` prefix**, `_1`/`_2` suffixes, internal `coord_pb_row_id_1` leaked |
| left, same fixture | 3 rows, unmatched query once with `has_overlap=False`; unmatched annotation fields are bedtools sentinels `.`/`-1` (not canonical NA) | 3 rows, unmatched query once with `has_overlap=False`; clean `coord_*` columns plus duplicated suffixed `coord_*_1/_2` columns |
| no match, inner | 0 rows | 0 rows |
| no match, left | 1 query row, `has_overlap=False` | 1 query row, `has_overlap=False` |
| touching `[10,20)` vs `[20,25)` | correctly 0 rows | **incorrectly 1 row** (1-based default re-interpretation, see above) |
| one-base `[10,20)` vs `[19,20)` | 1 row | 1 row |

These deviations are encoded as explicit assertions in
`tests/test_engine_contract.py`; the currently-failing ones are marked
`xfail(strict=True)` with the precise root cause so the suite stays green
while the deviations remain documented. Because the markers are **strict**,
any future run in which a guarded assertion unexpectedly passes fails the
suite with XPASS, forcing the obsolete marker to be reviewed and removed.
**Removing an xfail marker requires the engine to actually pass the
assertion** (Task 3/4 work).

### Current implementation limitations

1. **Polars-Bio coordinate-system mis-interpretation (highest risk).**
   `PolarsBioEngine` passes canonical 0-based half-open DataFrames to
   `pb.overlap` without declaring the coordinate system, so polars-bio
   0.35.1's 1-based global default applies. Touching intervals are reported
   as overlapping. Fix (explicit `pb.set_option` / metadata stamp) belongs
   to Task 3/4; the audit only records and tests against it.
2. **Polars-Bio result schema.** `PolarsBioEngine._post_process` prefixes
   *every* column with `coord_` (including annotation-frame columns),
   leaks the internal `pb_row_id` row-identity column, and keeps
   polars-bio `_1`/`_2` suffixes. Violates SPEC section 9.2 and
   `docs/engine-contract.md` section 3 (annotation fields must carry the
   `annot_` provenance prefix).
3. **Bedtools left-mode sentinels.** `BedtoolsEngine._bedtool_to_df` keeps
   bedtools `-loj` sentinel values (`.` / `-1`) in unmatched annotation
   fields instead of canonical missing values (engine-contract section 6).
   Its `to_dataframe(header=None)` also positionally names 6-wide rows as
   BED6 (`name`/`score`/`strand`) before the engine renames columns.
4. **Backend exception swallowing.** `PolarsBioEngine._join_overlap` catches
   *all* exceptions from `pb.overlap` and returns an empty frame
   (`logger.error` + `return pl.DataFrame()`) — SPEC section 9 requires
   explicit propagation. Same pattern in `_find_nearest`. Not changed here
   (no behavior changes in Task 2.5); must be fixed in Task 4.
5. **Python interpreter range.** Exact pins require Python ≥ 3.12
   (`numpy==2.5.3`). `SPEC.md` states no minimum-Python requirement, so
   there is no SPEC conflict: 3.12 is the Task 2.5 supported runtime and
   `pyproject.toml` / CI / Docker all declare it. Python 3.10/3.11 are not
   supported while these exact pins hold.
6. **Dependency disposition (audit complete).** Repository-wide audit
   (runtime code, tests, dynamic imports, export paths, documentation
   workflows, deployment files):
   - **removed:** `python-magic`, `validators`, `pyranges`, `altair` — no
     imports, dynamic imports, tests, or documentation-supported workflow
     uses any of them. `altair` remains available transitively via
     `streamlit`, so Streamlit charting is unaffected.
   - **retained:** `openpyxl` — concrete role: Excel export
     (`pd.ExcelWriter(engine='openpyxl')` in
     `streamlit_app/streamlit_app.py`, Excel download path).
   `requirements.txt`, `pyproject.toml`, and `uv.lock` were updated and the
   lockfile regenerated after removal. Every *remaining* runtime dependency
   has a verified current role: `streamlit` (app framework), `pandas`
   (canonical tables), `numpy` (`core/annotator.py`), `pybedtools`
   (Bedtools backend), `polars` (Polars-Bio backend dependency),
   `polars-bio` (Polars-Bio backend), `openpyxl` (Excel export), `plotly`
   (app charts, `streamlit_app.py`).
7. **`pb.overlap` warning noise.** Every polars-bio call in tests emits the
   missing-coordinate-metadata `UserWarning` (see limitation 1). It
   disappears once the engine declares the coordinate system.

### Contract tests added (Task 2.5)

**Scope note (honest Task 3 boundary):** Task 2.5 was a dependency/runtime
audit; it did **not** implement Task 3. While recording the observed
backend output contracts, the audit *opportunistically established an
initial engine-contract baseline*: `tests/test_engine_contract.py` carries
parameterized differential tests over both `BedtoolsEngine` and
`PolarsBioEngine`, and captures **five known deviations as strict xfails**.
This is intentionally a minimal harness, not the full Task 3 suite. Task 3
should later expand it systematically (more modes, strand handling, larger
synthetic fixtures, nearest-operator semantics, result-adapter edge cases)
and keep the strict-xfail guardrail convention.

- `tests/test_engine_contract.py` — both engines through identical
  fixtures: inner match/non-match, left mode preserving the non-matching
  query exactly once with `has_overlap=False`, no-match → 0 rows (inner) /
  preserved query row (left), plus SPEC section 4 boundary semantics
  (touching = no overlap, one-base = overlap, different chromosomes) and
  canonical-schema assertions (strict-xfail where currently deviated).
- `tests/test_parser_contract.py` — BED passthrough, GFF3 1-based
  inclusive → 0-based half-open, VCF POS/END span → canonical, custom CSV
  with declared coordinate system, and known formats immune to
  `declared_system` re-interpretation.
- `tests/test_streamlit_app_contract.py` — `st.testing.v1.AppTest`
  headless smoke run of `streamlit_app/streamlit_app.py`.

### Test command and baseline

Documented command (from repository root):

```bash
.venv/bin/python -m pytest
```

(or `python -m pytest` with the venv activated; `pytest.ini` pins
`testpaths = tests` and `pythonpath = .`).

Task 2.5 completion baseline: **142 passed, 5 xfailed, 0 failed, 0
skipped** (previous baseline: 117 passed). See the task report for the
exact three consecutive full-suite runs.

### CI

`.github/workflows/python-tests.yml` runs the suite on `ubuntu-latest` and
`macos-latest` with Python 3.12, installs the bedtools binary via
`apt-get`/`brew`, installs `requirements-dev.txt`, and runs `pytest`
(3.10/3.11 are omitted from the matrix because the exact pins cannot
install there; see limitation 5).

### Docker runtime verification (Task 2.5 review resolution)

- The production `Dockerfile` was updated from `python:3.10-slim` to
  `python:3.12-slim` to match the supported runtime. The image's
  `HEALTHCHECK` invokes `curl`; `python:3.12-slim` does not ship `curl`, so
  `curl` was added to the apt install list (previously the healthcheck
  would have failed with command-not-found in the final image).
- Verification was performed by building the image from scratch
  (`docker build --platform linux/amd64 -t annotater:task25 .` —
  successful; the earlier default-platform arm64 build is the one
  described in the platform limitation below) and running checks inside
  the resulting container. Observed output:
  - Python 3.12.14; `bedtools --version` → `bedtools v2.31.1`
    (`/usr/bin/bedtools`)
  - imports OK: `pybedtools` 0.12.1, `polars` 1.44.2, `polars_bio`
    0.35.1 (top-level `pb.overlap` callable), `streamlit` 1.64.0,
    `pandas` 3.0.6, `numpy` 2.5.3, `openpyxl` 3.1.5
  - AnnotateR core public API imports OK (`streamlit_app.core`:
    `BedtoolsEngine`, `PolarsBioEngine`, `FormatDetector`,
    `BEDParser`/`GFFParser`/`VCFParser`, `CoordinateConverter`,
    `CoordinateNormalizer`, canonicalization/validation helpers)
  - `curl` 8.14.1 present (`/usr/bin/curl`) — the only external command
    used by the `HEALTHCHECK` (`curl --fail
    http://localhost:8501/_stcore/health`) and the compose healthcheck
  - full test suite in an equivalent clean container (production image +
    mounted `tests/` + `pytest.ini`, ephemeral `pip install pytest
    pytest-cov`; the production image intentionally excludes test
    dependencies): **142 passed, 5 xfailed, 0 failed, 0 skipped**, exit
    code 0
- **Known platform limitation (found during Docker verification):**
  `polars-bio==0.35.1` publishes a manylinux **x86_64-only** wheel (no
  `aarch64` wheel); on Linux/aarch64, pip falls back to the sdist and the
  maturin/Rust source build fails in the slim image. The supported
  production image therefore targets `linux/amd64`
  (`docker build --platform linux/amd64 ...`), which matches the GitHub
  CI runners. Native arm64 Linux deployment would require either an
  upstream `aarch64` wheel or a Rust toolchain build stage — out of
  Task 2.5 scope. (macOS arm64 developer machines are unaffected: a
  `macosx_11_0_arm64` wheel exists.)
## Task 3 — engine parity harness (2026-09-22)

Task 3 built the systematic Bedtools <-> Polars-Bio parity harness and
used it to produce the first complete, executable deviation inventory.
**No engine behavior was fixed in this task** (the one exception is the
minimal canonical-adapter bug fix S1 below, which was required for the
harness to run at all and is engine-neutral). Polars-Bio was not touched;
all Polars-Bio deviations are assigned to Task 4.

### Harness design (`tests/parity/`)

Three layers of evidence, per `docs/engine-contract.md` section 14:

1. **Explicit expected fixtures** (`cases.py`, `fixtures.py`): tiny
   in-memory canonical tables (0-based half-open) with expected rows
   encoded as `(query_row, annot_row_or_None)` tuples in canonical row
   order, derived from `max(starts) < min(ends)` and the SPEC 7.2
   left-mode rules — never from backend output.
2. **Per-engine contract tests**: each engine runs through
   `run_and_canonicalize` (engine → raw result →
   `canonicalize_annotation_result`) and is compared with
   `assert_canonical_equal` — a strict comparator enforcing exact
   canonical column set + order, row count (multiplicity), row order,
   NA-aware values, real booleans, and contractually normative dtypes
   (`coord_start`/`coord_end` int64, `annot_start`/`annot_end` Int64,
   `has_overlap` bool).
3. **Differential comparison** (`test_differential_parity.py`):
   Bedtools canonical result vs Polars-Bio canonical result on
   representative fixtures, in addition to layer 1+2.

Coverage areas: overlap (exact/partial/containment, one-to-many,
many-to-many, duplicates), boundary off-by-one matrix (incl.
zero-based coordinates and `chr0`/`chr10` lexical trap), left-join
(UNM = canonical missing, not bedtools `-loj` sentinels), metadata
provenance (colliding names, arbitrary/numeric/boolean/missing values,
column order, reserved prefixes), deterministic ordering (inputs placed
out of coordinate order), strand (`use_strand=False` neutrality only),
and the error/failure contract (SPEC 9.2). Raw-layer diagnostics
(`test_backend_raw_diagnostics.py`) attribute each deviation to its
exact layer and record positive controls for conformant layers.

xfail discipline: markers are EXPLICIT per (case, engine) with
root-cause reasons (registry in `tests/parity/fixtures.py`);
`xfail_strict = true` is now global in `pytest.ini`. A fixed deviation
XPASSes and fails CI until its stale marker is removed; a new
non-conforming case fails loudly instead of silently xfailing.
`tests/test_engine_contract.py` was shrunken to smoke-level raw-output
contract tests; all five Task 2.5 strict xfails were migrated into the
parity harness with equal-or-better coverage (none lost).

### Current deviation inventory (Task 3)

**Polars-Bio (all assigned to Task 4):**

- **P1 — non-canonical result schema.**
  `PolarsBioEngine._post_process` prefixes BOTH frames with `coord_`,
  retains polars-bio `_1`/`_2` suffixes, leaks the internal `pb_row_id`
  column, and no `annot_*` columns exist.
  `canonicalize_annotation_result` therefore rejects every non-empty
  output (`CanonicalSchemaError`) before any semantic comparison.
  Violates SPEC 6 (exact canonical column set with provenance prefixes)
  and SPEC 9.2 (provenance must not be guessed by suffix heuristics);
  engine-contract section 3.
  *Pinned by:* every non-empty canonical-level parity case (36 strict
  xfails), `test_polars_raw_inner_output_is_canonical` (raw layer), and
  all differential cases.
- **P2 — coordinate system never declared.**
  `PolarsBioEngine` does not set polars-bio's coordinate-system option,
  so polars-bio 0.35.1's global default (1-based CLOSED intervals)
  re-interprets canonical 0-based half-open data: touching intervals
  (`[10,20)` vs `[20,25)`) are reported as overlapping. Violates SPEC 5;
  engine-contract section 4. The deviation is in the RAW overlap call
  (wrong row set before any post-processing).
  *Pinned by:* 5 touching/boundary strict xfails plus
  `test_polars_raw_touching_intervals_do_not_overlap`.
- **P3 — `pb.overlap` failures swallowed.**
  `_join_overlap` catches ALL exceptions and returns an empty frame
  (log only), converting backend failure into a plausible empty result.
  Violates SPEC 9.2. *Pinned by:*
  `test_polars_overlap_backend_failure_propagates` (strict xfail).
- **P4 — `pb.nearest` failures swallowed.** Same pattern in
  `_find_nearest`. Violates SPEC 9.2. *Pinned by:*
  `test_polars_nearest_backend_failure_propagates` (strict xfail).

**Bedtools:**

- **B1 — empty-input guard drops left rows.**
  `BedtoolsEngine.intersect` returns an empty frame whenever EITHER
  input is empty, so `how="left"` with an empty annotation table drops
  every query row instead of preserving them as unmatched. Violates
  SPEC 7.2; engine-contract section 6. *Pinned by:*
  `left_empty_annotation_table[bedtools]` (strict xfail).
- **B2 — missing metadata lost.** A missing metadata value on a matched
  row round-trips as the `'.'` sentinel and the column degrades to
  string, instead of canonical missing. Violates SPEC 6 /
  engine-contract section 8. *Pinned by:*
  `metadata_missing_values_matched_rows[bedtools]` (strict xfail).
- **B3 — numeric-looking string metadata re-typed.** String metadata
  such as `'3.5'` round-trips as float `3.5` because
  `BedTool.to_dataframe` re-infers dtypes from text. Violates SPEC 6
  (deterministic metadata preservation) and SPEC 10.3. *Pinned by:*
  `metadata_string_numeric_looks[bedtools]` (strict xfail).
- **B4 — raw left sentinels.** Raw left-mode output keeps bedtools
  `-loj` sentinel values (`'.'`/`'-1'`) in unmatched annotation fields
  instead of canonical missing. Currently masked at the public level by
  `canonicalize_annotation_result`; the engine should emit canonical
  missing directly (engine-contract sections 6/8; Task 5). *Pinned by:*
  `test_bedtools_raw_left_unmatched_uses_canonical_missing` (strict
  xfail).
- **B5 — result-parsing failures swallowed (DISCOVERED in Task 3).**
  `BedtoolsEngine._bedtools_to_df` catches ALL
  `BedTool.to_dataframe` exceptions and returns an empty DataFrame —
  the same SPEC 9.2 violation class as P3/P4, on the Bedtools side.
  *Pinned by:* `test_bedtools_result_parsing_failure_propagates`
  (strict xfail).

**Shared canonical adapter:**

- **S1 — all-matched frames with bool/int64 `annot_*` columns crashed
  canonicalization (DISCOVERED and MINIMALLY FIXED in Task 3).**
  `canonicalize_annotation_result` unconditionally executed
  `out.loc[~matched, annot_cols] = CANONICAL_MISSING`; under pandas 3.x
  the scalar is dtype-validated even when the mask is empty, raising
  `TypeError: Invalid value 'nan' for dtype 'bool'` for any all-matched
  result carrying a bool annotation column (verified on pinned pandas
  3.0.6: bool raises; a plain-int64 column was probed and does not). This is
  engine-neutral (it would crash for both engines) and blocked the
  harness from testing the metadata contract, so it was fixed with a
  one-line guard (`if (~matched).any():`) in
  `streamlit_app/core/schema.py`. No matched-row semantics changed.
  *Pinned by:* `metadata_boolean_values` (the pre-fix crash case) and
  `metadata_numeric_values` (both engines now pass).

### Positive controls (layers that already conform)

- Bedtools **raw inner** output is already canonical (exact
  `coord_*`/`annot_*` schema + `has_overlap` bool):
  `test_bedtools_raw_inner_output_is_canonical` passes.
- Bedtools **ordering and multiplicity** are deterministic and match
  the canonical ordering rule for every ordering fixture, including
  duplicate-valued rows (rerun determinism verified).
- Polars-bio **left row reconstruction** (row-id join back onto the
  query frame) correctly preserves unmatched query rows at the RAW
  layer — its left-mode deviation is only the schema (P1), not row
  loss: `test_polars_raw_left_reconstructs_unmatched_queries`.
- **Empty inputs** produce valid empty results for both engines (0
  rows, full canonical schema after adaptation) — distinct from the
  swallowed-failure deviations above.
- **Unknown `mode`** raises an explicit `ValueError` for both engines;
  **malformed input** (missing `chr`) raises explicitly for both;
  **bedtools backend failure** (`BedTool.intersect` raising) propagates.
- Strand values round-trip as metadata and do not affect matching when
  `use_strand=False` (Bedtools; Polars-Bio blocked by P1 only).

### Documented gaps (not tested — not yet normative)

- `use_strand=True` semantics (SPEC 8.3; engine-contract section 10) —
  neither engine implements it; no fixture invents the behavior. Note
  for Task 6: `BedtoolsEngine._df_to_bedtool` places metadata columns
  in source order, so a `strand` column lands in the BED name position,
  not the BED6 strand position — `-s` semantics would misread it.
- `min_overlap` (engine-contract section 9): ambiguous mapping to
  bedtools `-f`/`-F`/`-r`/`-e` must be fixed in a dedicated task before
  parity is claimed.
- `contains`/`within`/`closest` (engine-contract sections 11-12):
  predicates not yet normative.

### Test command and baseline (Task 3)

Documented command (from repository root):

```bash
.venv/bin/python -m pytest
```

Task 3 completion baseline: **199 passed, 60 xfailed, 0 failed, 0
skipped** (previous baseline: 142 passed, 5 xfailed). The 60 strict
xfails are exactly the P1-P4/B1-B5 deviations above (see the inventory
for which fixture pins which deviation). Pinned environment: Python
3.12.14, bedtools 2.31.1, pybedtools 0.12.1, polars 1.44.2,
polars-bio 0.35.1, pandas 3.0.6.
