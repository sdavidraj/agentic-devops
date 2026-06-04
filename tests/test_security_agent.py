"""Tests for the security agent."""

import subprocess

from agents import security_agent


def completed(command: list[str], returncode: int = 0, stdout: str = ""):
    return subprocess.CompletedProcess(
        args=command,
        returncode=returncode,
        stdout=stdout,
        stderr="",
    )


def test_security_agent_warns_when_tools_are_missing(monkeypatch) -> None:
    monkeypatch.setattr(security_agent, "tool_installed", lambda tool_name: False)

    result = security_agent.run({})

    assert result["status"] == "warning"
    assert "tool not installed, skipping in demo mode" in " ".join(result["details"])


def test_security_agent_passes_when_scanners_pass(monkeypatch) -> None:
    monkeypatch.setattr(security_agent, "tool_installed", lambda tool_name: True)
    monkeypatch.setattr(
        security_agent,
        "run_command",
        lambda command: completed(command, stdout="no issues"),
    )

    result = security_agent.run({})

    assert result["status"] == "passed"


def test_security_agent_fails_when_scanner_reports_severe_issue(monkeypatch) -> None:
    monkeypatch.setattr(security_agent, "tool_installed", lambda tool_name: True)
    monkeypatch.setattr(
        security_agent,
        "run_command",
        lambda command: completed(command, returncode=1, stdout="CRITICAL vulnerability found"),
    )

    result = security_agent.run({})

    assert result["status"] == "failed"


def test_security_agent_warns_when_scanner_has_runtime_issue(monkeypatch) -> None:
    monkeypatch.setattr(security_agent, "tool_installed", lambda tool_name: True)
    monkeypatch.setattr(
        security_agent,
        "run_command",
        lambda command: completed(command, returncode=1, stdout="DB error: could not download"),
    )

    result = security_agent.run({})

    assert result["status"] == "warning"
