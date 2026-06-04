"""DigitalOcean VM rollback agent for the Agentic DevOps demo."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

from agents.config import vm_app_port, vm_host, vm_user
from agents.vm_deploy_agent import (
    APP_CONTAINER,
    PREVIOUS_CONTAINER,
    printable_command,
    ssh_command,
    ssh_key_path_from_env,
)


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    print(f"$ {printable_command(command)}")
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.stdout.strip():
        print(completed.stdout.strip())
    if completed.stderr.strip():
        print(completed.stderr.strip())
    return completed


def rollback_script(previous_image: str, app_port: int) -> str:
    commands = [
        "set -euo pipefail",
        f"docker stop {APP_CONTAINER} >/dev/null 2>&1 || true",
        f"docker rm {APP_CONTAINER} >/dev/null 2>&1 || true",
        (
            f"if docker inspect {PREVIOUS_CONTAINER} >/dev/null 2>&1; then "
            f"docker rename {PREVIOUS_CONTAINER} {APP_CONTAINER}; "
            f"docker start {APP_CONTAINER}; "
            "exit 0; "
            "fi"
        ),
    ]
    if previous_image:
        commands.extend(
            [
                f"docker pull {shlex.quote(previous_image)}",
                (
                    f"docker run -d --name {APP_CONTAINER} --restart unless-stopped "
                    f"-p {app_port}:8080 {shlex.quote(previous_image)}"
                ),
            ]
        )
    else:
        commands.append("echo 'No previous checkout-service container or image found.' && exit 2")
    return " && ".join(commands)


def resolve_config(context: dict[str, Any]) -> dict[str, Any]:
    host = str(context.get("vm_host") or vm_host()).strip()
    user = str(context.get("vm_user") or vm_user()).strip()
    app_port = int(context.get("vm_app_port") or vm_app_port())
    previous_image = str(
        context.get("previous_docker_image")
        or context.get("docker_image_previous")
        or ""
    ).strip()

    if not host:
        raise ValueError("VM_HOST is required for digitalocean-vm rollback.")

    return {
        "host": host,
        "user": user,
        "app_port": app_port,
        "previous_image": previous_image,
    }


def run(context: dict[str, Any]) -> dict[str, Any]:
    temp_key: Path | None = None
    try:
        config = resolve_config(context)
        key_path, temp_key = ssh_key_path_from_env()
        command = ssh_command(
            config["host"],
            config["user"],
            rollback_script(config["previous_image"], config["app_port"]),
            key_path,
        )
        completed = run_command(command)

        if completed.returncode == 0:
            return {
                "agent": "rollback",
                "status": "passed",
                "summary": "Rolled back checkout-service on the DigitalOcean VM.",
                "details": [
                    "Deployment target: digitalocean-vm",
                    "Rollback mechanism: Docker container/image restore",
                    f"VM: {config['user']}@{config['host']}",
                    f"Container restored: {APP_CONTAINER}",
                ],
            }

        return {
            "agent": "rollback",
            "status": "warning",
            "summary": "DigitalOcean VM rollback could not restore a previous checkout-service container.",
            "details": [
                "Deployment target: digitalocean-vm",
                "Rollback mechanism: Docker container/image restore",
                f"VM: {config['user']}@{config['host']}",
                f"Exit code: {completed.returncode}",
                "No unrelated containers were modified.",
            ],
        }
    except Exception as exc:
        return {
            "agent": "rollback",
            "status": "failed",
            "summary": "DigitalOcean VM rollback failed.",
            "details": [
                str(exc),
                "Check: VM_HOST",
                "Check: VM_SSH_PRIVATE_KEY or VM_SSH_KEY_PATH",
            ],
        }
    finally:
        if temp_key:
            temp_key.unlink(missing_ok=True)
