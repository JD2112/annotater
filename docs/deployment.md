# Deployment

How to build, test, and deploy AnnotateR — locally, in a container, and on
[SciLifeLab Serve](https://serve.scilifelab.se/).

This document is for maintainers. End users who just want to run the app
locally should read [QUICKSTART.md](https://github.com/pyrevo/annotater/blob/main/QUICKSTART.md).

## Contents

- [Prerequisites](#prerequisites)
- [Architecture / platform](#architecture-platform)
- [Building the container image](#building-the-container-image)
- [Published images (GHCR)](#published-images-ghcr)
- [Local container test](#local-container-test)
- [Port and health check](#port-and-health-check)
- [SciLifeLab Serve setup](#scilifelab-serve-setup)
- [Environment / configuration](#environment-configuration)
  (including [upload size](#upload-size) and [data handling](#data-handling))
- [Expected startup and resources](#expected-startup-and-resources)
- [Deployment verification](#deployment-verification)
- [Common failure modes](#common-failure-modes)
- [References](#references)

## Prerequisites

- **Docker** (Docker Desktop on macOS/Windows, or the Docker Engine on
  Linux) with build support. On Apple Silicon hosts the image is built for
  `linux/amd64` (below) and Docker transparently uses QEMU emulation; the
  build is slower but functional.
- For Serve deployment: a Docker Hub account or a GitHub account (for
  GHCR), and a SciLifeLab Serve account.
- No other system dependencies are needed to *build or run* the image:
  bedtools is installed inside the image from the base distribution.

## Architecture / platform

**The image is built for `linux/amd64` only.**

- The pinned Polars-Bio release (`polars-bio==0.35.1`) publishes
  manylinux `x86_64` wheels only — there is no `linux/aarch64` wheel, so
  an arm64-native build cannot resolve the pinned dependencies. This was
  re-verified against PyPI during Task 8 (see
  [references.md](references.md)).
- The `Dockerfile` pins the platform at the `FROM` level
  (`FROM --platform=linux/amd64 python:3.12-slim`), so `docker build`
  produces an amd64 image regardless of the host architecture.
- SciLifeLab Serve's own build guidance likewise uses
  `docker build --platform linux/amd64 ...`.
- If a future Polars-Bio release ships `linux/aarch64` wheels, the
  platform pin can be relaxed — but only after the full contract suite is
  revalidated on the new platform.

## Building the container image

From the repository root:

```bash
docker build --platform linux/amd64 -t annotater:dev .
```

Python dependencies are installed from the committed `uv.lock` (see
[Dependency management](#dependency-management)), so the full resolved
graph — including transitive dependencies — is the one recorded in the
lock, not whatever is newest on PyPI at build time. The remaining inputs
are the base image `python:3.12-slim` (a moving tag; not digest-pinned)
and the distribution bedtools package (Debian bookworm ships bedtools
2.31.1, matching the validated environment). Image layers are not claimed
to be bit-reproducible.

The image contains only what the app needs:

```
/app
├── app.py                        # Serve entry-point shim (see below)
├── pyproject.toml                # dependency declarations (install input only)
├── uv.lock                       # exact locked graph (install input only)
├── streamlit_app/                # application package
├── data/examples/                # bundled example inputs (no user data)
├── benchmarks/benchmark_engines.py
└── scripts/docker_smoke.sh
```

## Dependency management

- `pyproject.toml` declares the direct dependencies (runtime
  `dependencies`, test/lint tools in the `dev` extra).
- `uv.lock` is the exact resolved graph and the single source of truth.
- The `Dockerfile` runs `uv export --frozen --no-dev` on the lock and
  installs the result with `uv pip install --require-hashes --no-deps`:
  no re-resolution, hash-verified, runtime dependencies only. `uv` is
  pinned (`UV_VERSION` build arg) and removed after the install.
- CI runs `uv sync --frozen --extra dev` (same lock, plus dev tools) and a
  `lock-consistency` job running `scripts/export_requirements.sh --check`,
  which fails if `uv.lock` is out of sync with `pyproject.toml` or the
  committed requirements files are stale.
- `requirements.txt` / `requirements-dev.txt` are **generated** from
  `uv.lock` (fully pinned, no hashes) for plain-`pip` users. Do not edit
  them by hand.

To change dependencies intentionally: edit `pyproject.toml`, run
`uv lock` (or `uv lock --upgrade-package <name>` for a single package),
review the `uv.lock` diff, run `scripts/export_requirements.sh`, and
commit all of them together.

`docs/requirements-docs.txt` (MkDocs site build) is a separate,
non-runtime dependency set and is not covered by `uv.lock`.

## Published images (GHCR)

Release images are published to GitHub Container Registry by the
`release-ghcr` GitHub Actions workflow
(`.github/workflows/release-ghcr.yml`). It runs **only on explicit
`workflow_dispatch`** (maintainer action, from `main`) with an explicit
`image_tag` input — it never publishes on every push, and it rejects
`latest`. Each publication is gated by the full in-container smoke
(`scripts/docker_smoke.sh`) before the image is pushed.

Every published image is immutable and is tagged twice with the **same
digest**:

```text
ghcr.io/pyrevo/annotater:0.1.0-rc1     # release-candidate tag (pre-publication testing)
ghcr.io/pyrevo/annotater:sha-<sha>     # per-commit tag of the exact published commit
```

Conventions:

- **RC tags** (`X.Y.Z-rcN`) are for pre-publication testing, e.g. on
  SciLifeLab Serve before the final release.
- **Final semantic-version tags** (e.g. `0.1.0`) are published later, in
  the same workflow, from the approved final release commit.
- **`latest` is never used** as a deployment reference; Serve image
  fields and any pull commands must use an explicit tag (or a digest).
- **Digest pinning** is available where useful: `docker pull
  ghcr.io/pyrevo/annotater@sha256:<digest>` always resolves the exact
  published image (the published digest is recorded in
  [release-plan-0.1.0.md](https://github.com/pyrevo/annotater/blob/main/docs/release-plan-0.1.0.md)).
- **Package visibility:** Serve pulls the image anonymously, so the GHCR
  *package* must be set to **public** under the repository's Package
  settings. Package visibility is independent of the future Serve
  application visibility (which is configured separately in Serve as
  *Project* during the private testing phase).
- All images are `linux/amd64` (platform pin, see
  [Architecture / platform](#architecture-platform)).

The workflow has no default `image_tag`, and it fails before building if
`image_tag` (or the `sha-<sha>` tag) already exists in GHCR, so a published
tag can never be overwritten. A registry error while checking also fails
the run.

Example publication (GitHub → Actions → `release-ghcr` → Run workflow):

```text
branch: main
image_tag: 0.1.0-rc2
```

### Why `app.py`

SciLifeLab Serve requires the main Streamlit script to be named `app.py`
and located in the image working directory. The repository's application
entry point is `streamlit_app/streamlit_app.py`; `app.py` is a thin shim
that imports the real module and calls its `main()`. Local development,
tests, and the container therefore run the identical code.

## Local container test

```bash
# 1. Build
docker build --platform linux/amd64 -t annotater:dev .

# 2. Automated smoke test (imports, bedtools version, both engines,
#    canonical smoke annotation with strict parity, Streamlit health + UI)
#    --entrypoint bash overrides the image ENTRYPOINT (the Streamlit
#    server, required for Serve), otherwise the args are appended to it.
docker run --rm --entrypoint bash annotater:dev /app/scripts/docker_smoke.sh

# 3. Interactive run
docker run --rm -p 8501:8501 annotater:dev
# -> http://localhost:8501
```

The smoke script (`scripts/docker_smoke.sh`, also executed by CI) checks,
in order:

1. `bedtools` is on `PATH` at version 2.31.x;
2. core imports succeed (app package, both engines, canonical adapter);
3. a canonical smoke annotation on the bundled example inputs completes
   with **both** engines (overlap and closest), and the two canonical
   results pass the same strict comparator used by the parity suite;
4. Streamlit starts from the Serve entry point (`app.py`), passes
   `GET /_stcore/health`, and serves the UI (`GET /` → HTTP 200).

A passing `docker build` alone is **not** sufficient verification.

## Port and health check

- Streamlit listens on **8501** (`--server.port=8501`,
  `--server.address=0.0.0.0`). SciLifeLab Serve asks for the port in the
  app settings; Streamlit's 8501 is the expected value.
- The image defines a health check against the Streamlit health endpoint:

  ```
  curl --fail http://localhost:8501/_stcore/health
  ```

  (interval 30 s, timeout 10 s, start period 40 s, 3 retries). Serve
  additionally monitors the container itself; the in-image health check
  is used by Docker and by the smoke test.

## SciLifeLab Serve setup

Verified against the current Serve documentation (see
[References](#references) and [references.md](references.md)). Summary of
the platform requirements this deployment satisfies:

| Requirement | AnnotateR |
|---|---|
| App packaged as a Docker image | yes (above) |
| Main file named `app.py` in the working directory | yes (shim) |
| Streamlit on port 8501 | yes |
| `linux/amd64` image | yes (pinned in `Dockerfile`) |
| Code publicly available, no sensitive data | code is public; uploaded files are processed by the running app, which deletes its temporary parsing copy immediately after parsing and keeps parsed data and results only in memory for the active session (see [Data handling](#data-handling)) |
| Upload size limit (Streamlit apps) | **100 MB per file** documented by the Serve platform ([references.md](references.md)); this is lower than the Streamlit default of 200 MB that applies when running the image elsewhere (see [Upload size](#upload-size)) |

### Step-by-step

1. **Publish the image to a registry.** Serve fetches the image from a
   registry (it never uses your local image). Either:

   - **Docker Hub (manual):**

     ```bash
     docker build --platform linux/amd64 \
       -t <your-dockerhub-username>/annotater:<tag> .
     docker push <your-dockerhub-username>/annotater:<tag>
     ```

   - **GHCR (automated):** the `release-ghcr` workflow publishes from
     GitHub Actions on explicit request (see
     [Published images (GHCR)](#published-images-ghcr)). The package must
     be set to *public* under Package settings, since Serve must be able
     to pull it.

   Rules to keep in mind:
   - **Each version needs a unique tag** (e.g. `annotater:v2`,
     `annotater:20260925`). Once an app has been deployed with a tag, that
     tag is frozen — redeploying requires a new tag.
   - The image **must remain available** after deployment; Serve fetches
     it at regular intervals and the app stops working if it disappears.

2. **Create (or sign in to) a Serve account**, then create a **project**
   (Default project template) on the *My projects* page.

3. **Create the app**: click **Create** on the *Streamlit App* card and
   fill in:

   | Field | Value |
   |---|---|
   | Subdomain | e.g. `annotater` → `annotater.serve.scilifelab.se` |
   | Mount path | `None` (AnnotateR does not use persistent storage) |
   | Hardware | default (2 vCPU / 4 GB RAM); request more via serve@scilifelab.se if motivated by a concrete workload |
   | Port | `8501` |
   | Image | `<registry>/<image>:<tag>`, e.g. `<username>/annotater:v1` |
   | Title / Description / Keywords | per your project |
   | Permissions | `Private` or `Link` while developing; `Public` at release (Serve requires apps to become public eventually) |
   | Creators | per your project records |
   | Source code URL | `https://github.com/pyrevo/annotater` |

4. **Update**: publish a new image tag, then in the app *Settings* change
   the Image tag and press *Update*.

No secrets or credentials are used by AnnotateR at runtime; there is
nothing to configure in Serve's environment-variable settings beyond the
defaults in [Environment / configuration](#environment-configuration).

## Environment / configuration

The application uses exactly one AnnotateR-specific environment
variable, `TEMP_DIR`. The Docker image additionally sets four
`STREAMLIT_*` variables, and the Streamlit runtime reads
`STREAMLIT_SERVER_MAX_UPLOAD_SIZE` if it is set. All are optional.

| Variable | Default | Effect |
|---|---|---|
| `TEMP_DIR` | `/tmp/annotator` | Directory for the temporary copy of each upload that is written for parsing (created if missing; the image creates it with world-writable permissions). The copy is deleted immediately after parsing, on success or failure. |
| `STREAMLIT_SERVER_MAX_UPLOAD_SIZE` | unset (Streamlit default **200**) | Maximum size of one uploaded file, in MB. Not set by the image or by the application, so the Streamlit default of 200 MB applies; see [Upload size](#upload-size). |
| `STREAMLIT_SERVER_HEADLESS` | `true` (image) | No browser auto-open in the container. |
| `STREAMLIT_SERVER_FILE_WATCHER_TYPE` | `poll` (image) | Avoids inotify limits on volumes. |
| `STREAMLIT_SERVER_ENABLE_CORS` | `false` (image) | Disables CORS. |
| `STREAMLIT_BROWSER_GATHER_USAGE_STATS` | `false` (image) | No usage stats. |

Other settings-style names that appear in
`streamlit_app/config/settings.py` or in `docker-compose.yml` (for
example size, chunking, worker, caching, cleanup and logging settings)
are not read by any application code path, so setting them has no
effect and they are not supported configuration.

### Upload size

The effective per-file upload limit is Streamlit's
`server.maxUploadSize`, which defaults to **200 MB** in the pinned
Streamlit release (1.64.0) and which neither the image nor the
application overrides. An operator running the image can change it with
`STREAMLIT_SERVER_MAX_UPLOAD_SIZE` (in MB). AnnotateR enforces no
separate size limit of its own. On SciLifeLab Serve, the platform
documents a limit of **100 MB** for Streamlit apps, which applies there.

### Data handling

- Uploaded files are processed by the running AnnotateR server.
- A temporary copy is written under `TEMP_DIR` for parsing and deleted
  immediately afterwards, whether parsing succeeds or fails.
- Parsed data and results remain only in application memory for the
  active session; AnnotateR does not intentionally persist uploaded files
  or results after that lifecycle.
- Local Docker execution processes uploads in the AnnotateR container
  running on the user's own machine; SciLifeLab Serve is not involved.
- Infrastructure-level behavior of a hosting platform (logs, caches,
  proxies, node storage) is outside what AnnotateR controls and is not
  described here.

The repository's `docker-compose.yml` is a development convenience
(it bind-mounts the source tree and `/tmp/annotator`); the bind mount is
not required for, or part of, the supported container behavior.

### Developer toolbar controls

The Streamlit toolbar in the top-right corner (Rerun, Deploy, Clear
cache, developer menu) is controlled with the officially supported
`client.toolbarMode` configuration. The app pins it explicitly in
`streamlit_app/streamlit_app.py` via
`st.set_option("client.toolbarMode", "auto")`. With `auto` (the default
in Streamlit 1.64.0) the developer options are shown only when the app is
accessed through localhost, i.e. by a developer running it locally; a
deployed (Serve) audience connecting from outside localhost gets the clean
viewer toolbar. No CSS/DOM-based hiding is used, and local development
ergonomics (including the local Rerun control) are unchanged.

## Expected startup and resources

- Cold start (interpreter + imports + Streamlit) takes roughly 10–20 s
  locally; Serve may need a couple of minutes after *Running* before the
  app answers (stated by Serve).
- Default allocation (2 vCPU / 4 GB RAM) is sufficient for interactive
  use with files below the 100 MB platform upload cap; the in-container
  smoke test passes within these limits. Very large inputs (hundreds of
  MB) need headroom for canonical frames held in memory — see
  [Limitations](limitations.md).
- The filesystem is ephemeral except for the project *Mount path* (not
  used). Each upload is written to a temporary file under `TEMP_DIR` for
  parsing and deleted immediately afterwards; parsed data is held in
  memory. Intermediate bedtools files are written by pybedtools to its
  default temporary directory (`TMPDIR` / the system temp directory),
  not to `TEMP_DIR`.

## Deployment verification

After (re)deploying:

1. Open the app URL (or `http://localhost:8501` for a local container).
2. Run the built-in check: upload `data/examples/example_coordinates.bed`
   as coordinates and `data/examples/example_annotations.gff3` as
   annotations, run **overlap**, then rerun with the other engine — both
   must return identical canonical results (the UI states the backends
   are interchangeable).
3. Confirm the deployed image version separately from the application
   version: the footer shows the application version (`0.1.0`, which is
   unchanged between `0.1.0-rc1` and the final release), so it cannot
   identify an RC tag. Check the image's OCI label instead, e.g.
   `docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.version" }}' ghcr.io/pyrevo/annotater:<tag>`,
   which the `release-ghcr` workflow sets to the published tag.
4. For Serve: confirm the container status is *Running* and the health
   check in the app overview is green.

## Common failure modes

| Symptom | Likely cause / fix |
|---|---|
| `docker build` fails in `pip install` on an Apple Silicon host | Building arm64-native. Build with `--platform linux/amd64` (the `Dockerfile` already pins amd64; use Docker Desktop with the x86 emulation enabled). |
| Serve keeps serving an old version | Reused an image tag. Publish a **new unique tag** and update the Image field. |
| Serve app never becomes available | Image tag not pulled (private GHCR package, image deleted, or typo in the Image field). The image must stay publicly available at all times. |
| Uploads above ~100 MB are rejected on Serve | Platform upload limit (Streamlit apps). When running the image yourself, the limit is Streamlit's 200 MB default; change it with `STREAMLIT_SERVER_MAX_UPLOAD_SIZE` (see [Upload size](#upload-size)). |
| bedtools engine errors only in the container | `bedtools` not on `PATH` inside the image — run `scripts/docker_smoke.sh`; it asserts version 2.31.x. |
| App is slow on Serve | Default 2 vCPU/4 GB allocation. Request more resources via serve@scilifelab.se with a concrete workload example. |
| Positions ≥ 2³¹ error from the Bedtools engine | pybedtools packs coordinates into a 32-bit field (see [benchmark docs](benchmark.md) / Limitations). Not reachable with natural chromosomes. |

## References

Current official documentation (retrieved 2026-09-25; exact links are
kept in [references.md](references.md)):

- SciLifeLab Serve — Streamlit app hosting guide (step-by-step, resource
  defaults, upload limit, image/tag rules)
- SciLifeLab Serve — application hosting overview (port range, public
  code/data, no databases)
- Docker build reference (`--platform`)
- PyPI — `polars-bio` (wheel availability per platform)