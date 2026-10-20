"""Contract checks for the required real-browser CI gate.

The browser suite is opt-in locally, so the job can only be trustworthy if a
``REQUIRED`` run cannot go green while the suite is disabled, reduced or
misconfigured. These checks run without Playwright: collection fails before
any browser or frontend setup, and the workflow is inspected structurally
rather than by substring matching.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.browser_test_inventory import (
    BROWSER_CHANNEL_ENV,
    BROWSER_CHANNEL_VALUE,
    BROWSER_OPT_IN_ENV,
    BROWSER_REQUIRED_ENV,
    BROWSER_TEST_MODULE,
    EXPECTED_BROWSER_TESTS,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "python-tests.yml"
GUARD_MESSAGE = "ANNOTATER_BROWSER_REQUIRED=1 requires ANNOTATER_BROWSER_TESTS=1"
EXPECTED_JOBS = {
    "lock-consistency",
    "tests",
    "frontend-tests",
    "browser-regression",
    "docker-smoke",
}
BROWSER_COMMAND_PREFIX = (
    "uv",
    "run",
    "--with",
    "playwright==1.64.0",
    "pytest",
    BROWSER_TEST_MODULE,
)
ALLOWED_TRAILING_PYTEST_OPTIONS = frozenset({"-v", "-q"})
DURATIONS_OPTION = re.compile(r"--durations=\d+")
DOCUMENTED_COMMAND = (
    "uv run --with playwright==1.64.0 --extra dev pytest "
    "tests/test_browser_multi_tab.py"
)


# ---------------------------------------------------------------------------
# Workflow loading.
# ---------------------------------------------------------------------------


def load_workflow(path: Path) -> dict[str, object]:
    workflow = yaml.safe_load(path.read_text())
    assert isinstance(workflow, dict)
    return workflow


# ---------------------------------------------------------------------------
# Workflow contract.
# ---------------------------------------------------------------------------


def _browser_command_problems(run: str) -> list[str]:
    text = run.strip()
    if not text:
        return ["browser test command is empty"]
    if "\n" in text:
        return ["browser test command must be a single line"]
    try:
        tokens = shlex.split(text)
    except ValueError as exc:
        return [f"browser test command is not shell-tokenizable: {exc}"]
    prefix = BROWSER_COMMAND_PREFIX
    if tuple(tokens[: len(prefix)]) != prefix:
        return [
            (
                "browser test command must be exactly `uv run --with "
                "playwright==1.64.0 pytest tests/test_browser_multi_tab.py` "
                "followed only by -v/-q/--durations=N"
            )
        ]
    unexpected = [
        token
        for token in tokens[len(prefix) :]
        if token not in ALLOWED_TRAILING_PYTEST_OPTIONS
        and not DURATIONS_OPTION.fullmatch(token)
    ]
    if unexpected:
        return [f"browser test command uses unsupported option(s): {unexpected!r}"]
    return []


def audit_browser_workflow(path: Path) -> list[str]:
    workflow = load_workflow(path)
    problems: list[str] = []

    triggers = workflow.get("on")
    if triggers is None:
        # PyYAML resolves unquoted YAML 1.1 ``on`` to the boolean True.
        triggers = workflow.get(True)
    if not isinstance(triggers, dict) or "pull_request" not in triggers:
        problems.append("browser workflow must run on pull_request")

    if "defaults" in workflow:
        problems.append("workflow must not override the default shell or run defaults")

    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return problems + ["workflow has no jobs mapping"]

    absent_jobs = sorted(EXPECTED_JOBS - set(jobs))
    if absent_jobs:
        problems.append(f"existing CI job(s) missing: {', '.join(absent_jobs)}")

    job = jobs.get("browser-regression")
    if not isinstance(job, dict):
        return problems + ["missing browser-regression job"]
    if "if" in job:
        problems.append("browser-regression job must not be conditional")
    if "continue-on-error" in job:
        problems.append("browser-regression job must not use continue-on-error")
    if "defaults" in job:
        problems.append("browser-regression job must not override run defaults")

    steps = job.get("steps")
    if not isinstance(steps, list):
        return problems + ["browser-regression job has no steps list"]

    checkouts = [
        step
        for step in steps
        if isinstance(step, dict)
        and str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    if len(checkouts) != 1:
        problems.append("browser job must use exactly one checkout step")
    else:
        checkout = checkouts[0]
        if checkout.get("uses") != "actions/checkout@v4":
            problems.append("browser job must use actions/checkout@v4")
        checkout_with = checkout.get("with") or {}
        if isinstance(checkout_with, dict) and "ref" in checkout_with:
            problems.append(
                "browser job must test the default integration checkout, not a ref override"
            )

    pytest_steps = [
        (index, step)
        for index, step in enumerate(steps)
        if isinstance(step, dict)
        and isinstance(step.get("run"), str)
        and "pytest" in step["run"]
    ]
    browser_index: int | None = None
    if len(pytest_steps) != 1:
        problems.append("browser job must run exactly one pytest command")
    else:
        browser_index, step = pytest_steps[0]
        problems.extend(_browser_command_problems(str(step["run"])))
        env = step.get("env") or {}
        if not isinstance(env, dict):
            env = {}
        required_env = {
            BROWSER_OPT_IN_ENV: "1",
            BROWSER_REQUIRED_ENV: "1",
            BROWSER_CHANNEL_ENV: BROWSER_CHANNEL_VALUE,
        }
        for name, value in required_env.items():
            if str(env.get(name)) != value:
                problems.append(
                    f"browser test step must set {name}={value!r} on the run step"
                )
        if "if" in step:
            problems.append("browser test step must not be conditional")
        if "continue-on-error" in step:
            problems.append("browser test step must not use continue-on-error")
        if "shell" in step:
            problems.append("browser test step must not override the shell")
        if "working-directory" in step:
            problems.append("browser test step must not change the working directory")

    artifact_steps = [
        (index, step)
        for index, step in enumerate(steps)
        if isinstance(step, dict)
        and str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    if len(artifact_steps) != 1:
        problems.append("browser job must upload diagnostics with exactly one artifact step")
    else:
        artifact_index, artifact = artifact_steps[0]
        if browser_index is not None and artifact_index <= browser_index:
            problems.append(
                "diagnostics artifact upload must come after the browser test step"
            )
        condition = artifact.get("if")
        if not isinstance(condition, str) or (
            "failure()" not in condition or "cancelled()" not in condition
        ):
            problems.append(
                "diagnostics artifact must upload on failure() or cancelled()"
            )
        artifact_with = artifact.get("with") or {}
        if not isinstance(artifact_with, dict):
            artifact_with = {}
        if artifact_with.get("name") != "browser-regression-diagnostics":
            problems.append(
                "diagnostics artifact must be named browser-regression-diagnostics"
            )
        artifact_path = str(artifact_with.get("path", ""))
        for expected in ("browser-logs", "browser-traces"):
            if expected not in artifact_path:
                problems.append(f"diagnostics artifact must include {expected}")

    return problems


def test_the_workflow_satisfies_the_browser_contract():
    assert audit_browser_workflow(WORKFLOW) == []


def test_the_workflow_keeps_the_existing_ci_jobs():
    jobs = load_workflow(WORKFLOW)["jobs"]
    assert isinstance(jobs, dict)
    assert set(jobs) == EXPECTED_JOBS


def test_the_workflow_requires_diagnostics_after_the_browser_step(tmp_path: Path):
    workflow = load_workflow(WORKFLOW)
    steps = workflow["jobs"]["browser-regression"]["steps"]
    browser_index = next(
        index
        for index, step in enumerate(steps)
        if isinstance(step.get("run"), str) and "pytest" in step["run"]
    )
    artifact_index = next(
        index
        for index, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    )
    artifact = steps.pop(artifact_index)
    steps.insert(browser_index, artifact)
    path = tmp_path / "reordered.yml"
    path.write_text(yaml.safe_dump(workflow, sort_keys=False))
    problems = audit_browser_workflow(path)
    assert any("after the browser test step" in problem for problem in problems), problems


def _mutated_workflow(
    tmp_path: Path, *replacements: tuple[str, str]
) -> Path:
    text = WORKFLOW.read_text()
    for old, new in replacements:
        assert text.count(old) == 1, f"workflow fragment not unique: {old!r}"
        text = text.replace(old, new, 1)
    path = tmp_path / "python-tests.yml"
    path.write_text(text)
    return path


_MISSING_REQUIRED_FLAG = (
    f'          {BROWSER_REQUIRED_ENV}: "1"\n',
    "",
)
_MISSING_OPT_IN_FLAG = (
    f'          {BROWSER_OPT_IN_ENV}: "1"\n',
    "",
)
_WRONG_TEST_TARGET = (
    "pytest tests/test_browser_multi_tab.py -v --durations=10",
    "pytest tests/test_smoke.py -v --durations=10",
)
_ENV_ON_WRONG_STEP = (
    (
        "      - name: Record commit identity\n        run: |\n",
        (
            "      - name: Record commit identity\n"
            "        env:\n"
            f'          {BROWSER_OPT_IN_ENV}: "1"\n'
            f'          {BROWSER_REQUIRED_ENV}: "1"\n'
            "        run: |\n"
        ),
    ),
    (
        (
            "      - name: Run real-browser regression tests\n"
            "        env:\n"
            f'          {BROWSER_OPT_IN_ENV}: "1"\n'
            f'          {BROWSER_REQUIRED_ENV}: "1"\n'
            f'          {BROWSER_CHANNEL_ENV}: {BROWSER_CHANNEL_VALUE}\n'
            "          ANNOTATER_BROWSER_LOG_DIR: ${{ runner.temp }}/browser-logs\n"
            "          ANNOTATER_BROWSER_TRACE_DIR: ${{ runner.temp }}/browser-traces\n"
        ),
        "      - name: Run real-browser regression tests\n",
    ),
)
_CHECKOUT_REF_OVERRIDE = (
    "      - uses: actions/checkout@v4\n\n      - name: Record commit identity\n",
    (
        "      - uses: actions/checkout@v4\n"
        "        with:\n"
        "          ref: ${{ github.event.pull_request.head.sha }}\n\n"
        "      - name: Record commit identity\n"
    ),
)
_NO_PULL_REQUEST = ("  pull_request:\n", "  workflow_dispatch:\n")
_BROWSER_STEP_ANCHOR = "      - name: Run real-browser regression tests\n"
_QUOTED_CONTINUE_ON_ERROR = (
    _BROWSER_STEP_ANCHOR,
    _BROWSER_STEP_ANCHOR + '        "continue-on-error": true\n',
)
_QUOTED_STEP_IF = (
    _BROWSER_STEP_ANCHOR,
    _BROWSER_STEP_ANCHOR + '        "if": false\n',
)
_QUOTED_CHECKOUT_REF_OVERRIDE = (
    "      - uses: actions/checkout@v4\n\n      - name: Record commit identity\n",
    (
        "      - uses: actions/checkout@v4\n"
        "        with:\n"
        '          "ref": ${{ github.event.pull_request.head.sha }}\n\n'
        "      - name: Record commit identity\n"
    ),
)
_DISABLING_PYTEST_OPTION = (
    "pytest tests/test_browser_multi_tab.py -v --durations=10",
    "pytest tests/test_browser_multi_tab.py --noconftest -v --durations=10",
)
_PLUGIN_DISABLING_PYTEST_OPTION = (
    "pytest tests/test_browser_multi_tab.py -v --durations=10",
    "pytest tests/test_browser_multi_tab.py -p no:cacheprovider -v --durations=10",
)
_EXIT_BEFORE_PYTEST = (
    "          uv run --with playwright==1.64.0 pytest tests/test_browser_multi_tab.py -v --durations=10",
    (
        "          exit 0\n"
        "          uv run --with playwright==1.64.0 pytest tests/test_browser_multi_tab.py -v --durations=10"
    ),
)
_SHELL_OVERRIDE = (
    _BROWSER_STEP_ANCHOR,
    _BROWSER_STEP_ANCHOR + "        shell: bash\n",
)
_BROWSER_CONTINUE_ON_ERROR = (
    "      - name: Run real-browser regression tests\n",
    (
        "      - name: Run real-browser regression tests\n"
        "        continue-on-error: true\n"
    ),
)
_DIAGNOSTICS_ALWAYS = (
    "        if: failure() || cancelled()\n",
    "",
)


@pytest.mark.parametrize(
    ("replacements", "expected"),
    [
        ((_MISSING_REQUIRED_FLAG,), BROWSER_REQUIRED_ENV),
        ((_MISSING_OPT_IN_FLAG,), BROWSER_OPT_IN_ENV),
        ((_WRONG_TEST_TARGET,), "browser test command must be exactly"),
        (_ENV_ON_WRONG_STEP, BROWSER_REQUIRED_ENV),
        ((_CHECKOUT_REF_OVERRIDE,), "default integration checkout"),
        ((_QUOTED_CHECKOUT_REF_OVERRIDE,), "default integration checkout"),
        ((_NO_PULL_REQUEST,), "pull_request"),
        ((_BROWSER_CONTINUE_ON_ERROR,), "continue-on-error"),
        ((_QUOTED_CONTINUE_ON_ERROR,), "continue-on-error"),
        ((_QUOTED_STEP_IF,), "conditional"),
        ((_DISABLING_PYTEST_OPTION,), "unsupported option"),
        ((_PLUGIN_DISABLING_PYTEST_OPTION,), "unsupported option"),
        ((_EXIT_BEFORE_PYTEST,), "single line"),
        ((_SHELL_OVERRIDE,), "shell"),
        ((_DIAGNOSTICS_ALWAYS,), "failure() or cancelled()"),
    ],
)
def test_the_workflow_contract_rejects_broken_configuration(
    tmp_path: Path, replacements, expected: str
):
    problems = audit_browser_workflow(_mutated_workflow(tmp_path, *replacements))
    assert problems
    assert any(expected in problem for problem in problems), problems


def test_the_documented_playwright_command_uses_the_dev_environment():
    docs = (ROOT / "docs" / "deployment.md").read_text()
    module_doc = (ROOT / BROWSER_TEST_MODULE).read_text()
    assert DOCUMENTED_COMMAND in docs
    assert DOCUMENTED_COMMAND in module_doc


# ---------------------------------------------------------------------------
# Required-mode inventory and execution contract, in isolated subprocesses.
# ---------------------------------------------------------------------------


def _clean_env(*, required: bool, opt_in: bool) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("ANNOTATER_BROWSER_")
    }
    env.pop("PYTEST_ADDOPTS", None)
    if required:
        env[BROWSER_REQUIRED_ENV] = "1"
    if opt_in:
        env[BROWSER_OPT_IN_ENV] = "1"
    return env


def _run_pytest(
    cwd: Path,
    *arguments: str,
    required: bool,
    opt_in: bool,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *arguments,
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=cwd,
        env=_clean_env(required=required, opt_in=opt_in),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _synthetic_module(
    *,
    omit: str | None = None,
    rename: tuple[str, str] | None = None,
    skip: str | None = None,
    xfail: str | None = None,
    extra: bool = False,
) -> str:
    lines = ["from __future__ import annotations", "", "import pytest", ""]
    for nodeid in EXPECTED_BROWSER_TESTS:
        name = nodeid.split("::", 1)[1]
        if name == omit:
            continue
        if name == skip:
            lines.append('@pytest.mark.skip(reason="synthetic skip")')
        if name == xfail:
            lines.append('@pytest.mark.xfail(reason="synthetic xfail", strict=True)')
        actual = rename[1] if rename is not None and name == rename[0] else name
        body = "    assert False" if name == xfail else "    assert True"
        lines.extend([f"def {actual}():", body, ""])
    if extra:
        lines.extend(["def test_unexpected_browser_regression():", "    assert True", ""])
    return "\n".join(lines)


def _scratch_repo(tmp_path: Path, **module_options) -> Path:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    for name in ("conftest.py", "browser_contract.py", "browser_test_inventory.py"):
        shutil.copy2(ROOT / "tests" / name, tests_dir / name)
    (tests_dir / "__init__.py").write_text("")
    (tests_dir / "test_browser_multi_tab.py").write_text(
        _synthetic_module(**module_options)
    )
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\ntestpaths = tests\npythonpath = .\n"
    )
    return tmp_path


def _assert_failed(
    proc: subprocess.CompletedProcess[str], *fragments: str
) -> None:
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    for fragment in fragments:
        assert fragment in output, output


def test_the_required_browser_inventory_matches_real_collection():
    proc = _run_pytest(
        ROOT,
        BROWSER_TEST_MODULE,
        "--collect-only",
        required=False,
        opt_in=True,
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    for nodeid in EXPECTED_BROWSER_TESTS:
        assert nodeid in output, output


def test_required_mode_accepts_a_complete_executed_inventory(tmp_path: Path):
    proc = _run_pytest(
        _scratch_repo(tmp_path), BROWSER_TEST_MODULE, required=True, opt_in=True
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_required_mode_rejects_a_collection_only_run(tmp_path: Path):
    proc = _run_pytest(
        _scratch_repo(tmp_path),
        BROWSER_TEST_MODULE,
        "--collect-only",
        required=True,
        opt_in=True,
    )
    _assert_failed(proc, "did not run and pass")


def test_required_mode_rejects_a_setup_only_run(tmp_path: Path):
    proc = _run_pytest(
        _scratch_repo(tmp_path),
        BROWSER_TEST_MODULE,
        "--setup-only",
        required=True,
        opt_in=True,
    )
    _assert_failed(proc, "did not run and pass")


@pytest.mark.parametrize(
    "module_argument",
    (
        "./tests/test_browser_multi_tab.py",
        "tests/./test_browser_multi_tab.py",
    ),
)
def test_required_mode_rejects_missing_tests_for_equivalent_module_paths(
    tmp_path: Path, module_argument: str
):
    missing = EXPECTED_BROWSER_TESTS[0]
    proc = _run_pytest(
        _scratch_repo(tmp_path, omit=missing.split("::", 1)[1]),
        module_argument,
        required=True,
        opt_in=True,
    )
    _assert_failed(proc, "missing expected browser test", missing)


def test_required_mode_rejects_a_missing_browser_test(tmp_path: Path):
    missing = EXPECTED_BROWSER_TESTS[1]
    proc = _run_pytest(
        _scratch_repo(tmp_path, omit=missing.split("::", 1)[1]),
        BROWSER_TEST_MODULE,
        required=True,
        opt_in=True,
    )
    _assert_failed(proc, "missing expected browser test", missing)


def test_required_mode_rejects_a_renamed_browser_test(tmp_path: Path):
    original = EXPECTED_BROWSER_TESTS[2].split("::", 1)[1]
    renamed = "test_renamed_browser_regression"
    proc = _run_pytest(
        _scratch_repo(tmp_path, rename=(original, renamed)),
        BROWSER_TEST_MODULE,
        required=True,
        opt_in=True,
    )
    _assert_failed(
        proc,
        "missing expected browser test",
        original,
        "unexpected browser test",
        renamed,
    )


def test_required_mode_rejects_a_deselected_browser_test(tmp_path: Path):
    deselected = EXPECTED_BROWSER_TESTS[0]
    proc = _run_pytest(
        _scratch_repo(tmp_path),
        BROWSER_TEST_MODULE,
        f"--deselect={deselected}",
        required=True,
        opt_in=True,
    )
    _assert_failed(proc, "missing expected browser test", deselected)


def test_required_mode_rejects_a_keyword_deselected_browser_test(tmp_path: Path):
    deselected = EXPECTED_BROWSER_TESTS[1].split("::", 1)[1]
    proc = _run_pytest(
        _scratch_repo(tmp_path),
        BROWSER_TEST_MODULE,
        "-k",
        f"not {deselected}",
        required=True,
        opt_in=True,
    )
    _assert_failed(proc, "missing expected browser test", deselected)


def test_required_mode_rejects_an_uninventoried_new_browser_test(tmp_path: Path):
    proc = _run_pytest(
        _scratch_repo(tmp_path, extra=True),
        BROWSER_TEST_MODULE,
        required=True,
        opt_in=True,
    )
    _assert_failed(
        proc,
        "unexpected browser test",
        "test_unexpected_browser_regression",
        "browser_test_inventory.py",
    )


def test_required_mode_rejects_a_skipped_browser_test(tmp_path: Path):
    skipped = EXPECTED_BROWSER_TESTS[3]
    proc = _run_pytest(
        _scratch_repo(tmp_path, skip=skipped.split("::", 1)[1]),
        BROWSER_TEST_MODULE,
        required=True,
        opt_in=True,
    )
    _assert_failed(proc, "skipped or xfailed", skipped, "(skipped)")


def test_required_mode_rejects_an_xfailed_browser_test(tmp_path: Path):
    xfailed = EXPECTED_BROWSER_TESTS[4]
    proc = _run_pytest(
        _scratch_repo(tmp_path, xfail=xfailed.split("::", 1)[1]),
        BROWSER_TEST_MODULE,
        required=True,
        opt_in=True,
    )
    _assert_failed(proc, "skipped or xfailed", xfailed, "(xfailed)")


def test_local_opt_in_still_allows_a_skipped_browser_test(tmp_path: Path):
    skipped = EXPECTED_BROWSER_TESTS[3]
    proc = _run_pytest(
        _scratch_repo(tmp_path, skip=skipped.split("::", 1)[1]),
        BROWSER_TEST_MODULE,
        required=False,
        opt_in=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_local_default_still_skips_the_browser_suite():
    proc = _run_pytest(
        ROOT, BROWSER_TEST_MODULE, required=False, opt_in=False
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    assert f"{len(EXPECTED_BROWSER_TESTS)} skipped" in output


def test_required_mode_fails_when_the_opt_in_flag_is_missing():
    proc = _run_pytest(
        ROOT, BROWSER_TEST_MODULE, required=True, opt_in=False
    )
    _assert_failed(proc, GUARD_MESSAGE)
