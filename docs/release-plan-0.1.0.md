# v0.1.0 release plan (to run AFTER manual GUI acceptance)

No tag, GitHub Release, or image publication exists yet. The
`release-prep-0.1.0` pass aligned version metadata to `0.1.0` in
preparation, but the formal release happens only after the GUI is
accepted.

**License: RESOLVED (2026-09-28).** The maintainers selected
BSD-3-Clause as the canonical license for the current AnnotateR
project/release after reviewing the provenance audit (see
`docs/implementation-notes.md`); LICENSE, README badge/text, app footer,
`pyproject.toml`, and `CITATION.cff` now all agree on BSD-3-Clause.
This former release gate is closed.

Remaining release gate (in order):

1. Manual GUI acceptance.
2. Apply any final approved GUI polish from the acceptance review
   (separate, small change; re-verify tests).
3. Run the full test suite: `.venv/bin/python -m pytest` (expected
   baseline 853 passed, 0 failed, 0 skipped — re-verify at release time).
4. Docker smoke: `docker build --platform linux/amd64 -t annotater . &&
   docker run --rm -p 8501:8501 annotater` and confirm `/_stcore/health`
   plus the manual GUI checks.
5. Align final release metadata:
   - confirm `pyproject.toml` version == `Settings.VERSION` == footer ==
     `0.1.0`; confirm all license declarations remain BSD-3-Clause;
   - add `version: 0.1.0` and the release date to `CITATION.cff`
     (still no invented DOI or publication).
6. Tag `v0.1.0` on the release commit.
7. Create the GitHub Release from the tag, including the first-release
   summary (canonical coordinate contract; Bedtools and Polars-Bio
   parity; overlap / left / min_overlap / strand / contains / within /
   closest; Streamlit integration; reproducible Docker deployment;
   benchmark infrastructure).
8. Deploy the approved image (SciLifeLab Serve or other target) with the
   `v0.1.0` tag.
9. Post-deployment smoke test: health endpoint, one real run per engine
   (Bedtools and Polars-Bio), result export.

Follow-up cleanup (not part of the release gate): final disposition of
the legacy R files per `docs/legacy.md` (delete vs. move to `legacy/`).