"""Tests for the DigitalOcean VM deploy agent."""

from agents import vm_deploy_agent


class Completed:
    def __init__(self, returncode: int = 0, stdout: str = "true\n", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_vm_deploy_agent_builds_expected_ssh_docker_command(monkeypatch) -> None:
    commands = []
    monkeypatch.delenv("VM_SSH_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("VM_SSH_KEY_PATH", raising=False)
    monkeypatch.setattr(vm_deploy_agent, "run_command", lambda command: commands.append(command) or Completed())

    context = {
        "vm_host": "203.0.113.10",
        "vm_user": "root",
        "vm_app_port": 8080,
        "docker_image": "ghcr.io/acme/checkout-service:sha",
    }

    result = vm_deploy_agent.run(context)

    assert result["status"] == "passed"
    assert context["slo_base_url"] == "http://203.0.113.10:8080"
    assert commands[0][0] == "ssh"
    assert commands[0][-2] == "root@203.0.113.10"
    remote_script = commands[0][-1]
    assert "apt_update_with_retry" in remote_script
    assert "archive.ubuntu.com/ubuntu" in remote_script
    assert "command -v docker >/dev/null 2>&1" in remote_script
    assert "docker pull ghcr.io/acme/checkout-service:sha" in remote_script
    assert "docker rm -f checkout-service-previous" in remote_script
    assert "docker rename checkout-service checkout-service-previous" in remote_script
    assert "docker run -d --name checkout-service" in remote_script


def test_vm_deploy_agent_fails_when_vm_host_missing() -> None:
    result = vm_deploy_agent.run({"docker_image": "checkout-service:latest"})

    assert result["status"] == "failed"
    assert result["stop_pipeline"] is True
    assert any("VM_HOST" in detail for detail in result["details"])


def test_vm_deploy_agent_masks_short_secret() -> None:
    assert vm_deploy_agent.mask_secret("token") == "***"


def test_printable_command_masks_registry_token(monkeypatch) -> None:
    monkeypatch.setenv("GHCR_TOKEN", "super-secret-token")

    printed = vm_deploy_agent.printable_command(["ssh", "root@host", "echo super-secret-token"])

    assert "super-secret-token" not in printed
    assert "supe...oken" in printed
