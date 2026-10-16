"""Release input must remain data; notification failure must not persist credentials."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import requests
import yaml

from observability.webhooks import WebhookManager

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_rejects_shell_payload_before_side_effect(tmp_path):
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    step = next(s for s in workflow["jobs"]["validate"]["steps"] if s.get("id") == "version")
    marker = tmp_path / "injected"
    payload = f"$(touch {marker})"
    values = {"github.event_name": "workflow_dispatch", "inputs.version": payload}

    def expand(value):
        for key, replacement in values.items():
            value = value.replace("${{ " + key + " }}", replacement)
        return value

    output = tmp_path / "outputs"
    env = {**os.environ, "GITHUB_OUTPUT": str(output), "GITHUB_REF": "refs/tags/v1.0.0"}
    env.update({k: expand(v) for k, v in step.get("env", {}).items()})
    result = subprocess.run(["bash", "-c", expand(step["run"])], env=env, capture_output=True)
    assert not marker.exists(), "version was executed as shell syntax"
    assert result.returncode != 0
    assert not output.exists() or output.read_text() == ""


@pytest.mark.parametrize("provider", ["discord", "telegram"])
def test_webhook_failure_persists_only_safe_metadata(tmp_path, monkeypatch, caplog, provider):
    from observability import webhooks

    monkeypatch.setenv("READYTRADER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.invalid/SECRET_DISCORD")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "SECRET_TELEGRAM")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "PRIVATE_CHAT")
    monkeypatch.setattr(webhooks.time, "sleep", lambda _: None)

    def failed_post(url, **kwargs):
        raise requests.ConnectionError(f"failed {url}: PRIVATE_MESSAGE")

    monkeypatch.setattr(webhooks.requests, "post", failed_post)
    getattr(WebhookManager, f"send_{provider}_notification")("PRIVATE_MESSAGE")
    path = tmp_path / "webhook_dead_letter.jsonl"
    assert path.exists()
    record = json.loads(path.read_text())
    assert record["provider"] == provider
    assert record["error_class"] == "ConnectionError"
    assert record["correlation_id"]
    assert path.stat().st_mode & 0o777 == 0o600
    for secret in ("SECRET_DISCORD", "SECRET_TELEGRAM", "PRIVATE_CHAT", "PRIVATE_MESSAGE"):
        assert secret not in path.read_text() + caplog.text


def test_observability_requires_secret_and_only_publishes_loopback():
    config = yaml.safe_load((ROOT / "deploy/observability/docker-compose.yml").read_text())
    grafana = config["services"]["grafana"]
    serialized = json.dumps(grafana)
    assert "admin/admin" not in serialized
    assert "GF_SECURITY_ADMIN_PASSWORD__FILE" in serialized
    assert "GRAFANA_ADMIN_PASSWORD_FILE:?" in config["secrets"]["grafana_admin_password"]["file"]
    for service in config["services"].values():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:")


def test_frontend_context_excludes_local_secrets_and_build_artifacts():
    patterns = set((ROOT / "frontend/.dockerignore").read_text().splitlines())
    required = {
        ".env*",
        "**/.env*",
        "*.key",
        "**/*.key",
        "*.pem",
        "**/*.pem",
        ".npmrc",
        "**/.npmrc",
        "secrets",
        "node_modules",
        ".next",
        ".git",
        "playwright-report",
        "test-results",
    }
    assert required <= patterns
