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

## Task 4 — Polars-Bio contract compliance (2026-09-22)

**Result: P1–P4 resolved.** `PolarsBioEngine` now satisfies the engine
contract for the covered parity surface: canonical result schema with
explicit provenance, 0-based half-open coordinate semantics,
deterministic ordering, left-mode reconstruction, and backend error
propagation. All 55 strict Polars-Bio xfails from Task 3 were converted
to passing tests (their markers were removed); the 5 Bedtools xfails
(B1–B5) remain, out of scope for this task.

### PolarsBioEngine rewrite (deviations P1–P4)

The engine was rewritten around a single explicit mapping strategy.
The old code passed pandas DataFrames into `pb.overlap` and repaired
the output with a broken `_right`-suffix heuristic; it also set no
coordinate-system metadata and swallowed all backend exceptions.

- **Per-frame coordinate stamping (P2).** Both backend frames are
  stamped `frame.config_meta.set(coordinate_system_zero_based=True)`
  on the polars frame (polars 1.44 `config_meta`, read by polars-bio
  0.35.1's `_metadata.get_coordinate_system`). This is the narrowest
  mechanism: it declares the coordinate system exactly where the data
  lives, without mutating the process-wide
  `datafusion.bio.coordinate_system_zero_based` option (polars-bio's
  own default is 1-based CLOSED, the wrong model for canonical data).
  No global option is read or written, so BedtoolsEngine and
  PolarsBioEngine can run in one process without interfering, and the
  engine is correct regardless of any external global setting.
- **Explicit provenance mapping (P1).** Backend frames carry a
  collision-safe positional row-identity column
  (`_pb_query_row_id` / `_pb_annot_row_id`, suffix-bumped if the name
  already exists). `pb.overlap`/`pb.nearest` are called with explicit
  `suffixes=("_1", "_2")`, `cols1`, `cols2`. The adapter builds the
  rename map from the KNOWN input schema (never from suffix
  heuristics on the output) and validates the raw output as an exact
  column-set match; any mismatch raises `CanonicalSchemaError`
  (SPEC 9.2). Row IDs are dropped before the public result.
- **Deterministic ordering.** Rows are sorted by
  `(query_row_id, annotation_row_id)` — input row identity, never
  coordinate — giving the canonical order (query input order, then
  annotation input order) including for duplicate-valued rows.
- **Left mode.** Unmatched queries are reconstructed by set-difference
  on query row IDs and appear exactly once with canonical missing
  annot fields and `has_overlap=False` (SPEC 7.2), in canonical
  position (sorted by row ID with the matched rows).
- **Error propagation (P3, P4).** `pb.overlap` / `pb.nearest` are
  called without any try/except: backend exceptions propagate. A 0-row
  result with no exception is a genuine no-match (valid empty), not a
  swallowed failure.
- **Input validation.** Engine entry validates both inputs with
  `validate_canonical_interval_table`; malformed input raises
  `CanonicalSchemaError` instead of reaching the backend.
- **Empty results.** A 0-row raw result short-circuits to a genuinely
  empty result (`inner`: empty frame; `left`: unmatched query rows).

### Newly discovered in Task 4

- **P5 (fixed) — `pb.nearest` phantom rows for empty annotation.**
  With an empty annotation frame, `pb.nearest` still emits one row per
  query with ALL annotation fields null (k=1 with no neighbor); the
  adapter previously turned these into `has_overlap=True` rows with
  NA annotation coordinates. `_nearest` now drops rows whose
  annotation row ID is null, so closest mode with an empty annotation
  table returns a genuinely empty result (SPEC 9.2). *Pinned by:*
  `test_polars_inner_empty_inputs_return_empty_result`.
- **`pb.nearest` distance dtype** is integer when the gap is integral
  (observed `Int64` for integral inputs); consumers must not assume
  float.

### Focused regression tests (`tests/test_polars_bio_engine.py`)

New module pinning guarantees the parity suite only exercises
indirectly: half-open semantics with the global option explicitly set
to the wrong model (per-frame stamping wins); the engine leaves the
process-wide option untouched; raw output has no backend artifacts
(no `_1`/`_2` suffixes, no row-ID columns, exact canonical column
set); raw output is accepted as-is by
`canonicalize_annotation_result` for every how/mode combination
(`closest` declares `distance` as an extra column); empty-input
matrix (all mode/how/emptiness combinations); left with empty
annotation preserves queries; closest distance column semantics;
malformed input raises explicitly.

### Test command and baseline (Task 4)

Documented command (from repository root):

```bash
.venv/bin/python -m pytest
```

Task 4 completion baseline: **262 passed, 5 xfailed, 0 failed, 0
skipped** (previous baseline: 199 passed, 60 xfailed). The 5 remaining
strict xfails are exactly B1–B5 (Bedtools). Pinned environment: Python
3.12.14, bedtools 2.31.1, pybedtools 0.12.1, polars 1.44.2,
polars-bio 0.35.1, pandas 3.0.6.

### Remaining known deviations (unchanged, Task 5/6)

B1 (empty-input guard drops left rows), B2 (missing metadata lost),
B3 (numeric-looking string metadata re-typed), B4 (raw left
sentinels), B5 (result-parsing failures swallowed) — all Bedtools;
see the Task 3 inventory above. Documented gaps (non-normative):
`use_strand=True`, `min_overlap`, `contains`/`within` (Task 6).

## Task 5 — Bedtools contract compliance (2026-09-22)

**Result: B1–B5 resolved.** `BedtoolsEngine` now satisfies the engine
contract on the covered parity surface: canonical result schema with
explicit provenance, lossless metadata round-trip, canonical missing on
unmatched left rows, deterministic empty-input handling, and backend
error propagation. All 5 strict Bedtools xfails from Task 3 were
converted to passing tests (their markers were removed). `use_strand`,
`min_overlap`, and `contains`/`within` semantics remain documented
gaps (Task 6).

### BedtoolsEngine rewrite (deviations B1–B5)

The engine was rewritten around an identity-only adapter. The old code
serialized the WHOLE input frame (stringified metadata, `.fillna('.')`)
into BED, read the raw output through pandas dtype inference
(`to_dataframe` with no dtype argument), guessed provenance from column
counts, and swallowed every `to_dataframe` exception.

- **Identity-only serialization (B2, B3).** The bedtools text file now
  carries ONLY `chr`/`start`/`end` plus a collision-safe internal
  row-identity column (`_bt_query_row_id` / `_bt_annot_row_id`,
  suffix-bumped if the name exists) per side. User metadata never
  crosses the text boundary: after matching, every published
  coord/annotation/metadata value is re-attached from the ORIGINAL
  validated input frames by row identity. Missing values become
  canonical missing (`pd.NA`), never the `'.'` sentinel (B2);
  numeric-looking strings keep their type (B3); numpy scalars are
  reduced to the Python scalars the canonicalizer's `astype(object)`
  publication uses, so raw output matches the canonicalized expected
  values cell-for-cell.
- **Structural sentinel handling (B4).** Raw output is read with
  `to_dataframe(header=None, dtype=str)` — pure text, no dtype
  inference. Match determination is structural, not value-based:
  bedtools `-loj` fills unmatched annotation fields with sentinels
  (`.`/`-1`), and the adapter reads the INTERNAL annotation row-id
  column, where `'.'` can only be a backend sentinel (row ids are
  engine-generated integers `0..n-1`). Real user metadata values such
  as `'.'` or `'-1'` are re-attached from the input frame and can never
  be mistaken for missing values. Unmatched rows carry canonical
  missing in every `annot_*` field and `has_overlap=False`.
- **Deterministic empty-input handling (B1).** Both inputs are
  validated with `validate_canonical_interval_table` first (malformed
  input raises, never a silent empty result). With an empty annotation
  table, `left` mode returns every query row unmatched WITHOUT
  invoking bedtools (the canonical result is already known); `inner`
  returns a genuinely empty result. A 0-row raw result with no
  exception is a genuine no-match, never a swallowed failure.
- **Error propagation (B5).** `intersect`/`closest`/`to_dataframe` are
  called without any try/except; backend and conversion exceptions
  propagate to the caller (SPEC 9.2). `pybedtools.cleanup()` runs in a
  `finally` block.
- **Deterministic ordering.** Rows are sorted by
  `(query row id, annotation row id)` — input row identity, never
  coordinate — giving the canonical order (query input order, then
  annotation input order) including for duplicate-valued rows.
- **Raw layout validation.** The raw frame must have exactly
  `2 * columns_per_side` columns (8 unstranded) or `2 *
  columns_per_side + 1` for `closest -d` (9 unstranded); any other
  layout raises `CanonicalSchemaError` (no positional guessing).

### Newly discovered / handled in Task 5

- **`use_strand=True` needed an explicit strand column.** bedtools
  `-s` requires a strand in column 6; the old code only worked by
  accident (user `strand` metadata happened to cross the boundary in
  column order). The stranded serialization now carries
  `chr/start/end/<row id>/. (score)/strand` per side (12 raw columns,
  13 with `closest -d`): the user's `strand` metadata when present,
  else `'.'` (unstranded, matches nothing under `-s`). The unstranded
  path is unchanged. The flag itself is still forwarded to bedtools
  `-s` unchanged — `use_strand` SEMANTICS remain Task 6 scope.
- **bedtools `closest -d` distance is its own non-normative value**:
  for `[15,25)` vs `[100,200)` it reports 76 (the Polars-Bio `nearest`
  gap for the same pair is 75). Closest's full semantics stay Task 6;
  the adapter only guarantees a lossless `Int64` round-trip of the
  backend-reported value (`NA` when no feature was found).
- **`bedtools closest` requires genomically sorted input** (pre-existing
  bedtools requirement, unchanged): unsorted query/annotation frames
  raise `BEDToolsError` from the binary itself, which now propagates
  explicitly instead of being swallowed.

### Focused regression tests (`tests/test_bedtools_engine.py`)

New module pinning guarantees the parity suite only exercises
indirectly: raw output is exactly the canonical column set (no BED
field names, row-id columns, or `col_N` padding) and is accepted as-is
by `canonicalize_annotation_result` for every how/mode combination
(`closest` declares `distance`); the real-user-value regression — user
metadata values `'.'`/`'-1'` survive a matched round-trip verbatim,
genuinely missing values round-trip as `pd.NA` (never `'.'`), and
numeric-looking strings (`'3.5'`, `'00123'`) keep their type; left
mode with an empty annotation table is produced deterministically with
ZERO bedtools invocations (monkeypatched proof); backend
(`BEDToolsError`) and conversion (`to_dataframe`) failures propagate;
duplicate-valued rows keep the (query identity, annotation identity)
expansion order; `closest` keeps the lossless `Int64` distance extra
column; `use_strand` is forwarded to bedtools `-s` unchanged.

### Test command and baseline (Task 5)

Documented command (from repository root):

```bash
.venv/bin/python -m pytest
```

Task 5 completion baseline: **282 passed, 0 xfailed, 0 failed, 0
skipped** (previous baseline: 262 passed, 5 xfailed). No known-deviation
xfails remain for either engine. Pinned environment: Python 3.12.14,
bedtools 2.31.1, pybedtools 0.12.1, polars 1.44.2, polars-bio 0.35.1,
pandas 3.0.6.

### Remaining known deviations (Task 6)

None for the canonical covered surface. Documented gaps (non-normative,
unchanged in Task 5): `use_strand=True` semantics (flag forwarded,
matching semantics undefined), `min_overlap` (forwarded to `-f` in
overlap mode only), `contains`/`within` (`-f 1.0`/`-F 1.0`
placeholders), `closest` full semantics (distance definition, tie
breaking).

## Task 6A — min_overlap semantics (2026-09-23)

**Scope:** fix one backend-independent meaning for the existing single
`min_overlap` parameter and lock it with contract + parity tests.
Strand/contains/within/closest semantics remain out of scope (Task
6B–6E backlog, untouched).

### Normative definition (SPEC 8.2)

`min_overlap` is the **minimum fraction of the canonical query
interval covered by a single annotation interval** for that
query/annotation pair to qualify as a match:

```text
overlap_length = max(0, min(q_end, a_end) - max(q_start, a_start))
query_length   = q_end - q_start
qualifies iff  overlap_length > 0 AND overlap_length / query_length >= min_overlap
```

- Query-relative: denominator is the query length. NOT the annotation
  fraction, NOT reciprocal (bedtools `-r`), NOT either-side (`-e`),
  NOT coverage summed across annotation rows.
- Inclusive threshold (`>=`); ordinary positive overlap still required
  (touching intervals never match, even at `min_overlap=0`).
- Valid domain: `None` (no threshold) or a number in `[0, 1]` (int or
  float — integers `0`/`1` are valid numeric equivalents, normalized to
  `float`). Negative, >1, NaN, ±inf, booleans, and non-numeric types
  raise `ValueError`; invalid values are never clamped or forwarded to
  a backend.
- Left mode: the threshold participates in match determination. A
  query whose annotation matches all fail the threshold is emitted
  exactly once, unmatched (`has_overlap=False`, no failing match row).

### Validation policy

Validated once in the shared `AnnotationEngine` constructor via the
module-level `validate_min_overlap` (in `streamlit_app/core/annotator.py`),
so both backends validate identically and the rejection happens
**before any backend execution** (proven by a monkeypatched no-call
test). One consistent exception type: `ValueError`, matching the
existing public API's invalid-parameter handling (unknown `mode`).

### Architecture: shared canonical post-filter

```text
canonical inputs
      ↓
ordinary backend overlap (NO backend fraction option for min_overlap)
      ↓
canonical matched pairs
      ↓
shared min_overlap_keep_mask filter   ← SPEC 8.2 predicate, one code path
      ↓
left reconstruction (if how="left")
      ↓
canonical output
```

`min_overlap_keep_mask(df, min_overlap)` in
`streamlit_app/core/annotator.py` is the single contract-level
predicate; both engines call it on their canonical-column frames
(after backend matching, before left reconstruction). Unmatched
(-loj sentinel) rows are excluded from the predicate and pass through
unchanged; queries losing all matches are then reconstructed as
unmatched by the existing left logic.

### Bedtools strategy

`min_overlap` is **no longer mapped to bedtools `-f`** (the historical
behavior). Reasons, all demonstrated during this task:

- bedtools v2.31.1 rejects `-f 0.0` outright (its range is
  `(0.0, 1.0]`, verified against the installed binary): the old
  wiring made the valid no-op threshold `0.0` a hard `BEDToolsError`;
- the contract is backend-independent by definition — applying the
  identical shared predicate removes any reliance on bedtools'
  version-specific fraction arithmetic (double division + `<` cutoff);
- `-f`/`-F` remain internally available and are still used only by the
  non-normative contains/within placeholders (unchanged, Task 6C/6D
  scope).
- For the record: bedtools v2.31.1 `-f` was empirically verified to be
  a fraction of A (the query) and to use an inclusive cutoff, so the
  old behavior agreed with the new contract for `0 < f <= 1`; the
  `f = 0` crash and the version-coupling are why the shared filter was
  preferred anyway.

### Polars-Bio strategy

Pinned polars-bio 0.35.1 `overlap` exposes **no fraction mechanism**
(signature + docstring verified against the installed package), so
AnnotateR's query-fraction contract is enforced explicitly with the
same shared predicate over the ordinary `pb.overlap` pairs. The
`coordinate_system_zero_based=True` per-frame metadata handling is
untouched; no global configuration introduced.

### Tests

- `tests/parity/cases.py`: `MIN_OVERLAP_CASES` — 25 cases × 2 engines
  (50 parameterized tests) covering: full overlap at thresholds 0/0.5/1.0; exactly-half boundary
  (0.49/0.50/0.51, pins `>=`); one-base boundary (0.10/0.11); touching
  at 0.0; annotation-larger-than-query at 1.0 (query-relative);
  query-larger-than-annotation (0.10/0.11); reciprocal distinction
  (annotation 10% covered, query 100% → match at 1.0, would fail under
  `-r`); no aggregation across two 0.30 annotations (inner + left);
  one-pass-one-fail; multiple qualifying in annotation input order;
  duplicate queries (inner + left, incl. all-failing left); duplicate
  annotations; metadata (incl. missing value) through filtering; left
  mixed qualifying/failing/no-match; 1/3 precision boundary (Task 6A
  review: pins IEEE-754 exactly-rounded division at an irrational
  threshold); within-placeholder scope (Task 6A review: the filter is
  NOT applied in the non-normative `within` mode). 8 of them are also in
  `DIFFERENTIAL_CASES` (direct engine-vs-engine layer, which now
  forwards `case.engine_kwargs`).
- `tests/parity/test_min_overlap_parity.py`: every case against BOTH
  engines via the strict canonical comparator (explicit expected rows,
  never backend output).
- `tests/test_min_overlap_validation.py`: invalid values
  (`-0.01`, `-1`, `1.01`, `2`, NaN, ±inf, `True`, `False`, `"0.5"`)
  raise `ValueError` for both engines; valid values (`None`, `0`,
  `0.0`, `0.5`, `1`, `1.0`) accepted with documented int normalization;
  monkeypatched proof that an invalid value never invokes either
  backend; both engines accept/reject exactly the same value set.

### Behavior changes

- **Bug fixed:** `min_overlap=0.0` previously crashed BedtoolsEngine
  (bedtools `-f 0.0` is a hard error); it is now a valid no-op
  threshold, matching the UI help text ("0 = any overlap").
- **Bug fixed:** PolarsBioEngine previously ignored `min_overlap`
  entirely; it now enforces the same contract.
- For `0 < min_overlap <= 1` in plain overlap mode, BedtoolsEngine
  results are unchanged (bedtools `-f` agreed with the contract there);
  the code path changed (post-filter instead of `-f`) but results do
  not.
- Invalid thresholds (out of range/NaN/±inf/bool/non-numeric) now
  raise `ValueError` at engine construction instead of being forwarded
  to bedtools (error) or silently ignored (polars-bio).
- No changes to strand, contains, within, or closest behavior; no new
  user-facing knobs; no UI changes (the slider already maps 0 → `None`).
  The min_overlap post-filter is explicitly gated to `overlap` mode in
  both engines (Task 6A review decision — the non-normative
  contains/within placeholders keep their exact pre-Task-6A behavior),
  pinned by `min_overlap_within_placeholder_not_applied`.

### Review (Task 6A)

Two independent fresh-context Pi subagent reviews (semantics-vs-spec and
implementation/tests) at HEAD: both verdicts **OK with notes**, all
normative points CONFORMS, no P0/P1 semantics findings. Resolved
findings: (1) PLAN.md case count 22 → 25; (2) the post-filter was
initially applied in all modes that route through the shared overlap
path — gated to `overlap` mode only so the contains/within placeholders
are untouched, with a pinning parity case; (3) added a 1/3 precision
pinning case. Accepted as-is (documented, no change): `np.int64` is
rejected as non-numeric (SPEC 8.2 names Python int/float; the UI passes
Python float); the mocked-backend validation test proves rejection at
construction, which satisfies "before backend execution" by definition.
Deferred: stale `use_strand` bullet in `tests/parity/test_extended_semantics.py`
(pre-existing since Task 5; fixed when Task 6B lands), min_overlap ×
`use_strand` cases (6B), min_overlap + left + empty-table cases
(early-return paths, low risk).

### Test command and baseline (Task 6A)

Documented command (from repository root):

```bash
.venv/bin/python -m pytest
```

Task 6A completion baseline: **375 passed, 0 xfailed, 0 failed, 0
skipped** (previous baseline: 282 passed), run twice after the review
fixes. Focused counts: min-overlap contract parity 50 passed (25 cases
× 2 engines), differential parity 16 passed (8 pre-existing + 8
min-overlap), validation 35 passed, full parity suite 178 passed.
Pinned
environment: Python 3.12.14, bedtools 2.31.1, pybedtools 0.12.1,
polars 1.44.2, polars-bio 0.35.1, pandas 3.0.6.

### Remaining known deviations (Task 6 backlog)

`min_overlap` is now normative and parity-protected. Documented gaps
(non-normative, unchanged in Task 6A): `use_strand=True` matching
semantics (flag forwarded to bedtools `-s`; the stranded serialization
exists but the contract is undefined), `contains`/`within` (bedtools
`-f 1.0`/`-F 1.0` placeholders / polars-bio no-op — engine-contract
section 11), `closest` full semantics (distance definition, tie
breaking; the 76-vs-75 discrepancy noted in Task 5 remains).

## Task 6B — strand semantics (2026-09-23)

`use_strand` now has one normative, backend-independent meaning (SPEC
8.3; engine-contract section 10):

- `use_strand=False`: strand does not participate in match
  qualification (pre-Task-6B behavior, unchanged);
- `use_strand=True`: a pair qualifies only if the interval predicate
  qualifies AND both rows carry an explicit canonical strand
  (`+`/`-`) and the strands are equal.

### Decisions

- **Missing/unknown strand is NOT a wildcard.** Canonical missing
  (including a source `.` after normalization) and an entirely absent
  strand column on either input make a stranded match impossible —
  including unknown-vs-unknown. The behavior is identical for both
  engines because the predicate is shared.
- **No native backend strand option.** Bedtools no longer forwards `-s`
  on the overlap path: its treatment of `.`/missing strand is
  undocumented and must not define the AnnotateR contract (bedtools'
  stranded serialization + `-s` were also structurally broken — the
  12-column raw layout parsed the strand column as the annotation row
  id, so any stranded inner match crashed). Pinned polars-bio 0.35.1
  `overlap` exposes no strand option at all. Both engines therefore run
  an ordinary unstranded overlap and apply the shared canonical
  predicate post-hoc — the same architecture as Task 6A `min_overlap`.
  The stranded serialization + native `-s` remain ONLY in the
  non-normative `closest` placeholder, unchanged (Task 6E scope).
- **No mode gating.** The shared strand predicate applies to every mode
  that routes through the engines' overlap path (overlap and the
  non-normative contains/within placeholders), because SPEC 8.3 defines
  strand as orthogonal to the *selected* interval predicate. This
  slightly changes both engines' contains/within placeholder behavior
  (strand now participates identically on both) while those predicates
  remain non-normative — their full contract is Task 6C/6D scope.
  (Contrast Task 6A: `min_overlap` IS gated to overlap mode because
  SPEC 8.2 is defined for the overlap method only.)
- **Logical AND with `min_overlap`.** The predicates are independent:
  strand is applied first, `min_overlap` second; neither bypasses the
  other (no precedence).
- **Left mode.** A query whose geometrical overlaps all fail the strand
  predicate is unmatched exactly once (SPEC 7.2); a query with at least
  one qualifying match emits only its qualifying matches.
- **Validation.** Canonical strand values other than `+`/`-`/missing
  (`?`, `*`, `plus`, `1`, `""`, ...) were already rejected by
  `validate_canonical_interval_table` before Task 6B; Task 6B adds
  engine-level tests proving rejection for both engines BEFORE any
  backend execution. No parser/validation redesign was needed.

### Implementation

- `streamlit_app/core/annotator.py`:
  - new contract-level `strand_keep_mask(df, q_meta, a_meta)`:
    `coord_strand == annot_strand` with both values explicit
    (`+`/`-`); canonical missing (pd.NA/NaN) compares False; an absent
    strand column on either side yields an all-False mask (NOT a
    fall-back to unstranded mode);
  - `BedtoolsEngine._overlap`: ordinary unstranded `intersect` (no
    `s` flag, always the 4-column identity serialization per side) +
    the shared strand post-filter after matching and before left
    reconstruction (`-loj` sentinel rows pass through untouched);
    `_to_bed` gained an explicit `stranded` parameter (only
    `_closest` requests the stranded layout now);
  - `PolarsBioEngine._adapt_overlap_result`: the same shared post-filter
    before the `min_overlap` filter;
  - stale docstrings (Task 6-scope flag forwarding, stranded overlap
    serialization, "engines do not yet implement" strand bullets)
    corrected.
- UI: the checkbox already passed a boolean correctly; only the help
  text was updated to state the normative semantics (missing strand
  never matches in stranded mode).

### Tests

- `tests/parity/cases.py`: `STRAND_CASES` expanded from 1 to 29
  explicit-fixture cases covering the full Task 6B fixture matrix
  (same/opposite/missing/both-missing strands, `.` normalization,
  one-query-two-strands, duplicate queries/annotations, left mismatch /
  left mixed, different chromosome, touching boundaries,
  strand × min_overlap composition (both pass / strand fail /
  threshold fail / left reconstruction), and missing strand column in
  inner and left mode); 15 representative strand fixtures added to
  `DIFFERENTIAL_CASES`.
- `tests/parity/test_extended_semantics.py` →
  `tests/parity/test_strand_parity.py`: per-engine contract layer
  (29 cases × 2 engines) plus
  `test_strand_dot_source_value_not_wildcard` (BED file end-to-end:
  source `.` → canonical missing → not a wildcard under stranded
  matching, both engines).
- `tests/test_strand_validation.py`: malformed canonical strand values
  (`?`, `*`, `plus`, `1`, `""`) raise `InvalidIntervalError` for BOTH
  engines before any backend execution (monkeypatched no-backend
  proof).
- `tests/test_bedtools_engine.py`:
  `test_bedtools_strand_flag_forwarded` replaced by
  `test_bedtools_overlap_does_not_delegate_strand_to_backend` (no
  `s` flag on the overlap path; `closest` still forwards its
  non-normative `-s`).

### Behavior changes

- Bedtools `use_strand=True` (overlap mode): previously delegated to
  native `-s` with a stranded serialization; the missing-strand
  behavior of that path was backend-defined and the layout parsing was
  broken (crash on stranded inner matches). Now: explicit AnnotateR
  contract, both engines identical.
- Polars-Bio `use_strand=True` (overlap mode): previously ignored the
  flag entirely (silently returned unstranded results — a SPEC
  violation). Now enforces the same shared contract.
- `use_strand=False` results are unchanged on both engines.
- Contains/within placeholders: strand now participates identically on
  both engines (documented above); the placeholders remain
  non-normative.
- Closest: unchanged (native `-s` on bedtools, ignored on polars-bio),
  non-normative, Task 6E scope.

### Test command and baseline (Task 6B)

Documented command (from repository root):

```bash
.venv/bin/python -m pytest
```

Task 6B completion baseline: **460 passed, 0 xfailed, 0 failed, 0
skipped** (previous baseline: 375 passed), run twice. Focused counts:
strand contract parity 59 passed (29 cases × 2 engines + 1 `.`
end-to-end), strand validation 13 passed, differential parity 31
passed (16 pre-existing + 15 strand), full parity suite 250 passed.

### Remaining known deviations (Task 6 backlog)

`use_strand` and `min_overlap` are now normative and parity-protected.
Documented gaps (non-normative): `contains`/`within` (bedtools
`-f 1.0`/`-F 1.0` placeholders / polars-bio no-op — engine-contract
section 11), `closest` full semantics (distance definition, tie
breaking; the 76-vs-75 discrepancy noted in Task 5 remains; the
bedtools `-s` forwarding there is a placeholder, not the Task 6B
contract).
