# Deployment

How to build, test, and deploy AnnotateR — locally, in a container, and on
[SciLifeLab Serve](https://serve.scilifelab.se/).

This document is for maintainers. End users who just want to run the app
locally should read [QUICKSTART.md](https://github.com/pyrevo/annotater/blob/main/QUICKSTART.md).

## Contents

- [Prerequisites](#prerequisites)
- [Architecture status](#architecture-status)
- [Architecture / platform](#architecture-platform)
- [Building the container image](#building-the-container-image)
- [Published images (GHCR)](#published-images-ghcr)
- [Local container test](#local-container-test)
- [Port and health check](#port-and-health-check)
- [SciLifeLab Serve setup](#scilifelab-serve-setup)
- [Environment / configuration](#environment-configuration)
  (including [upload size](#upload-size), [parsing concurrency](#parsing-concurrency)
  and [data handling](#data-handling))
- [Single-worker requirement](#single-worker-requirement)
- [Expected startup and resources](#expected-startup-and-resources)
- [Deployment verification](#deployment-verification)
- [Common failure modes](#common-failure-modes)
- [References](#references)

## Prerequisites

- **Docker** (Docker Desktop on macOS/Windows, or the Docker Engine on
  Linux) with build support. On Apple Silicon hosts the image is built for
  `linux/amd64` (below) and runs under x86 emulation: Docker Desktop uses
  Rosetta when that option is enabled (the default in recent releases) and
  QEMU otherwise. The build is slower but functional.
- For Serve deployment: a Docker Hub account or a GitHub account (for
  GHCR), and a SciLifeLab Serve account.
- No other system dependencies are needed to *build or run* the image:
  bedtools is installed inside the image from the base distribution.

## Architecture status

AnnotateR's container has two generations, and this document covers both:

| | **Streamlit image** — published | **React/FastAPI image** — planned RC4 |
|---|---|---|
| Web layer | Streamlit, script `app.py` | React SPA (`frontend/dist`) + FastAPI (`streamlit_app/api_server.py`) |
| Entry point | Streamlit server, port **8501** | `start-script.sh` → Uvicorn, port **8000** |
| Health path | `GET /_stcore/health` | `GET /health` |
| State | Streamlit session state | in-memory API session store (single worker; see [Single-worker requirement](#single-worker-requirement)) |
| Published tags | `0.1.0-rc3` (and `0.1.0-rc2`, running on the public beta) | **none yet**; `0.1.0-rc4` is planned, not published |

The **Streamlit** generation is what the published GHCR images and the current
public beta deployment run, and the sections below that describe it remain the
reference for those images. The **React/FastAPI** generation is what the
`Dockerfile` on this branch builds and what the planned `0.1.0-rc4` image will
contain. It is **not yet published to GHCR and not yet deployed to SciLifeLab
Serve**: its deployment steps below are the documented plan, not a completed
publication. Do not read this document as a claim that the React/FastAPI image
is live anywhere.

## Architecture / platform

**The image is built for `linux/amd64` only.**

- The pinned Polars-Bio release (`polars-bio==0.35.1`) publishes
  manylinux `x86_64` wheels only — there is no `linux/aarch64` wheel, so
  an arm64-native build cannot resolve the pinned dependencies. This was
  re-verified against PyPI during Task 8 (see
  [references.md](references.md)).
- The `Dockerfile` pins the platform at the `FROM` level
  (`ARG PLATFORM=linux/amd64` + `FROM --platform=${PLATFORM}
  python:3.12-slim`), so `docker build` produces an amd64 image regardless
  of the host architecture. The build is multi-stage: a Node 22 stage
  builds the React frontend, and only the built assets (`frontend/dist`)
  are copied into the runtime image.
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
lock, not whatever is newest on PyPI at build time. The build is
multi-stage: a `node:22-slim` stage runs `npm ci` and `npm run build`
(so the build host needs access to the npm registry), and the runtime
image then installs only the pinned Python dependencies. The remaining
inputs are the base image `python:3.12-slim` (a moving tag; not
digest-pinned) and the distribution bedtools package (Debian bookworm
ships bedtools 2.31.1, matching the validated environment). Image layers
are not claimed to be bit-reproducible.

The image contains only what the app needs:

```
/app
├── app.py                        # legacy Serve entry-point shim (Streamlit generation)
├── start-script.sh               # ENTRYPOINT: single-worker Uvicorn on port 8000
├── pyproject.toml                # dependency declarations (install input only)
├── uv.lock                       # exact locked graph (install input only)
├── streamlit_app/                # application package (api_server.py is the FastAPI app)
├── frontend/dist/                # built React assets, served by FastAPI at /
├── data/examples/                # bundled example inputs (no user data)
├── benchmarks/benchmark_engines.py
└── scripts/
    ├── docker_smoke.sh           # scientific-core smoke
    ├── docker_smoke_api.sh       # served FastAPI/React smoke
    └── offline_smoke.py          # network-disabled scientific smoke
```

The runtime image is non-root: the container runs as `appuser` (UID 1000,
the SciLifeLab Serve standard).

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
`latest`. Each publication is gated before the push by the same in-container
smokes CI runs: the scientific core (`scripts/docker_smoke.sh`), the served
FastAPI/React application (`scripts/docker_smoke_api.sh`), and the
network-disabled scientific runtime (`scripts/offline_smoke.py`).

The published tags so far (`0.1.0-rc1`…`0.1.0-rc3`) are **Streamlit**
images. The React/FastAPI image built from this branch is planned for
`0.1.0-rc4`; that image has **not** been published, tagged, released, or
deployed. Keep using the explicit published RC tag for any current local or
Serve deployment.

Every published image is immutable and is tagged twice with the **same
digest**:

```text
ghcr.io/pyrevo/annotater:0.1.0-rc3     # release-candidate tag (pre-publication testing; latest published RC)
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
image_tag: 0.1.0-rc3
```

### Why `app.py` is still present

The **published Streamlit generation** must name its main file `app.py` in the
image working directory (a SciLifeLab Serve requirement for its Streamlit app
type). The repository's application entry point is
`streamlit_app/streamlit_app.py`; `app.py` is a thin shim that imports the real
module and calls its `main()`. It is retained so the published images stay
runnable and reproducible.

The **React/FastAPI generation** does not go through Streamlit. Its image
`ENTRYPOINT` is `start-script.sh`, which launches Uvicorn serving
`streamlit_app.api_server:app`; the React app is served as static assets by
that same FastAPI process at `/`.

## Local container test

```bash
# 1. Build
docker build --platform linux/amd64 -t annotater:dev .

# 2. Scientific-core smoke (bedtools, both engines, canonical parity)
#    --entrypoint bash overrides the image ENTRYPOINT (start-script.sh),
#    otherwise the args are appended to it and the web server starts.
docker run --rm --entrypoint bash annotater:dev /app/scripts/docker_smoke.sh

# 3. Served-application smoke (startup, /health, routes, sessions, export)
docker run --rm --entrypoint bash annotater:dev /app/scripts/docker_smoke_api.sh

# 4. Offline scientific-runtime smoke (network hard-blocked)
docker run --rm --network none --entrypoint python \
  annotater:dev /app/scripts/offline_smoke.py

# 5. Interactive run
docker run --rm -p 8000:8000 annotater:dev
# -> http://localhost:8000   (health: http://localhost:8000/health)
```

The three smoke scripts are also executed by CI (`.github/workflows/
python-tests.yml`, job `docker-smoke`). What each covers:

- **`scripts/docker_smoke.sh`** — scientific core, server-agnostic:
  1. `bedtools` is on `PATH` at version 2.31.x;
  2. core imports succeed (app package, both engines, canonical adapter);
  3. a canonical smoke annotation on the bundled example inputs completes
     with **both** engines (overlap and closest), and the two canonical
     results pass the same strict comparator used by the parity suite;
  4. hand-computed scientific assertions on tiny inline fixtures pass on
     both engines.
- **`scripts/docker_smoke_api.sh`** — the served application, exactly as the
  container runs it (starts `start-script.sh`): non-root UID 1000, healthy
  startup, `GET /health` (and that it fails while the process is down), the
  React assets served at `/`, `/api/meta`, two independent sessions with
  isolated results, upload cleanup, Bedtools and Polars-Bio execution,
  bundled chromosome normalization, custom mapping, VCF export, and that a
  restart resets session state (no leak).
- **`scripts/offline_smoke.py`** — the scientific runtime with the network
  off (`--network none`, plus a socket-level block): the bundled chromosome
  catalog and a custom mapping load, both engines annotate with strict
  canonical parity, and VCF export works — with no external chromosome data.

The served-application and offline smokes can also be run from pytest,
gated on a built image:

```bash
docker build --platform linux/amd64 -t annotater:ci .
ANNOTATER_TEST_IMAGE=annotater:ci pytest tests/test_container_image.py
```

A passing `docker build` alone is **not** sufficient verification.

### Real-browser regression tests (Playwright)

`tests/test_browser_multi_tab.py` drives a real browser through Playwright
against the actual FastAPI app serving the built React frontend. It covers
the two-tab revision contract that HTTP-only tests cannot see:

1. a stale tab cannot export another tab's result;
2. a stale tab cannot run on another tab's datasets;
3. re-uploading restores a consistent tab;
4. an upload `409` clears the stale file card and disables Run;
5. a revision-safe clean-up cannot wipe another tab's newer dataset;
6. sample coordinate provenance does not leak into the next upload's
   coordinate declaration.

Run it locally (system Google Chrome by default):

```bash
(cd frontend && npm install && npm run build)
ANNOTATER_BROWSER_TESTS=1 \
  uv run --with playwright==1.64.0 --extra dev pytest tests/test_browser_multi_tab.py
```

`--extra dev` is required: `uv run` otherwise selects only the project's
runtime dependencies, so `pytest` may be absent even when the browser suite's
pytest command is correct.

Or use Playwright's managed Chromium (the CI choice) and install it once:

```bash
ANNOTATER_BROWSER_TESTS=1 ANNOTATER_BROWSER_CHANNEL=bundled \
  uv run --with playwright==1.64.0 playwright install chromium
ANNOTATER_BROWSER_TESTS=1 ANNOTATER_BROWSER_CHANNEL=bundled \
  uv run --with playwright==1.64.0 --extra dev pytest tests/test_browser_multi_tab.py
```

The test fixture starts and stops its own Uvicorn process on a free local
port; each scenario gets an isolated browser context (separate cookie jar).
Set `ANNOTATER_BROWSER_LOG_DIR` to capture server and browser console logs,
and `ANNOTATER_BROWSER_TRACE_DIR` to write one Playwright trace per context.
`ANNOTATER_BROWSER_REQUIRED=1` makes missing prerequisites fail instead of
skip (CI uses it).

The `browser-regression` CI job in `.github/workflows/python-tests.yml` runs
this suite on every pull request. Like the other PR jobs it uses GitHub's
default checkout, so it tests the synthetic merge commit that would land
rather than the loose PR head. The job logs both the PR head SHA and the
checked-out commit SHA, builds the frontend from that checkout, installs the
pinned Playwright Chromium, and uploads logs and traces as the
`browser-regression-diagnostics` artifact when it fails or is cancelled.

The job is fail-closed: `ANNOTATER_BROWSER_REQUIRED=1` makes a disabled suite
(missing `ANNOTATER_BROWSER_TESTS=1`), a dropped/renamed/deselected browser
test, a skipped, xfailed or non-passing browser test, a collection-only or
setup-only run, or a missing browser/frontend build/bedtools/server fail the
job. The exact expected node IDs live in `tests/browser_test_inventory.py`;
add a legitimate regression there in the same change.

The workflow contract accepts one explicit invocation:

```
uv run --with playwright==1.64.0 pytest tests/test_browser_multi_tab.py
```

followed only by `-v`, `-q`, or `--durations=N`. Shell wrappers, conditional
steps, `continue-on-error`, working-directory changes, and other pytest
options (including `-k`, `--deselect`, `--noconftest`, `-p`, and
`--collect-only`) are rejected. Diagnostics must be uploaded after the browser
test step. Workflow inspection uses the PyYAML dev dependency; local runs
without `ANNOTATER_BROWSER_REQUIRED` keep the opt-in skip behavior.

### Required check configuration

The GitHub Actions check name for this job is:

```
real-browser regression (two-tab revisions)
```

As of 2026-10-19, `pyrevo/annotater` has no classic branch protection on
`main` and no repository rulesets, so this check is not yet required. Changing
repository settings is outside this task; after merge, an administrator
should enable a `main` ruleset (or classic protection) that:

- requires this exact check, alongside the existing pytest, lock, frontend
  and Docker checks, before merging;
- requires a pull request and at least one approval;
- dismisses stale approvals and requires conversation resolution;
- requires branches to be up to date before merging.

This job does not change the existing pytest, frontend-lint or Docker jobs.

## Port and health check

- The **React/FastAPI** image listens on **8000**. `start-script.sh` runs
  `uvicorn streamlit_app.api_server:app --host 0.0.0.0 --port "${PORT}"`
  (`PORT` defaults to 8000). SciLifeLab Serve asks for the port in the app
  settings; 8000 is the expected value for this image.
- The image defines a health check against the FastAPI health route:

  ```
  curl --fail http://localhost:8000/health
  ```

  (`GET /health` returns `{"status": "ok", "version": "0.1.0"}`.) The
  Dockerfile `HEALTHCHECK` uses interval 30 s, timeout 10 s, start period
  30 s, 3 retries; `docker-compose.yml` matches. Serve's own deployment
  status is separate; the in-image health check is used by Docker and by
  the smoke tests.
- For reference, the **published Streamlit** images listen on **8501** and
  are healthy at `curl --fail http://localhost:8501/_stcore/health`.

## SciLifeLab Serve setup

This section separates what the repository verifies from what Serve
documents and what can only be confirmed in the Serve UI. The Serve pages
were re-checked on **2026-10-22**; their stated version date is
**2026-09-23** (docs v5.3.0-beta). Links are in
[references.md](references.md).

**Verified in this repository**

| Fact | Evidence |
|---|---|
| Image is `linux/amd64` | `Dockerfile` pins `PLATFORM=linux/amd64` |
| Container runs as non-root UID 1000 | `Dockerfile` creates `appuser` with UID 1000 and ends with `USER appuser` |
| Startup script is in the image working directory | `Dockerfile` sets `WORKDIR /app`, copies `start-script.sh` to `/app/start-script.sh`, makes it executable, and uses `ENTRYPOINT ["./start-script.sh"]` |
| Web service listens on 8000 with `GET /health` | `start-script.sh` and the FastAPI health route; the Dockerfile health check uses the same endpoint |
| FastAPI runs one Uvicorn worker | `start-script.sh` deliberately omits `--workers` |
| No mount path or database is required | AnnotateR keeps session state in process memory and writes only temporary parsing files |

**Documented by Serve**

- Other/custom apps are Docker images and must use a startup script placed
  in the container working directory; Streamlit apps additionally require
  `app.py` in the working directory.
- Images must run as non-root UID 1000 and listen on a port in
  **3000–9999**. Streamlit apps use 8501; the React/FastAPI image uses 8000.
- Each deployed version needs a unique tag, and the image must remain
  publicly available.
- Code and data must be public, sensitive data is not supported, and apps
  must eventually become public.
- Default resources are 2 vCPU / 4 GB RAM.
- Serve documents a **100 MB upload limit** for Streamlit apps and a
  **100 MB upload limit** for other/custom apps. The documentation does
  **not** establish whether either limit is per file, per request, or
  another scope.

**Deployment-time assumptions to confirm in Serve**

- The Other/Custom app form accepts the exact GHCR reference and exposes
  the environment variables used below.
- The proxy forwards `X-Forwarded-Proto`, and `FORWARDED_ALLOW_IPS` can be
  set to the actual proxy addresses or safely left at `*` only when the
  container is reachable solely through Serve.
- One replica is sufficient for the in-memory session store, and Serve
  does not route one browser session across replicas without affinity.
- The rejection response for an upload above Serve's platform limit,
  including whether the request reaches AnnotateR at all. Confirm this in
  the Serve UI and with a test upload after deployment.

`MAX_FILE_SIZE_MB=100` is therefore a **recommended validation setting**,
not a verified Serve requirement. It lets AnnotateR enforce its own
per-file limit while streaming the upload to private temporary storage,
before parsing its contents, but a platform or proxy may reject an upload
before the request reaches the application. Such a rejection is not
guaranteed to display AnnotateR's own error message.

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

3. **Create the Streamlit app** (for the published RC1–RC3 generation):
   click **Create** on the *Streamlit App* card and fill in:

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

#### Deploying the React/FastAPI image (planned RC4)

The steps above use Serve's *Streamlit App* type, which is what the published
`0.1.0-rc1`–`0.1.0-rc3` images use. The planned RC4 React/FastAPI image is a
plain Docker web service (`start-script.sh` → Uvicorn), so it should be
created as a **separate Other/Custom app**, not by changing the existing
Streamlit beta app. The existing beta remains on RC2 until an RC4 deployment
has been validated.

Deployment settings for the planned image:

- **App type:** Other/Custom app (Docker image), not Streamlit.
- **Port:** `8000` (the Streamlit type's `8501` does not apply).
- **Health:** `GET /health` (not `/_stcore/health`).
- **Startup script:** Serve requires the script in the image working
  directory. The image satisfies this: `WORKDIR` is `/app`, the executable
  `start-script.sh` is copied to `/app/start-script.sh`, and it is the
  `ENTRYPOINT`. No `app.py` is needed for this app type.
- **Image:** public GHCR image with an explicit, immutable tag; the image
  runs as UID 1000 and is `linux/amd64`.
- **Upload limit:** Serve documents a **100 MB upload limit** for
  other/custom apps but does not establish whether it is per file or per
  request. The image defaults to `MAX_FILE_SIZE_MB=500`; setting
  `MAX_FILE_SIZE_MB=100` is a **recommended validation setting**, not a
  verified Serve requirement. It applies AnnotateR's own per-file limit
  before the upload is parsed. A platform or proxy rejection may happen
  before the request reaches AnnotateR and is not guaranteed to show
  AnnotateR's upload error.
- **Single worker / replicas:** the image already runs exactly one Uvicorn
  worker. Keep one replica; do not scale horizontally unless Serve provides
  verified session affinity for the in-memory session store (see
  [Single-worker requirement](#single-worker-requirement)).
- **Proxy and cookie:** keep `FORWARDED_ALLOW_IPS` at `*` only if the
  container is reachable solely through Serve's trusted TLS-terminating
  proxy. Confirm that the proxy forwards `X-Forwarded-Proto`; over HTTPS the
  app then issues the `Secure`, `HttpOnly`, `SameSite=Lax` `__Host-` session
  cookie. If the proxy topology differs, set `FORWARDED_ALLOW_IPS` to the
  proxy addresses instead.
- **No mount path / no database:** AnnotateR uses neither.
- **Visibility:** Project/Link during testing; Public at release (Serve
  requires apps to become public eventually).

After deployment, verify `GET /health`, an upload/run/export with both
engines, the application-level upload limit, the HTTPS session cookie, and
what Serve itself returns for an upload above its platform limit. That
platform response may come from Serve rather than AnnotateR. This
deployment has **not been performed**: no RC4 image is published and no RC4
Serve app exists. Confirm the exact Serve app type, platform limit scope,
and proxy/replica behavior against the current Serve documentation and the
authenticated Serve UI at deployment time (see [References](#references)).

No secrets or credentials are used by AnnotateR at runtime.
`MAX_FILE_SIZE_MB=100` is the only deployment-specific value recommended
as a validation setting; the other variables have safe defaults in
[Environment / configuration](#environment-configuration).

## Environment / configuration

All environment variables are optional. The React/FastAPI image's
entrypoint (`start-script.sh`) reads `PORT` and `FORWARDED_ALLOW_IPS`; the
API reads `MAX_FILE_SIZE_MB`, `ANNOTATER_CORS_ORIGINS` and
`ANNOTATER_MAX_CONCURRENT_PARSES`. The published
Streamlit generation instead sets four `STREAMLIT_*` variables, reads
`STREAMLIT_SERVER_MAX_UPLOAD_SIZE` if it is set, and uses `TEMP_DIR`
through its file helpers.

**React/FastAPI image (this branch):**

| Variable | Default | Effect |
|---|---|---|
| `PORT` | `8000` | Port Uvicorn binds in `start-script.sh`. |
| `FORWARDED_ALLOW_IPS` | `*` | Trusted proxy address(es) for `--forwarded-allow-ips`, so the TLS-terminating proxy's `X-Forwarded-Proto` is honoured and the session cookie is issued `Secure` over HTTPS. Override if the deployment topology differs. |
| `MAX_FILE_SIZE_MB` | `500` | Per-file upload limit enforced by the API (`/api/upload`); see [Upload size](#upload-size). |
| `ANNOTATER_MAX_CONCURRENT_PARSES` | `2` | Maximum number of uploads parsed concurrently. A positive integer is used as given; `0` and negative values are clamped to `1`; a non-integer aborts startup. Raising it increases peak memory — see [Parsing concurrency](#parsing-concurrency). |
| `ANNOTATER_CORS_ORIGINS` | unset (no cross-origin access) | Comma-separated origin allowlist for credentialed cross-origin API calls, e.g. `https://app.example.org,https://tools.example.org`. The default deployment (React app served from the same host) is same-origin and needs no configuration. A bare `*` entry is rejected at startup: with `allow_credentials=True` it would reflect every request origin. |

The React/FastAPI upload path writes its temporary parsing copy under the
**system** temporary directory (`tempfile.mkdtemp`) and deletes it
immediately after parsing, on success or failure; it does not read
`TEMP_DIR`. `TEMP_DIR` (default `/tmp/annotator`; the image creates it with
world-writable permissions) and `CLEANUP_AFTER_HOURS` (age after which
`cleanup_temp_files` would remove stale files) apply only to the
Streamlit-generation helpers (`save_uploaded_file`, `cleanup_temp_files`),
which the React/FastAPI image does not call.

**Published Streamlit generation (reference):**

| Variable | Default | Effect |
|---|---|---|
| `STREAMLIT_SERVER_MAX_UPLOAD_SIZE` | unset (Streamlit default **200**) | Maximum size of one uploaded file, in MB (see [Upload size](#upload-size)). |
| `STREAMLIT_SERVER_HEADLESS` | `true` (image) | No browser auto-open in the container. |
| `STREAMLIT_SERVER_FILE_WATCHER_TYPE` | `poll` (image) | Avoids inotify limits on volumes. |
| `STREAMLIT_SERVER_ENABLE_CORS` | `false` (image) | Disables CORS. |
| `STREAMLIT_BROWSER_GATHER_USAGE_STATS` | `false` (image) | No usage stats. |

Other settings-style names that appear in
`streamlit_app/config/settings.py` or in `docker-compose.yml` (for example
chunking (`CHUNK_SIZE`), worker-count (`MAX_WORKERS`), caching
(`ENABLE_CACHING`) and logging (`LOG_LEVEL`) settings) are not read by any
application code path, so setting them has no effect and they are not
supported configuration.

### Parsing concurrency

`POST /api/upload` parses on a worker thread so the event loop stays
responsive, but it borrows from a limiter dedicated to parsing rather than
AnyIO's shared default thread pool. Starlette runs synchronous endpoints such
as `GET /health`, `/api/meta`, sample load and clear on that shared default
pool, so a burst of uploads cannot occupy all its tokens and starve them.
Uploads waiting for a parse slot wait on the event loop without blocking it.
The limit applies to uploads only; sample loading parses on the default pool.

`ANNOTATER_MAX_CONCURRENT_PARSES` is read at import by
`streamlit_app/config/settings.py`. It accepts a base-10 integer: the default
is `2`, `0` and negative values are clamped to `1`, positive values are used as
given (there is no upper clamp), and a non-integer value raises `ValueError`
during settings import, so the process aborts at startup rather than silently
falling back.

Parsing is memory-heavy: a canonical frame can be several times the size of
the uploaded file, so concurrent parses multiply peak RSS. At the default of
`2`, an internal measurement of four concurrent ~111 MB uploads peaked at
about **2.6 GB RSS**, within the default 2 vCPU / 4 GB Serve allocation
([Expected startup and resources](#expected-startup-and-resources)). Raise the
limit only together with more memory; it cannot create CPU throughput beyond
the available cores.

### Upload size

**React/FastAPI image:** the API enforces its own per-file limit,
`MAX_FILE_SIZE_MB` (default **500 MB**): an upload over the limit is rejected
by `/api/upload` with an explicit error rather than being silently truncated.
Change it by setting `MAX_FILE_SIZE_MB`. On SciLifeLab Serve, setting
`MAX_FILE_SIZE_MB=100` is a **recommended validation setting**, not a
verified Serve requirement. Serve documents a **100 MB upload limit** for
other/custom apps but does not say whether that limit is per file or per
request. The application-level check covers only requests that reach
AnnotateR; a platform or proxy may reject an upload earlier, and that
response is not guaranteed to be AnnotateR's own error message.

**Streamlit generation:** the effective per-file upload limit is Streamlit's
`server.maxUploadSize`, which defaults to **200 MB** in the pinned Streamlit
release (1.64.0); an operator can change it with
`STREAMLIT_SERVER_MAX_UPLOAD_SIZE` (in MB). Serve also documents a **100 MB
upload limit** for its Streamlit app type, without stating whether it is per
file or per request.

Serve's 100 MB upload limit is a platform limit, not an AnnotateR default:
when you run the image yourself, the application limit remains
`MAX_FILE_SIZE_MB` (500 MB unless changed).

### Data handling

- Uploaded files are processed by the running AnnotateR server.
- In the React/FastAPI image a temporary copy of each upload is written
  under the system temporary directory (`tempfile.mkdtemp`) for parsing and
  deleted immediately afterwards, whether parsing succeeds or fails. In the
  Streamlit generation the copy is written under `TEMP_DIR`.
- Parsed data and results remain only in application memory for the
  active session; AnnotateR does not intentionally persist uploaded files
  or results after that lifecycle.
- Session state is held in the API process's memory and addressed by a
  per-browser cookie, so the API must run a single Uvicorn worker. With more
  than one worker a follow-up request could be routed to a process that does
  not hold the session's state. The bundled `start-script.sh` starts a single
  worker accordingly.
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

## Single-worker requirement

The React/FastAPI image keeps each user's parsed data, options, and results in
an **in-memory** session store, addressed by the session cookie: the
unprefixed `annotater_session` over plain HTTP, and — when the request
arrives over HTTPS via the trusted proxy — the `__Host-` prefixed
`__Host-annotater_session`. Both carry a server-generated token and are
`HttpOnly` and `SameSite=Lax`; over TLS the cookie is additionally `Secure`
with `Path=/` and no `Domain` (the `__Host-` prefix enforces exactly that),
and the unprefixed cookie is never read, so a token planted by a sibling
subdomain cannot fixate the session. The cookie name is matched byte-exactly
against the raw `Cookie` header: a name that is not the exact name (for
example one prefixed with a non-ASCII whitespace byte, which browsers do not
treat as `__Host-`) is ignored, so it can neither fixate nor deny service.
Only the byte-exact session cookie presented more than once is rejected with
HTTP 400 as genuinely ambiguous; clearing the site's cookies recovers. Because the state lives in one
process's memory, the app **must run exactly one Uvicorn worker**:

- `start-script.sh` starts a single worker and deliberately passes no
  `--workers` flag;
- with more than one worker, a follow-up request (execute, export, paginated
  results) could be routed to a process that does not hold that session's
  state, and the session would appear empty or inconsistent;
- the deployment is therefore vertically scaled (more CPU/RAM), not
  horizontally scaled. Do not add workers, and do not put multiple replicas
  behind a non-sticky load balancer;
- `--proxy-headers` with a trusted `--forwarded-allow-ips` is what lets the
  TLS-terminating Serve proxy influence the `Secure` cookie decision; if the
  proxy is bypassed or untrusted, adjust `FORWARDED_ALLOW_IPS`.

## Expected startup and resources

- Cold start (interpreter + imports + Uvicorn, plus the static React
  assets) takes roughly 10–20 s locally; Serve may need a couple of minutes
  after *Running* before the app answers (stated by Serve). The Streamlit
  generation's cold start is comparable.
- Default allocation (2 vCPU / 4 GB RAM) is sufficient for interactive
  use with files below Serve's documented 100 MB upload limit; the
  in-container smoke test passes within these limits. Very large inputs
  (hundreds of MB) need headroom for canonical frames held in memory — see
  [Limitations](limitations.md). Concurrent upload parses multiply that
  peak; see [Parsing concurrency](#parsing-concurrency).
- The filesystem is ephemeral except for the project *Mount path* (not
  used). Each upload is written to a temporary file under the system
  temporary directory (`tempfile.mkdtemp`) for parsing and deleted
  immediately afterwards; parsed data is held in memory. Intermediate
  bedtools files are likewise written by pybedtools to the system temp
  directory (`TMPDIR` if set).

## Deployment verification

After (re)deploying:

1. Open the app URL (or `http://localhost:8000` for a local React/FastAPI
   container, `http://localhost:8501` for a local Streamlit-generation
   container).
2. Confirm the service is healthy: `GET /health` must return
   `{"status": "ok", ...}` (React/FastAPI image) — the same check Docker and
   Serve use. For the Streamlit generation, `GET /_stcore/health`.
3. Run the built-in check: upload `data/examples/example_coordinates.bed`
   as coordinates and `data/examples/example_annotations.gff3` as
   annotations, run **overlap**, then rerun with the other engine — both
   must return identical canonical results (the UI states the backends
   are interchangeable).
4. Confirm the deployed image version separately from the application
   version: the running app reports the application version (`0.1.0`, which is
   unchanged across the release candidates and the final release), so it cannot
   identify an RC tag (`/api/meta` for the React/FastAPI image; the footer for
   the Streamlit generation). Check the image's OCI label instead, e.g.
   `docker inspect --format '{{ index .Config.Labels "org.opencontainers.image.version" }}' ghcr.io/pyrevo/annotater:<tag>`,
   which the `release-ghcr` workflow sets to the published tag.
5. For Serve: confirm the container status is *Running* and the health
   check in the app overview is green.

### Current public beta deployment

The public beta deployment at <https://annotater.serve.scilifelab.se> is
**running the `0.1.0-rc2` image** — the **Streamlit** generation, not the
React/FastAPI image described above. The maintainer updated the existing
Serve app from `0.1.0-rc1` by changing only the container image
reference; the deployment is healthy and the application loads. The
deployment is referenced by tag, not pinned by digest; the verified GHCR
digest of that tag is recorded separately in
[Release-candidate publications](https://github.com/pyrevo/annotater/blob/main/docs/release-plan-0.1.0.md#release-candidate-publications).
This is a pre-release deployment: final `v0.1.0` has not been released, and
the React/FastAPI image has not been deployed.

## Common failure modes

| Symptom | Likely cause / fix |
|---|---|
| `docker build` fails in `pip install` on an Apple Silicon host | Building arm64-native. Build with `--platform linux/amd64` (the `Dockerfile` already pins amd64; on Apple Silicon enable amd64 emulation in Docker Desktop — Rosetta when available — for the faster path). |
| Serve keeps serving an old version | Reused an image tag. Publish a **new unique tag** and update the Image field. |
| Serve app never becomes available | Image tag not pulled (private GHCR package, image deleted, or typo in the Image field). The image must stay publicly available at all times. |
| Uploads are rejected on Serve | Serve documents a 100 MB upload limit for Streamlit and other/custom apps but does not state whether it is per file or per request. The platform or proxy may reject before AnnotateR, so the response is not guaranteed to be AnnotateR's own error. Setting `MAX_FILE_SIZE_MB=100` is a recommended app-level validation setting, not a verified Serve requirement (see [Upload size](#upload-size)). When running the image yourself, the React/FastAPI limit is `MAX_FILE_SIZE_MB` (default 500 MB). |
| bedtools engine errors only in the container | `bedtools` not on `PATH` inside the image — run `scripts/docker_smoke.sh`; it asserts version 2.31.x. |
| App is slow on Serve | Default 2 vCPU/4 GB allocation. Request more resources via serve@scilifelab.se with a concrete workload example. |
| Positions ≥ 2³¹ error from the Bedtools engine | pybedtools packs coordinates into a 32-bit field (see [benchmark docs](benchmark.md) / Limitations). Not reachable with natural chromosomes. |

## References

Current official documentation (SciLifeLab Serve docs v5.3.0-beta, page
version 2026-09-23, re-checked 2026-10-22; exact links are kept in
[references.md](references.md)):

- SciLifeLab Serve — Streamlit app hosting guide (step-by-step, resource
  defaults, upload limit, image/tag rules)
- SciLifeLab Serve — other/custom app hosting guide (Docker images,
  working-directory startup script, port range, UID 1000, upload limit,
  visibility)
- SciLifeLab Serve — application hosting overview (port range, public
  code/data, no databases)
- Docker build reference (`--platform`)
- PyPI — `polars-bio` (wheel availability per platform)