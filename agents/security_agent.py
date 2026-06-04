"""Security review agent for the Agentic DevOps demo."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any


CHECKOV_COMMAND = ["checkov", "-d", "infra/terraform"]
TRIVY_COMMAND = [
    "trivy",
    "fs",
    ".",
    "--severity",
    "CRITICAL,HIGH",
    "--exit-code",
    "1",
]


def tool_installed(tool_name: str) -> bool:
    return shutil.which(tool_name) is not None


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def command_output(completed: subprocess.CompletedProcess[str]) -> str:
    output = (completed.stdout + completed.stderr).strip()
    return output or "No scanner output captured."


def is_runtime_issue(output: str) -> bool:
    lowered = output.lower()
    runtime_markers = [
        "could not download",
        "download",
        "connection refused",
        "network",
        "database",
        "db error",
        "permission denied",
    ]
    return any(marker in lowered for marker in runtime_markers)


def concise_output(output: str, max_lines: int = 6) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return "No scanner output captured."
    return " | ".join(lines[:max_lines])


def run_scanner(name: str, command: list[str]) -> dict[str, Any]:
    if not tool_installed(command[0]):
        message = f"{name} tool not installed, skipping in demo mode"
        print(message)
        return {
            "name": name,
            "status": "warning",
            "summary": message,
            "details": [message],
        }

    print(f"Running {name}: {' '.join(command)}")
    completed = run_command(command)
    output = command_output(completed)

    if completed.returncode == 0:
        return {
            "name": name,
            "status": "passed",
            "summary": f"{name} completed with no critical issues.",
            "details": [concise_output(output)],
        }

    if is_runtime_issue(output):
        return {
            "name": name,
            "status": "warning",
            "summary": f"{name} could not complete cleanly in demo mode.",
            "details": [
                f"Command: {' '.join(command)}",
                f"Exit code: {completed.returncode}",
                concise_output(output),
            ],
        }

    return {
        "name": name,
        "status": "failed",
        "summary": f"{name} reported severe security issues.",
        "details": [
            f"Command: {' '.join(command)}",
            f"Exit code: {completed.returncode}",
            concise_output(output),
        ],
    }


def overall_status(scanner_results: list[dict[str, Any]]) -> str:
    statuses = [result["status"] for result in scanner_results]
    if "failed" in statuses:
        return "failed"
    if "warning" in statuses:
        return "warning"
    return "passed"


def run(context: dict[str, Any]) -> dict[str, Any]:
    scanner_results = [
        run_scanner("Checkov", CHECKOV_COMMAND),
        run_scanner("Trivy", TRIVY_COMMAND),
    ]
    status = overall_status(scanner_results)

    details: list[str] = []
    for result in scanner_results:
        details.append(f"{result['name']}: {result['summary']}")
        details.extend(result["details"])

    return {
        "agent": "security",
        "status": status,
        "summary": f"Security scan completed with status: {status}.",
        "details": details,
    }
