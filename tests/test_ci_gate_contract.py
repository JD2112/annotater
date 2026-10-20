"""Contract checks for the stable ``ci-gate`` aggregate status check.

The workflow gate must fail whenever an essential validation job fails, is
cancelled or is skipped, and it must stay independent of deployment and
publication jobs.  The workflow is inspected structurally with PyYAML, and the
gate's decision logic is exercised directly against synthetic ``needs``
payloads, so these tests never need GitHub Actions or Docker.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "python-tests.yml"
DOCS_WORKFLOW = ROOT / ".github" / "workflows" / "docs.yaml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release-ghcr.yml"
GATE_SCRIPT = ROOT / "scripts" / "ci_gate.py"

GATE_JOB_ID = "ci-gate"
REQUIRED_JOBS = {
    "lock-consistency",
    "tests",
    "frontend-tests",
    "browser-regression",
    "docker-smoke",
}
GATE_COMMAND = ("python", "scripts/ci_gate.py")
GATE_CONDITION = "always()"


# ---------------------------------------------------------------------------
# Workflow loading and audit.
# ---------------------------------------------------------------------------


def load_workflow(path: Path = WORKFLOW) -> dict[str, object]:
    workflow = yaml.safe_load(path.read_text())
    assert isinstance(workflow, dict)
    return workflow


def _normalise_expression(value: object) -> str:
    return "".join(str(value).split())


def _triggers(workflow: dict[str, object]) -> object:
    triggers = workflow.get("on")
    if triggers is None:
        # PyYAML resolves unquoted YAML 1.1 ``on`` to the boolean True.
        triggers = workflow.get(True)
    return triggers


def audit_ci_gate(workflow: dict[str, object]) -> list[str]:
    """Return every structural problem that would weaken the gate."""

    problems: list[str] = []

    triggers = _triggers(workflow)
    if not isinstance(triggers, dict):
        problems.append("workflow must run on pull_request and main pushes")
    else:
        if "pull_request" not in triggers:
            problems.append("workflow must run on pull_request")
        push = triggers.get("push")
        branches = push.get("branches") if isinstance(push, dict) else None
        if not isinstance(branches, list) or "main" not in branches:
            problems.append("workflow must run on pushes to main")

    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return problems + ["workflow has no jobs mapping"]

    missing_jobs = sorted(REQUIRED_JOBS - set(jobs))
    if missing_jobs:
        problems.append(
            f"required validation job(s) missing: {', '.join(missing_jobs)}"
        )

    gate = jobs.get(GATE_JOB_ID)
    if not isinstance(gate, dict):
        return problems + [f"missing {GATE_JOB_ID} job"]

    if gate.get("name") != GATE_JOB_ID:
        problems.append(f"{GATE_JOB_ID} job must keep the stable check name")

    if _normalise_expression(gate.get("if", "")) not in {
        GATE_CONDITION,
        "${{" + GATE_CONDITION + "}}",
    }:
        problems.append(f"{GATE_JOB_ID} job must use if: always()")

    if "continue-on-error" in gate:
        problems.append(f"{GATE_JOB_ID} job must not use continue-on-error")

    needs = gate.get("needs")
    if not isinstance(needs, list):
        problems.append(f"{GATE_JOB_ID} job must declare an explicit needs list")
        needs_set: set[str] = set()
    else:
        needs_set = {str(job) for job in needs}
        missing_needs = sorted(REQUIRED_JOBS - needs_set)
        if missing_needs:
            problems.append("gate does not require: " + ", ".join(missing_needs))
        extra_needs = sorted(needs_set - REQUIRED_JOBS)
        if extra_needs:
            problems.append(
                "gate depends on non-validation job(s): " + ", ".join(extra_needs)
            )

    if "runs-on" not in gate:
        problems.append(f"{GATE_JOB_ID} job must declare runs-on")

    steps = gate.get("steps")
    if not isinstance(steps, list):
        return problems + [f"{GATE_JOB_ID} job has no steps list"]

    checkout_indices = [
        index
        for index, step in enumerate(steps)
        if isinstance(step, dict)
        and str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    run_steps = [
        (index, step)
        for index, step in enumerate(steps)
        if isinstance(step, dict) and "run" in step
    ]
    if len(run_steps) != 1:
        problems.append(f"{GATE_JOB_ID} job must run exactly one gate command")
    else:
        run_index, run_step = run_steps[0]
        if not checkout_indices or min(checkout_indices) > run_index:
            problems.append(f"{GATE_JOB_ID} must check out the gate script first")
        if "if" in run_step:
            problems.append("gate command must not be conditional")
        if "continue-on-error" in run_step:
            problems.append("gate command must not use continue-on-error")
        try:
            tokens = tuple(shlex.split(str(run_step["run"])))
        except ValueError as exc:
            problems.append(f"gate command is not shell-tokenizable: {exc}")
        else:
            if tokens != GATE_COMMAND:
                problems.append(
                    "gate command must be exactly `python scripts/ci_gate.py`"
                )
        env = run_step.get("env")
        if not isinstance(env, dict):
            problems.append("gate command must receive the needs outcomes")
        elif _normalise_expression(env.get("NEEDS_JSON", "")) != ("${{toJSON(needs)}}"):
            problems.append("gate command must receive NEEDS_JSON=${{ toJSON(needs) }}")

    return problems


# ---------------------------------------------------------------------------
# Gate decision logic.
# ---------------------------------------------------------------------------


def _load_gate_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("annotater_ci_gate", GATE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _all_successful() -> dict[str, dict[str, str]]:
    return {job: {"result": "success"} for job in REQUIRED_JOBS}


def _with_results(**overrides: str) -> dict[str, dict[str, str]]:
    needs = _all_successful()
    for job, result in overrides.items():
        needs[job] = {"result": result}
    return needs


def _run_gate(needs: object) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["NEEDS_JSON"] = json.dumps(needs)
    return subprocess.run(
        [sys.executable, str(GATE_SCRIPT)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_the_gate_script_requires_exactly_the_validation_jobs():
    module = _load_gate_module()
    assert set(module.REQUIRED_JOBS) == REQUIRED_JOBS
    assert len(module.REQUIRED_JOBS) == len(REQUIRED_JOBS)


def test_the_repository_workflow_satisfies_the_gate_contract():
    assert audit_ci_gate(load_workflow()) == []


def test_the_gate_requires_every_essential_validation_job():
    gate = load_workflow()["jobs"][GATE_JOB_ID]
    assert set(gate["needs"]) == REQUIRED_JOBS


def test_all_required_jobs_succeed_so_the_gate_succeeds():
    proc = _run_gate(_all_successful())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all required jobs succeeded" in proc.stdout


def test_any_required_job_failure_fails_the_gate():
    proc = _run_gate(_with_results(**{"browser-regression": "failure"}))
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "browser-regression: failure" in proc.stdout


def test_any_required_job_cancellation_fails_the_gate():
    proc = _run_gate(_with_results(**{"docker-smoke": "cancelled"}))
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "docker-smoke: cancelled" in proc.stdout


def test_any_required_job_skip_fails_the_gate():
    proc = _run_gate(_with_results(tests="skipped"))
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "tests: skipped" in proc.stdout


def test_a_missing_required_outcome_fails_the_gate():
    needs = _all_successful()
    del needs["lock-consistency"]
    proc = _run_gate(needs)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "lock-consistency: missing from needs" in proc.stdout


def test_an_unparseable_needs_payload_fails_the_gate():
    env = os.environ.copy()
    env["NEEDS_JSON"] = "not-json"
    proc = subprocess.run(
        [sys.executable, str(GATE_SCRIPT)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "cannot parse needs payload" in proc.stdout


# ---------------------------------------------------------------------------
# Mutations: the contract rejects weakened workflows.
# ---------------------------------------------------------------------------


def test_the_gate_contract_rejects_a_missing_required_dependency():
    workflow = copy.deepcopy(load_workflow())
    workflow["jobs"][GATE_JOB_ID]["needs"].remove("docker-smoke")
    problems = audit_ci_gate(workflow)
    assert any(
        "does not require" in problem and "docker-smoke" in problem
        for problem in problems
    ), problems


def test_the_gate_contract_rejects_a_renamed_required_job():
    workflow = copy.deepcopy(load_workflow())
    jobs = workflow["jobs"]
    jobs["docker-smoke-renamed"] = jobs.pop("docker-smoke")
    problems = audit_ci_gate(workflow)
    assert any(
        "required validation job(s) missing" in problem for problem in problems
    ), problems
    assert any("docker-smoke" in problem for problem in problems), problems


def test_the_gate_contract_rejects_an_extra_deployment_dependency():
    workflow = copy.deepcopy(load_workflow())
    workflow["jobs"][GATE_JOB_ID]["needs"].append("deploy")
    problems = audit_ci_gate(workflow)
    assert any(
        "non-validation job" in problem and "deploy" in problem for problem in problems
    ), problems


def test_the_gate_contract_rejects_a_conditional_gate():
    workflow = copy.deepcopy(load_workflow())
    workflow["jobs"][GATE_JOB_ID]["if"] = "success()"
    problems = audit_ci_gate(workflow)
    assert any("if: always()" in problem for problem in problems), problems


# ---------------------------------------------------------------------------
# Deployment and publication are deliberately outside the gate's graph.
# ---------------------------------------------------------------------------


def test_docs_deploy_and_ghcr_publication_are_not_gate_dependencies():
    gate_needs = set(load_workflow()["jobs"][GATE_JOB_ID]["needs"])
    docs_jobs = set(load_workflow(DOCS_WORKFLOW)["jobs"])
    release_jobs = set(load_workflow(RELEASE_WORKFLOW)["jobs"])

    assert "deploy" in docs_jobs
    assert "publish" in release_jobs
    assert gate_needs.isdisjoint(docs_jobs | release_jobs)
    assert not any("deploy" in job or "publish" in job for job in gate_needs)
