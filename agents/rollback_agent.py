"""Rollback agent for the Agentic DevOps demo."""

from __future__ import annotations

import subprocess
from typing import Any

from agents.config import kube_namespace, service_name



def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a kubectl command and capture output for the agent report."""
    return subprocess.run(command, capture_output=True, text=True, check=False)


def command_output(completed: subprocess.CompletedProcess[str]) -> str:
    output = (completed.stdout + completed.stderr).strip()
    return output or "No command output captured."


def run(context: dict[str, Any]) -> dict[str, Any]:
    slo_result = context.get("agent_outputs", {}).get("slo", {})
    slo_status = slo_result.get("status")
    namespace = context.get("namespace") or kube_namespace()
    deployment_name = context.get("service_name") or service_name()

    if slo_status != "failed":
        print("\nRollback Agent")
        print("--------------")
        print("No rollback required")
        return {
            "agent": "rollback",
            "status": "skipped",
            "summary": "No rollback required.",
            "details": ["Rollback was skipped because SLO status was not failed."],
        }

    undo_command = [
        "kubectl",
        "rollout",
        "undo",
        f"deployment/{deployment_name}",
        "-n",
        namespace,
    ]
    status_command = [
        "kubectl",
        "rollout",
        "status",
        f"deployment/{deployment_name}",
        "-n",
        namespace,
        "--timeout=120s",
    ]

    print("\nRollback Agent")
    print("--------------")
    print(f"SLO failed. Running: {' '.join(undo_command)}")
    undo_result = run_command(undo_command)
    undo_output = command_output(undo_result)

    if undo_result.returncode != 0:
        print("Rollback command failed.")
        print(undo_output)
        return {
            "agent": "rollback",
            "status": "failed",
            "summary": "Rollback command failed.",
            "details": [
                f"Command: {' '.join(undo_command)}",
                f"Exit code: {undo_result.returncode}",
                undo_output,
            ],
        }

    print(f"Waiting for rollout status: {' '.join(status_command)}")
    status_result = run_command(status_command)
    status_output = command_output(status_result)

    if status_result.returncode != 0:
        print("Rollback started, but rollout status did not complete successfully.")
        print(status_output)
        return {
            "agent": "rollback",
            "status": "failed",
            "summary": "Rollback started, but rollout status failed.",
            "details": [
                f"Undo command: {' '.join(undo_command)}",
                undo_output,
                f"Status command: {' '.join(status_command)}",
                f"Exit code: {status_result.returncode}",
                status_output,
            ],
        }

    print("Rollback completed successfully.")
    return {
        "agent": "rollback",
        "status": "passed",
        "summary": "Rollback completed successfully.",
        "details": [
            f"Undo command: {' '.join(undo_command)}",
            undo_output,
            f"Status command: {' '.join(status_command)}",
            status_output,
        ],
    }
