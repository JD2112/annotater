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
5a. **Release-candidate image (this step is separate from the final
    release above):** publish `ghcr.io/pyrevo/annotater:0.1.0-rc1` (plus
    the per-commit `sha-<sha>` tag, same digest) from the verified `main`
    commit via the `release-ghcr` workflow (explicit `workflow_dispatch`,
    `image_tag: 0.1.0-rc1`; see
    [deployment.md — Published images (GHCR)](deployment.md#published-images-ghcr)).
    Set the GHCR *package* to public so Serve can pull it, then let the
    maintainer test the RC on SciLifeLab Serve (private Project
    visibility) before the final release gate below. RC1 publication
    record: see [Release-candidate publications](#release-candidate-publications).
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

## Release-candidate publications

Immutable GHCR images published before the final `v0.1.0` release
(process: [deployment.md — Published images (GHCR)](deployment.md#published-images-ghcr)).

| RC | Source commit | Image tags (same digest) | Digest | Published |
|---|---|---|---|---|
| 0.1.0-rc1 | `7269b47cdade3511cd317634c304ebadf3d10345` (main) | `ghcr.io/pyrevo/annotater:0.1.0-rc1`, `ghcr.io/pyrevo/annotater:sha-7269b47` | `sha256:76b5574bb506abfa2d9a0fdeea51f0d5bca941e155d8e26e62cb1fcd73f10d91` (both tags, verified from the GHCR push receipts) | 2026-09-29 (release-ghcr workflow run #1: [actions/runs/36564727227](https://github.com/pyrevo/annotater/actions/runs/36564727227), platform `linux/amd64`) |

Package visibility note (2026-09-29): the `annotater` container package was
created by the workflow as **private** (default for a private repository)
and the automated token could not change it (no `packages` scope). The
maintainer must set it to **public** under the repository's Package
settings (or make the repository public) before Serve can pull it
anonymously — the agent token of this session only has
`gist, read:org, repo, workflow`.

Final-release images (`0.1.0`) are published only after step 5/6/7 above
have been approved.

Follow-up cleanup (not part of the release gate): final disposition of
the legacy R files per `docs/legacy.md` (delete vs. move to `legacy/`).
**Resolved:** the legacy files were deleted from the repository in
preparation for publication; see `docs/legacy.md`.