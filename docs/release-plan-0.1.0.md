# v0.1.0 release plan (to run AFTER manual GUI acceptance)

No tag, GitHub Release, or image publication exists yet. The
`release-prep-0.1.0` pass aligned version metadata to `0.1.0` in
preparation, but the formal release happens only after the GUI is
accepted. License normalization is blocked on a maintainer decision (see
`CITATION.cff` notes and `docs/implementation-notes.md`).

Precondition: **the repository license must be settled** (MAINTAINER
DECISION REQUIRED): LICENSE, the README badge/text, and the app footer
must all agree before the release. This is a legal decision outside agent
authority.

1. Apply any final GUI polish from the manual acceptance review (separate,
   small change; re-verify tests).
2. Run the full test suite: `.venv/bin/python -m pytest` (expected baseline
   853 passed, 0 failed, 0 skipped — re-verify at release time).
3. Docker smoke: `docker build --platform linux/amd64 -t annotater . &&
   docker run --rm -p 8501:8501 annotater` and confirm
   `/_stcore/health` plus the manual GUI checks.
4. Align final release metadata:
   - confirm `pyproject.toml` version == `Settings.VERSION` == footer ==
     `0.1.0`;
   - settle the license and make LICENSE / README badge / README text /
     footer / `CITATION.cff` `license` field agree;
   - add `version: 0.1.0` and the release date to `CITATION.cff`
     (still no invented DOI or publication).
5. Tag `v0.1.0` on the release commit.
6. Create the GitHub Release from the tag, including the first-release
   summary (canonical coordinate contract; Bedtools and Polars-Bio
   parity; overlap / left / min_overlap / strand / contains / within /
   closest; Streamlit integration; reproducible Docker deployment;
   benchmark infrastructure).
7. Deploy the approved image (SciLifeLab Serve or other target) with the
   `v0.1.0` tag.
8. Post-deployment smoke test: health endpoint, one real run per engine
   (Bedtools and Polars-Bio), result export.

Follow-up cleanup (not part of the release gate): final disposition of
the legacy R files per `docs/legacy.md` (delete vs. move to `legacy/`).