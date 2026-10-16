"""A failed audit stays fatal without masking independent CI verification."""

from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"


def _steps():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return {step.get("id"): step for step in workflow["jobs"]["build"]["steps"] if step.get("id")}


def test_ci_node_matches_validated_supported_toolchain():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    node = next(step for step in workflow["jobs"]["build"]["steps"] if step.get("uses", "").startswith("actions/setup-node@"))
    assert node["with"]["node-version"] == "24.19.0"


@pytest.mark.parametrize("step_id", ["quality", "security", "frontend_types", "frontend_tests", "frontend_build", "browser_install"])
def test_independent_gates_run_after_audit_failure_only_when_installed(step_id):
    step = _steps()[step_id]
    assert step["if"] == "${{ !cancelled() && steps.python_deps.outcome == 'success' && steps.frontend_deps.outcome == 'success' }}"
    assert not step.get("continue-on-error", False)


def test_locked_python_audit_is_independent_of_frontend_and_security_failure():
    step = _steps()["python_audit"]
    assert step["if"] == "${{ !cancelled() && steps.python_deps.outcome == 'success' }}"
    assert step["run"] == ".venv/bin/pip-audit -r requirements.lock.txt"
    assert not step.get("continue-on-error", False)


def test_audit_failure_remains_fatal_and_unfiltered():
    step = _steps()["frontend_audit"]
    assert step["run"] == "npm audit --prefix frontend"
    assert not step.get("continue-on-error", False)
    steps = _steps()
    assert steps["frontend_deps"]["run"] == "npm ci --prefix frontend"
    assert "pip check" in steps["python_deps"]["run"]
    assert steps["quality"]["run"] == 'PATH="$PWD/.venv/bin:$PATH" make check'
    assert steps["security"]["run"] == 'PATH="$PWD/.venv/bin:$PATH" make security'


def test_frontend_gates_use_existing_commands_and_browser_install_guard():
    steps = _steps()
    for step_id, script in [("frontend_types", "typecheck"), ("frontend_tests", "test"), ("frontend_build", "build")]:
        assert steps[step_id]["run"] == f"npm run {script} --prefix frontend"
    assert steps["browser_install"]["working-directory"] == "frontend"
    assert steps["browser_install"]["run"] == "npx playwright install --with-deps chromium"
    e2e = steps["frontend_e2e"]
    assert e2e["if"] == (
        "${{ !cancelled() && steps.python_deps.outcome == 'success' && "
        "steps.frontend_deps.outcome == 'success' && steps.browser_install.outcome == 'success' }}"
    )
    assert e2e["run"] == "env -u NODE_ENV npm run e2e --prefix frontend"
    assert e2e["env"]["PW_PYTHON_PATH"] == "${{ github.workspace }}/.venv/bin/python"
    assert not e2e.get("continue-on-error", False)
