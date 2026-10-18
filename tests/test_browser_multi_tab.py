"""Real-browser two-tab regression (release-gate finding F1).

Opt-in, like the container tests: it drives system Google Chrome through
Playwright against the real FastAPI app serving the built React frontend.

    (cd frontend && npm run build)
    ANNOTATER_BROWSER_TESTS=1 uv run --with playwright==1.64.0 \\
        pytest tests/test_browser_multi_tab.py

The gate's reproduction: two tabs of one browser share the session cookie.
Tab A runs Auto-detect (0-based: 0 of 1 matched); tab B runs the same file
declared 1-based (1 of 1 matched). Tab A still displays "0 of 1", but its
Export used to download tab B's 1-based result and a re-run silently used
tab B's datasets. Now both are visible conflicts in tab A.
"""

from __future__ import annotations

import json
import os
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

pytestmark = pytest.mark.skipif(
    os.environ.get("ANNOTATER_BROWSER_TESTS") != "1",
    reason="real-browser tests are opt-in: set ANNOTATER_BROWSER_TESTS=1 "
    "(needs Playwright, Google Chrome, bedtools and a built frontend)",
)


@pytest.fixture(scope="module")
def base_url():
    if not (DIST / "index.html").is_file():
        pytest.skip("frontend/dist is not built (cd frontend && npm run build)")
    if not engine_available("bedtools"):
        pytest.skip("bedtools is not installed")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "streamlit_app.api_server:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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
            pytest.fail("API server did not start")
        yield url
    finally:
        server.terminate()
        server.wait(timeout=10)


@pytest.fixture()
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            chrome = p.chromium.launch(channel="chrome", headless=True)
        except Exception as exc:  # noqa: BLE001 - absent system Chrome
            pytest.skip(f"Google Chrome is not available: {exc}")
        yield chrome
        chrome.close()


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


def _no_download(page, action, wait_ms=2500):
    downloads = []
    page.on("download", lambda download: downloads.append(download))
    action()
    page.wait_for_timeout(wait_ms)
    return downloads


def test_second_tab_cannot_make_first_tab_export_or_run_its_analysis(browser, base_url, files, tmp_path):
    context = browser.new_context(accept_downloads=True)
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
    context.close()


def test_upload_409_conflict_drops_the_stale_side_and_disables_run(browser, base_url, files):
    """Issue #58: a superseded upload must reset the tab, not keep the old file.

    With both sides loaded, the next query upload is answered with the 409
    ``revision_conflict`` PR #57 returns when another tab wins the race. The
    tab must drop the stale query card, keep the untouched annotation, show the
    "Changed in another tab" warning and leave Run disabled until a re-upload.
    """
    context = browser.new_context(accept_downloads=True)
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
    context.close()


def test_cross_tab_cleanup_cannot_wipe_a_newer_upload(browser, base_url, files):
    """Issue #51: an unknown-outcome clean-up names only the revision it owns.

    Tab A watches its next query upload die in flight, so the server's stored
    revision for that upload is unknown. Tab B (same session) has since stored a
    newer query under a new revision. Tab A's recovery must clear only the
    revision it last owned; a blind revision-less clear would delete tab B's
    newer dataset and break its export.
    """
    context = browser.new_context(accept_downloads=True)
    tab_a = _open_tab(context, base_url)
    assert "0 of 1 regions matched" in _load_and_run(tab_a, files, one_based=False)

    # Tab B stores a newer query under a fresh revision and proves it runs.
    tab_b = _open_tab(context, base_url)
    assert "1 of 1 regions matched" in _load_and_run(tab_b, files, one_based=True)

    # Tab A's next upload never reaches the server: outcome unknown, server
    # revision unknown, so only tab A's last-known revision may be cleared.
    tab_a.route("**/api/upload", lambda route: route.abort())
    superseded = files / "superseded.tsv"
    superseded.write_text("chr1\t100\t200\tr1\n")
    tab_a.bring_to_front()
    tab_a.locator("input[type=file]").nth(0).set_input_files(superseded)
    tab_a.wait_for_selector("text=/Network error uploading file/")

    # Tab B's newer dataset survived the clean-up: it still exports its own
    # 1-based result (a wiped query would leave it with nothing to export).
    tab_b.bring_to_front()
    assert tab_b.locator("text=1 of 1 regions matched").count() == 1
    with tab_b.expect_download() as info:
        tab_b.get_by_role("button", name="CSV", exact=True).click()
    assert MATCH_ROW in Path(info.value.path()).read_text()
    context.close()


def test_separate_browser_sessions_stay_independent(browser, base_url, files):
    one = browser.new_context(accept_downloads=True)
    two = browser.new_context(accept_downloads=True)  # a separate cookie jar
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
    one.close()
    two.close()
