"""Tests for the rollback agent."""

import subprocess

from agents import rollback_agent


def completed(command: list[str], returncode: int = 0, stdout: str = ""):
    return subprocess.CompletedProcess(
        args=command,
        returncode=returncode,
        stdout=stdout,
        stderr="",
    )


def test_rollback_skips_when_slo_passed(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(rollback_agent, "run_command", lambda command: calls.append(command))

    result = rollback_agent.run({"agent_outputs": {"slo": {"status": "passed"}}})

    assert result["status"] == "skipped"
    assert calls == []


def test_rollback_runs_undo_and_waits_for_rollout(monkeypatch) -> None:
    monkeypatch.setenv("KUBE_NAMESPACE", "agentic-checkout")
    calls = []

    def fake_run_command(command):
        calls.append(command)
        return completed(command, stdout="ok")

    monkeypatch.setattr(rollback_agent, "run_command", fake_run_command)

    result = rollback_agent.run({"agent_outputs": {"slo": {"status": "failed"}}})

    assert result["status"] == "passed"
    assert calls == [
        [
            "kubectl",
            "rollout",
            "undo",
            "deployment/checkout-service",
            "-n",
            "agentic-checkout",
        ],
        [
            "kubectl",
            "rollout",
            "status",
            "deployment/checkout-service",
            "-n",
            "agentic-checkout",
            "--timeout=120s",
        ],
    ]


def test_rollback_returns_failed_when_undo_fails(monkeypatch) -> None:
    def fake_run_command(command):
        return completed(command, returncode=1, stdout="undo failed")

    monkeypatch.setattr(rollback_agent, "run_command", fake_run_command)

    result = rollback_agent.run({"agent_outputs": {"slo": {"status": "failed"}}})

    assert result["status"] == "failed"
    assert result["summary"] == "Rollback command failed."
