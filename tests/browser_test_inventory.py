"""Explicit inventory of the required real-browser regression suite.

The browser job is only trustworthy if every regression it claims to gate is
collected and executed.  This list is deliberately explicit: a renamed,
deleted, deselected, skipped or xfailed regression must break the required
job instead of silently shrinking coverage.

When a legitimate browser regression is added, add its exact pytest node ID
here in the same change.  ``tests/test_browser_ci_contract.py`` proves that
this inventory matches the suite's real collection.
"""

from __future__ import annotations

BROWSER_TEST_MODULE = "tests/test_browser_multi_tab.py"

EXPECTED_BROWSER_TESTS: tuple[str, ...] = (
    f"{BROWSER_TEST_MODULE}::test_second_tab_cannot_make_first_tab_export_or_run_its_analysis",
    f"{BROWSER_TEST_MODULE}::test_upload_409_conflict_drops_the_stale_side_and_disables_run",
    f"{BROWSER_TEST_MODULE}::test_cross_tab_cleanup_cannot_wipe_a_newer_upload",
    f"{BROWSER_TEST_MODULE}::test_separate_browser_sessions_stay_independent",
    f"{BROWSER_TEST_MODULE}::test_sample_load_shows_provenance_without_hijacking_the_declaration",
    f"{BROWSER_TEST_MODULE}::test_custom_registry_is_not_adopted_across_tabs_and_clears_its_results",
    f"{BROWSER_TEST_MODULE}::test_a_replaced_dataset_never_leaves_a_stale_result",
    f"{BROWSER_TEST_MODULE}::test_a_failed_upload_can_be_retried_with_the_same_file",
    f"{BROWSER_TEST_MODULE}::test_a_non_json_http_refusal_preserves_the_loaded_dataset",
    f"{BROWSER_TEST_MODULE}::test_closest_sample_uses_its_declared_operation_without_meta",
)

BROWSER_REQUIRED_ENV = "ANNOTATER_BROWSER_REQUIRED"
BROWSER_OPT_IN_ENV = "ANNOTATER_BROWSER_TESTS"
BROWSER_CHANNEL_ENV = "ANNOTATER_BROWSER_CHANNEL"
BROWSER_CHANNEL_VALUE = "bundled"
