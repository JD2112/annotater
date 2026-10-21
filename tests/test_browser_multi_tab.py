"""Real-browser two-tab regression (release-gate finding F1).

Opt-in, like the container tests: it drives a real browser through Playwright
against the real FastAPI app serving the built React frontend. CI sets
``ANNOTATER_BROWSER_REQUIRED=1`` so a missing browser/build is a failure, not
a skip, and ``ANNOTATER_BROWSER_CHANNEL=bundled`` to use Playwright's managed
Chromium. Locally the default is the system Google Chrome channel:

    (cd frontend && npm run build)
    ANNOTATER_BROWSER_TESTS=1 \\
        uv run --with playwright==1.64.0 --extra dev pytest tests/test_browser_multi_tab.py

    # Use Playwright's bundled Chromium instead of system Chrome:
    ANNOTATER_BROWSER_TESTS=1 ANNOTATER_BROWSER_CHANNEL=bundled \\
        uv run --with playwright==1.64.0 \\
        playwright install chromium
    ANNOTATER_BROWSER_TESTS=1 ANNOTATER_BROWSER_CHANNEL=bundled \\
        uv run --with playwright==1.64.0 --extra dev pytest tests/test_browser_multi_tab.py

Set ``ANNOTATER_BROWSER_LOG_DIR`` and/or ``ANNOTATER_BROWSER_TRACE_DIR`` to
capture server/browser logs and Playwright traces (the CI job uploads both
on failure).

The gate's reproduction: two tabs of one browser share the session cookie.
Tab A runs Auto-detect (0-based: 0 of 1 matched); tab B runs the same file
declared 1-based (1 of 1 matched). Tab A still displays "0 of 1", but its
Export used to download tab B's 1-based result and a re-run silently used
tab B's datasets. Now both are visible conflicts in tab A.

It also verifies issue #54 as corrected for finding F1 in a real browser:
loading a bundled sample *displays* the convention actually applied to the
loaded files as provenance, without changing the coordinate declaration used
for the user's next upload.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from streamlit_app.core.engine_registry import engine_available

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend" / "dist"
ONE_BASED = "1-based (GFF/GTF/VCF)"
MATCH_ROW = "left_edge_base100"
LOG_DIR_ENV = "ANNOTATER_BROWSER_LOG_DIR"
TRACE_DIR_ENV = "ANNOTATER_BROWSER_TRACE_DIR"
_REQUIRED = os.environ.get("ANNOTATER_BROWSER_REQUIRED") == "1"
_OPTED_IN = os.environ.get("ANNOTATER_BROWSER_TESTS") == "1"

pytestmark = pytest.mark.skipif(
    not _OPTED_IN and not _REQUIRED,
    reason="real-browser tests are opt-in: set ANNOTATER_BROWSER_TESTS=1 "
    "(needs Playwright, a browser, bedtools and a built frontend)",
)


@pytest.fixture(scope="session", autouse=True)
def _required_mode_needs_opt_in():
    """Never let a REQUIRED run become green while browser tests are disabled."""
    if _REQUIRED and not _OPTED_IN:
        pytest.fail(
            "ANNOTATER_BROWSER_REQUIRED=1 requires ANNOTATER_BROWSER_TESTS=1; "
            "refusing to run with the browser suite disabled."
        )


def _env_dir(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _skip_or_fail(reason: str) -> None:
    """Skip locally, but never let a missing prerequisite pass CI silently."""
    if os.environ.get("ANNOTATER_BROWSER_REQUIRED") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


def _watch_page(page, record) -> None:
    page.on("console", lambda msg: record(f"console[{msg.type}] {msg.text}"))
    page.on("pageerror", lambda exc: record(f"pageerror: {exc}"))
    page.on(
        "requestfailed",
        lambda req: record(
            f"requestfailed: {req.method} {req.url} ({req.failure})"
        ),
    )


@pytest.fixture(scope="module")
def base_url():
    if not (DIST / "index.html").is_file():
        _skip_or_fail("frontend/dist is not built (cd frontend && npm run build)")
    if not engine_available("bedtools"):
        _skip_or_fail("bedtools is not installed")

    log_dir = _env_dir(LOG_DIR_ENV)
    log_path = log_dir / "server.log" if log_dir else None
    log_handle = log_path.open("w") if log_path else None
    output = log_handle if log_handle else subprocess.DEVNULL

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "streamlit_app.api_server:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(f"{url}/health", timeout=1)
                break
            except OSError:
                time.sleep(0.25)
        else:
            detail = ""
            if log_path and log_path.is_file():
                detail = log_path.read_text(errors="replace")[-4000:]
            pytest.fail(f"API server did not start\n{detail}".rstrip())
        yield url
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)
        if log_handle:
            log_handle.close()


@pytest.fixture()
def browser():
    try:
        from playwright import sync_api
    except ImportError as exc:  # pragma: no cover - opt-in environment
        reason = f"Playwright is not installed: {exc}"
        if os.environ.get("ANNOTATER_BROWSER_REQUIRED") == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    channel = os.environ.get("ANNOTATER_BROWSER_CHANNEL", "chrome").strip()
    bundled = channel.lower() in {"", "bundled"}
    launch_options = {"headless": True}
    if not bundled:
        launch_options["channel"] = channel
    with sync_api.sync_playwright() as p:
        try:
            chrome = p.chromium.launch(**launch_options)
        except Exception as exc:  # noqa: BLE001 - absent browser
            reason = f"browser is not available ({channel or 'bundled'}): {exc}"
            if bundled or os.environ.get("ANNOTATER_BROWSER_REQUIRED") == "1":
                pytest.fail(reason)
            pytest.skip(reason)
        yield chrome
        chrome.close()


@pytest.fixture()
def new_context(browser, request):
    """Create isolated contexts and record traces/console logs when requested."""
    trace_dir = _env_dir(TRACE_DIR_ENV)
    log_dir = _env_dir(LOG_DIR_ENV)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.name)
    created = []

    def make(**kwargs):
        context = browser.new_context(**kwargs)
        index = len(created)
        events = []
        if log_dir:
            context.on("page", lambda page: _watch_page(page, events.append))
        if trace_dir:
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
        created.append(
            (
                context,
                events,
                log_dir / f"{safe_name}-{index}.browser.log" if log_dir else None,
                trace_dir / f"{safe_name}-{index}.zip" if trace_dir else None,
            )
        )
        return context

    yield make

    for context, events, events_path, trace_path in created:
        if trace_path:
            try:
                context.tracing.stop(path=str(trace_path))
            except Exception as exc:  # noqa: BLE001 - context may already be gone
                events.append(f"trace stop failed: {exc}")
        context.close()
        if events_path:
            events_path.write_text("\n".join(events) + ("\n" if events else ""))


@pytest.fixture()
def files(tmp_path):
    # Query chr1 100 200 overlaps the annotation [99,100) only when read
    # 1-based, so the match count shows which declaration a run used.
    (tmp_path / "regions.tsv").write_text("chr1\t100\t200\tr1\n")
    (tmp_path / "annot.bed").write_text(f"chr1\t99\t100\t{MATCH_ROW}\n")
    return tmp_path


def _coord_select(page):
    return page.locator("select").filter(has=page.locator("option[value='0-based (BED)']")).nth(0)


def _load_and_run(page, files, one_based):
    page.locator("input[type=file]").nth(1).set_input_files(files / "annot.bed")
    page.wait_for_selector("text=Parsed annot.bed")
    if one_based:
        _coord_select(page).select_option(ONE_BASED)
    page.locator("input[type=file]").nth(0).set_input_files(files / "regions.tsv")
    page.wait_for_selector("text=Parsed regions.tsv")
    page.click("button:has-text('Run annotation')")
    page.wait_for_selector("text=Analysis complete")
    return page.locator("text=/Analysis complete.*regions matched/").inner_text()


def _open_tab(context, base_url):
    page = context.new_page()
    page.goto(base_url)
    page.wait_for_selector("text=Run annotation")
    return page


def _record_uploads(page):
    """Collect successful /api/upload responses so tests can name revisions."""
    responses = []

    def record(response):
        if (
            response.url.endswith("/api/upload")
            and response.request.method == "POST"
            and response.status == 200
        ):
            responses.append(response)

    page.on("response", record)
    return responses


def _upload_revision(responses, role):
    for response in responses:
        body = response.json()
        if body.get("role") == role:
            return body["revision"]
    raise AssertionError(f"no successful {role} upload response was recorded")


def _no_download(page, action, wait_ms=2500):
    downloads = []
    page.on("download", lambda download: downloads.append(download))
    action()
    page.wait_for_timeout(wait_ms)
    return downloads


def test_second_tab_cannot_make_first_tab_export_or_run_its_analysis(new_context, base_url, files, tmp_path):
    context = new_context(accept_downloads=True)
    tab_a = _open_tab(context, base_url)
    assert "0 of 1 regions matched" in _load_and_run(tab_a, files, one_based=False)
    tab_b = _open_tab(context, base_url)  # same browser -> same session cookie
    assert "1 of 1 regions matched" in _load_and_run(tab_b, files, one_based=True)

    # Back in tab A, which still displays its own Auto-detect run.
    tab_a.bring_to_front()
    assert tab_a.locator("text=0 of 1 regions matched").count() == 1

    # Export: previously downloaded tab B's 1-based result. Now: no download,
    # a visible conflict, and tab A's superseded results are withdrawn.
    downloads = _no_download(tab_a, lambda: tab_a.get_by_role("button", name="CSV", exact=True).click())
    assert downloads == []
    alert = tab_a.get_by_role("alert")
    assert "Changed in another tab" in alert.inner_text()
    assert "Nothing was exported" in alert.inner_text()
    assert tab_a.locator("text=No results yet").count() == 1

    # Re-run: previously ran on tab B's 1-based datasets ("1 of 1"). Now a
    # visible conflict that drops the stale file cards.
    tab_a.click("button:has-text('Run annotation')")
    tab_a.wait_for_selector("text=/Changed in another tab: The query and annotation datasets shown in this tab are no longer loaded/")
    assert tab_a.locator("text=Analysis complete").count() == 0
    assert tab_a.get_by_role("button", name="Run annotation").is_disabled()

    # Explicit re-upload in tab A restores a consistent tab whose export is
    # its own Auto-detect (0-based, unmatched) result.
    assert "0 of 1 regions matched" in _load_and_run(tab_a, files, one_based=False)
    with tab_a.expect_download() as info:
        tab_a.get_by_role("button", name="CSV", exact=True).click()
    exported = Path(info.value.path()).read_text()
    assert MATCH_ROW not in exported
    assert "chr1,100,200" in exported

    # ...and now it is tab B that is told, rather than exporting tab A's run.
    tab_b.bring_to_front()
    downloads = _no_download(tab_b, lambda: tab_b.get_by_role("button", name="CSV", exact=True).click())
    assert downloads == []
    assert "Changed in another tab" in tab_b.get_by_role("alert").inner_text()


def test_upload_409_conflict_drops_the_stale_side_and_disables_run(new_context, base_url, files):
    """Issue #58: a superseded upload must reset the tab, not keep the old file.

    With both sides loaded, the next query upload is answered with the 409
    ``revision_conflict`` PR #57 returns when another tab wins the race. The
    tab must drop the stale query card, keep the untouched annotation, show the
    "Changed in another tab" warning and leave Run disabled until a re-upload.
    """
    context = new_context(accept_downloads=True)
    page = _open_tab(context, base_url)
    assert "0 of 1 regions matched" in _load_and_run(page, files, one_based=False)
    assert page.get_by_role("button", name="Run annotation").is_enabled()

    page.route(
        "**/api/upload",
        lambda route: route.fulfill(
            status=409,
            content_type="application/json",
            body=json.dumps({
                "detail": {
                    "code": "revision_conflict",
                    "message": "This query upload was superseded by a newer upload or "
                    "clear from another tab of this browser session; nothing was stored.",
                    "stale": ["query"],
                }
            }),
        ),
    )
    # A fresh filename, so the picker actually fires a change event.
    superseded = files / "superseded.tsv"
    superseded.write_text("chr1\t100\t200\tr1\n")
    page.locator("input[type=file]").nth(0).set_input_files(superseded)

    page.wait_for_selector("text=/Changed in another tab/")
    assert page.locator("text=regions.tsv").count() == 0
    assert page.locator("text=annot.bed").count() == 1
    assert page.get_by_role("button", name="Run annotation").is_disabled()


def test_cross_tab_cleanup_cannot_wipe_a_newer_upload(new_context, base_url, files):
    """Issue #51: an unknown-outcome clean-up names only the revision it owns.

    Tab A watches its next query upload die in flight, so the server's stored
    revision for that upload is unknown. Tab B (same session) has since stored a
    newer query under a new revision. Tab A's recovery must clear only the
    revision it last owned; a blind revision-less clear would delete tab B's
    newer dataset and break its export.
    """
    context = new_context(accept_downloads=True)
    tab_a = _open_tab(context, base_url)
    tab_a_uploads = _record_uploads(tab_a)
    assert "0 of 1 regions matched" in _load_and_run(tab_a, files, one_based=False)
    stale_query_revision = _upload_revision(tab_a_uploads, "query")

    # Tab B stores a newer query under a fresh revision and proves it runs.
    tab_b = _open_tab(context, base_url)
    tab_b_uploads = _record_uploads(tab_b)
    assert "1 of 1 regions matched" in _load_and_run(tab_b, files, one_based=True)
    newer_query_revision = _upload_revision(tab_b_uploads, "query")
    assert newer_query_revision != stale_query_revision

    # Tab A's next upload never reaches the server: outcome unknown, server
    # revision unknown, so only tab A's last-known revision may be cleared.
    tab_a.route("**/api/upload", lambda route: route.abort())
    superseded = files / "superseded.tsv"
    superseded.write_text("chr1\t100\t200\tr1\n")
    tab_a.bring_to_front()

    # Gate on the actual clean-up request and response, not the UI message:
    # the message is shown before the fetch is even sent, so waiting on it
    # would let this test pass before the server has ruled on the clear.
    with tab_a.expect_request(
        lambda request: request.url.endswith("/api/dataset/clear")
        and request.method == "POST"
    ) as clear_request_info, tab_a.expect_response(
        lambda response: response.url.endswith("/api/dataset/clear")
        and response.request.method == "POST"
    ) as clear_response_info:
        tab_a.locator("input[type=file]").nth(0).set_input_files(superseded)

    tab_a.wait_for_selector("text=/Network error uploading file/")
    clear_request = clear_request_info.value
    clear_payload = clear_request.post_data_json
    assert clear_payload == {
        "role": "query",
        "revision": stale_query_revision,
    }

    # The server refuses a clear of a revision another tab replaced. Asserting
    # the response means completion is observed, not merely a UI side effect.
    clear_response = clear_response_info.value
    assert clear_response.status == 409
    conflict = clear_response.json()["detail"]
    assert conflict["code"] == "revision_conflict"
    assert conflict["stale"] == ["query"]

    # Tab B's newer dataset survived the clean-up: it still exports its own
    # 1-based result (a wiped query would leave it with nothing to export).
    tab_b.bring_to_front()
    assert tab_b.locator("text=1 of 1 regions matched").count() == 1
    with tab_b.expect_download() as info:
        tab_b.get_by_role("button", name="CSV", exact=True).click()
    assert MATCH_ROW in Path(info.value.path()).read_text()


def test_separate_browser_sessions_stay_independent(new_context, base_url, files):
    one = new_context(accept_downloads=True)
    two = new_context(accept_downloads=True)  # a separate cookie jar
    tab_one = _open_tab(one, base_url)
    tab_two = _open_tab(two, base_url)
    assert "0 of 1 regions matched" in _load_and_run(tab_one, files, one_based=False)
    assert "1 of 1 regions matched" in _load_and_run(tab_two, files, one_based=True)

    with tab_one.expect_download() as info:
        tab_one.get_by_role("button", name="CSV", exact=True).click()
    assert MATCH_ROW not in Path(info.value.path()).read_text()
    with tab_two.expect_download() as info:
        tab_two.get_by_role("button", name="CSV", exact=True).click()
    assert MATCH_ROW in Path(info.value.path()).read_text()


def test_sample_load_shows_provenance_without_hijacking_the_declaration(new_context, base_url, tmp_path):
    """Issue #54 as corrected for finding F1, in a real browser.

    The gene_overlap sample pairs a BED query (0-based) with a GFF3
    annotation (1-based). Load Sample Data must *display* that applied
    convention as read-only provenance on the cards, without changing the
    coordinate selectors that declare how the user's next upload is parsed.

    A BED-like ``.tsv`` pair exercises the consequence: 0 matches under
    Auto-detect (the intervals touch), but 1 match if the annotation is read
    as 1-based. On the PR #67 head the sample's 1-based provenance leaked
    into the selector and this run read "1 of 1".
    """
    context = new_context()
    page = _open_tab(context, base_url)
    coord = page.locator("select").filter(has=page.locator("option[value='0-based (BED)']"))

    page.get_by_role("button", name="Load Sample Data").click()
    page.wait_for_selector("text=example_coordinates.bed")

    # Applied convention is displayed as provenance...
    assert page.locator("text=Coordinates: 0-based (BED)").count() >= 1
    assert page.locator("text=Coordinates: 1-based (GFF/GTF/VCF)").count() >= 1
    # ...and the selectors stay at the default for the next upload.
    assert coord.nth(0).input_value() == "Auto-detect"
    assert coord.nth(1).input_value() == "Auto-detect"

    (tmp_path / "neutral_query.tsv").write_text("chr1\t100\t105\tq\n")
    (tmp_path / "neutral_annot.tsv").write_text("chr1\t105\t106\tgene\n")
    page.locator("input[type=file]").nth(0).set_input_files(tmp_path / "neutral_query.tsv")
    page.wait_for_selector("text=Parsed neutral_query.tsv")
    page.locator("input[type=file]").nth(1).set_input_files(tmp_path / "neutral_annot.tsv")
    page.wait_for_selector("text=Parsed neutral_annot.tsv")
    page.click("button:has-text('Run annotation')")
    page.wait_for_selector("text=Analysis complete")
    result = page.locator("text=/Analysis complete.*regions matched/").inner_text()
    assert "0 of 1 regions matched" in result


def test_custom_registry_is_not_adopted_across_tabs_and_clears_its_results(
    new_context, base_url, tmp_path
):
    """M2.3: a custom mapping is explicit, tab-scoped and removable.

    Tab A uploads a custom mapping and runs with it. Tab B, in the same
    browser session, may select the custom source but must not see or adopt
    tab A's mapping: the resource is session-scoped at the API, while the
    control state belongs to the tab that uploaded it. Removing the mapping
    in tab A withdraws the result derived from it.
    """
    context = new_context()
    tab_a = _open_tab(context, base_url)

    mapping = tmp_path / "mapping.tsv"
    mapping.write_text(
        "assembly\tucsc\tensembl\tgenbank\trefseq\n"
        "1\tchr1\t1\tCM000001.1\tNC_000001.1\n"
    )
    query = tmp_path / "custom_query.bed"
    annot = tmp_path / "custom_annot.bed"
    query.write_text("chr1\t100\t200\tq\n")
    annot.write_text("1\t100\t200\tgene\n")

    assembly = tab_a.locator("select").filter(
        has=tab_a.locator("option[value='__custom_chromosome_mapping__']")
    ).nth(0)
    assembly.select_option(label="Custom chromosome mapping")
    tab_a.locator("select").filter(
        has=tab_a.locator("option[value='ucsc']")
    ).nth(0).select_option("ucsc")

    panel_a = tab_a.get_by_label("Custom chromosome mapping registry")
    assert panel_a.get_by_text("none", exact=True).is_visible()
    assert tab_a.get_by_role("button", name="Run annotation").is_disabled()

    with tab_a.expect_response(
        lambda response: response.url.endswith("/api/registry")
        and response.request.method == "POST"
    ) as upload_info:
        tab_a.get_by_label("Custom chromosome mapping TSV").set_input_files(mapping)
    registry = upload_info.value.json()["registry"]
    assert registry["source"] == "custom"
    assert registry["assembly"] is None
    tab_a.wait_for_selector("text=/Custom chromosome mapping loaded/")
    assert panel_a.get_by_text(registry["revision"]).is_visible()

    # A second tab in the same session selects the source, but never fetches
    # or adopts the mapping tab A uploaded.
    tab_b = _open_tab(context, base_url)
    tab_b.locator("select").filter(
        has=tab_b.locator("option[value='__custom_chromosome_mapping__']")
    ).nth(0).select_option(label="Custom chromosome mapping")
    tab_b.locator("select").filter(
        has=tab_b.locator("option[value='ucsc']")
    ).nth(0).select_option("ucsc")
    panel_b = tab_b.get_by_label("Custom chromosome mapping registry")
    assert panel_b.get_by_text("none", exact=True).is_visible()
    assert panel_b.locator("text=Revision").count() == 0
    assert tab_b.get_by_role("button", name="Run annotation").is_disabled()

    # Tab A's custom mapping supplies the chromosome identity: the annotation
    # "1" resolves to the query's UCSC "chr1".
    tab_a.bring_to_front()
    dataset_inputs = tab_a.locator("input[type=file]:not([aria-label])")
    dataset_inputs.nth(1).set_input_files(annot)
    tab_a.wait_for_selector("text=Parsed custom_annot.bed")
    dataset_inputs.nth(0).set_input_files(query)
    tab_a.wait_for_selector("text=Parsed custom_query.bed")
    tab_a.click("button:has-text('Run annotation')")
    tab_a.wait_for_selector("text=Analysis complete")
    result = tab_a.locator("text=/Analysis complete.*regions matched/").inner_text()
    assert "1 of 1 regions matched" in result

    # Reports identify the custom mapping and never claim an assembly.
    assert tab_a.locator("text=/Custom chromosome mapping:/").count() >= 1
    assert tab_a.locator(f"text={registry['revision']}").count() >= 1
    assert tab_a.locator("text=/Bundled assembly:/").count() == 0

    tab_a.get_by_role("button", name="Remove mapping").click()
    tab_a.wait_for_selector("text=Custom chromosome mapping removed.")
    assert tab_a.locator("text=No results yet").count() == 1
    assert panel_a.get_by_text("none", exact=True).is_visible()
    assert tab_a.get_by_role("button", name="Run annotation").is_disabled()


def test_a_replaced_dataset_never_leaves_a_stale_result(new_context, base_url, files, tmp_path):
    """M2.5 audit finding F8: an old result is never presented or exported
    as if it belonged to a newly uploaded dataset.

    A dataset *clear* drops the result derived from the cleared revision,
    while a dataset *replacement* keeps it (the result belongs to the run
    that produced it). The two are safe together because the interface
    withdraws its own displayed result on every invalidating event. This
    test pins that behaviour in a real browser:

    * re-uploading a side in the same tab withdraws the displayed result, so
      no stale table and no stale export survive the upload;
    * when another tab replaces the datasets, the tab that still displays
      the old result exports *its own* rows -- never the other tab's data
      -- and once the other tab has run, the export becomes a visible
      conflict instead of a download.
    """
    context = new_context(accept_downloads=True)
    tab_a = _open_tab(context, base_url)
    assert "0 of 1 regions matched" in _load_and_run(tab_a, files, one_based=False)
    assert tab_a.get_by_role("button", name="CSV", exact=True).count() == 1

    # A replacement upload in the same tab withdraws the displayed result.
    other = tmp_path / "other.tsv"
    other.write_text("chr1\t100\t200\tr1\n")
    tab_a.locator("input[type=file]").nth(0).set_input_files(other)
    tab_a.wait_for_selector("text=Parsed other.tsv")
    assert tab_a.locator("text=No results yet").count() == 1
    assert tab_a.get_by_role("button", name="CSV", exact=True).count() == 0

    # Run again, so this tab displays a result of its own (the replaced
    # query is still loaded).
    tab_a.click("button:has-text('Run annotation')")
    tab_a.wait_for_selector("text=Analysis complete")
    assert "0 of 1 regions matched" in tab_a.locator(
        "text=/Analysis complete.*regions matched/"
    ).inner_text()

    # Another tab replaces the datasets (without running).
    tab_b = _open_tab(context, base_url)
    tab_b.locator("input[type=file]").nth(1).set_input_files(files / "annot.bed")
    tab_b.wait_for_selector("text=Parsed annot.bed")
    tab_b.locator("input[type=file]").nth(0).set_input_files(files / "regions.tsv")
    tab_b.wait_for_selector("text=Parsed regions.tsv")

    # This tab still displays its own result and exports its own rows --
    # never the other tab's data.
    with tab_a.expect_download() as info:
        tab_a.get_by_role("button", name="CSV", exact=True).click()
    exported = Path(info.value.path()).read_text()
    assert MATCH_ROW not in exported
    assert "chr1,100,200" in exported

    # Once the other tab has run, the session's result is that tab's, so
    # this tab's export is a visible conflict and never a download.
    tab_b.click("button:has-text('Run annotation')")
    tab_b.wait_for_selector("text=Analysis complete")
    downloads = []
    tab_a.on("download", lambda d: downloads.append(d))
    tab_a.get_by_role("button", name="CSV", exact=True).click()
    tab_a.wait_for_timeout(2500)
    assert downloads == [], "a superseded result must not be downloaded"
    assert "Changed in another tab" in tab_a.get_by_role("alert").inner_text()


def test_a_failed_upload_can_be_retried_with_the_same_file(new_context, base_url, tmp_path):
    """M2.5: a refused upload must be retryable with the very same file.

    A native file input keeps its previous selection, and selecting the
    same file again fires no change event. Without remounting the picker
    after a refusal, the user's second attempt silently did nothing -- the
    interface showed the error again and again with no new request. The
    previously loaded dataset must survive the refusal.
    """
    context = new_context()
    page = _open_tab(context, base_url)

    bad = tmp_path / "bad.bed"
    bad.write_text("chr1\t100\t50\tbroken\n")
    uploads = []
    page.on(
        "response",
        lambda r: uploads.append(r.status) if "/api/upload" in r.url else None,
    )

    page.locator("input[type=file]").nth(0).set_input_files(bad)
    page.wait_for_selector("text=Uploading and parsing bad.bed")
    page.wait_for_timeout(1000)
    assert uploads == [400], uploads
    assert page.get_by_role("alert").count() >= 1

    # The same file, selected again, must be sent again.
    page.locator("input[type=file]").nth(0).set_input_files(bad)
    page.wait_for_timeout(1500)
    assert uploads == [400, 400], uploads
