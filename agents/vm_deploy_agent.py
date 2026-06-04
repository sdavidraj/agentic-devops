"""DigitalOcean VM deploy agent for the Agentic DevOps demo."""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agents.config import docker_image, service_name, vm_app_port, vm_host, vm_user

APP_CONTAINER = "checkout-service"
PREVIOUS_CONTAINER = "checkout-service-previous"


def mask_secret(value: str) -> str:
    if not value:
        return value
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def ssh_key_path_from_env() -> tuple[str | None, Path | None]:
    load_dotenv()
    key_path = os.getenv("VM_SSH_KEY_PATH")
    if key_path:
        return key_path, None

    private_key = os.getenv("VM_SSH_PRIVATE_KEY")
    if not private_key:
        return None, None

    temp = tempfile.NamedTemporaryFile(
        mode="w",
        prefix="agentic-devops-vm-key-",
        delete=False,
        encoding="utf-8",
    )
    with temp:
        temp.write(private_key)
        if not private_key.endswith("\n"):
            temp.write("\n")
    path = Path(temp.name)
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return str(path), path


def ssh_command(host: str, user: str, remote_command: str, key_path: str | None = None) -> list[str]:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if key_path:
        command.extend(["-i", key_path])
    command.append(f"{user}@{host}")
    command.append(remote_command)
    return command


def printable_command(command: list[str]) -> str:
    text = " ".join(shlex.quote(part) for part in command)
    for secret_name in ["GHCR_TOKEN", "VM_SSH_PRIVATE_KEY", "DIGITALOCEAN_TOKEN"]:
        secret = os.getenv(secret_name)
        if secret:
            text = text.replace(secret, mask_secret(secret))
    return text


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    print(f"$ {printable_command(command)}")
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.stdout.strip():
        print(completed.stdout.strip())
    if completed.stderr.strip():
        print(completed.stderr.strip())
    return completed


def remote_docker_login_command() -> str | None:
    username = os.getenv("GHCR_USERNAME")
    token = os.getenv("GHCR_TOKEN")
    if not username or not token:
        return None
    return (
        "printf %s "
        f"{shlex.quote(token)} | docker login ghcr.io "
        f"-u {shlex.quote(username)} --password-stdin"
    )


def remote_deploy_script(image: str, app_port: int) -> str:
    commands = [
        "set -euo pipefail",
        "if ! command -v docker >/dev/null 2>&1; then "
        "apt-get update && apt-get install -y docker.io && systemctl enable --now docker; "
        "fi",
    ]
    login = remote_docker_login_command()
    if login:
        commands.append(login)
    commands.extend(
        [
            f"docker pull {shlex.quote(image)}",
            (
                f"previous_image=$(docker inspect -f '{{{{.Config.Image}}}}' {APP_CONTAINER} "
                "2>/dev/null || true)"
            ),
            "printf '%s' \"$previous_image\" > /tmp/checkout-service-previous-image",
            f"docker rm -f {PREVIOUS_CONTAINER} >/dev/null 2>&1 || true",
            (
                f"if docker inspect {APP_CONTAINER} >/dev/null 2>&1; then "
                f"docker stop {APP_CONTAINER} >/dev/null 2>&1 || true; "
                f"docker rename {APP_CONTAINER} {PREVIOUS_CONTAINER}; "
                "fi"
            ),
            (
                f"docker run -d --name {APP_CONTAINER} --restart unless-stopped "
                f"-p {app_port}:8080 {shlex.quote(image)}"
            ),
            f"docker inspect -f '{{{{.State.Running}}}}' {APP_CONTAINER}",
        ]
    )
    return " && ".join(commands)


def resolve_config(context: dict[str, Any]) -> dict[str, Any]:
    host = str(context.get("vm_host") or vm_host()).strip()
    user = str(context.get("vm_user") or vm_user()).strip()
    image = str(context.get("docker_image") or docker_image()).strip()
    app_port = int(context.get("vm_app_port") or vm_app_port())

    if not host:
        raise ValueError("VM_HOST is required for digitalocean-vm deployment.")
    if not image:
        raise ValueError("DOCKER_IMAGE or GHCR_IMAGE is required for VM deployment.")

    return {"host": host, "user": user, "image": image, "app_port": app_port}


def run(context: dict[str, Any]) -> dict[str, Any]:
    temp_key: Path | None = None
    try:
        config = resolve_config(context)
        key_path, temp_key = ssh_key_path_from_env()
        script = remote_deploy_script(config["image"], config["app_port"])
        command = ssh_command(config["host"], config["user"], script, key_path)
        completed = run_command(command)

        context["vm_host"] = config["host"]
        context["vm_user"] = config["user"]
        context["vm_app_port"] = config["app_port"]
        context["docker_image"] = config["image"]
        context["slo_base_url"] = f"http://{config['host']}:{config['app_port']}"

        if completed.returncode != 0:
            return {
                "agent": "deploy",
                "status": "failed",
                "summary": "DigitalOcean VM deployment failed.",
                "details": [
                    "Deployment target: digitalocean-vm",
                    "Deploy mechanism: GitHub Actions + SSH + Docker",
                    f"VM: {config['user']}@{config['host']}",
                    f"Image: {config['image']}",
                    f"Exit code: {completed.returncode}",
                    "Rollback mechanism: Docker container/image restore",
                ],
                "stop_pipeline": True,
            }

        return {
            "agent": "deploy",
            "status": "passed",
            "summary": "Deployed checkout-service to DigitalOcean VM with Docker.",
            "details": [
                "Deployment target: digitalocean-vm",
                "Deploy mechanism: GitHub Actions + SSH + Docker",
                f"VM: {config['user']}@{config['host']}",
                f"Image: {config['image']}",
                f"Container: {APP_CONTAINER}",
                f"Port mapping: {config['app_port']} -> 8080",
                f"SLO endpoint: http://{config['host']}:{config['app_port']}/checkout",
                "Rollback mechanism: Docker container/image restore",
            ],
        }
    except Exception as exc:
        return {
            "agent": "deploy",
            "status": "failed",
            "summary": "DigitalOcean VM deployment failed.",
            "details": [
                str(exc),
                "Check: VM_HOST",
                "Check: VM_SSH_PRIVATE_KEY or VM_SSH_KEY_PATH",
                "Check: DOCKER_IMAGE or GHCR_IMAGE",
            ],
            "stop_pipeline": True,
        }
    finally:
        if temp_key:
            temp_key.unlink(missing_ok=True)
