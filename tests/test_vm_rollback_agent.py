"""Tests for the DigitalOcean VM rollback agent."""

from agents import vm_rollback_agent


class Completed:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_vm_rollback_agent_only_touches_checkout_containers(monkeypatch) -> None:
    commands = []
    monkeypatch.delenv("VM_SSH_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("VM_SSH_KEY_PATH", raising=False)
    monkeypatch.setattr(vm_rollback_agent, "run_command", lambda command: commands.append(command) or Completed())

    result = vm_rollback_agent.run(
        {
            "vm_host": "203.0.113.10",
            "vm_user": "root",
            "vm_app_port": 8080,
            "previous_docker_image": "ghcr.io/acme/checkout-service:previous",
        }
    )

    assert result["status"] == "passed"
    remote_script = commands[0][-1]
    assert "checkout-service-previous" in remote_script
    assert "checkout-service" in remote_script
    assert "docker system prune" not in remote_script
    assert "docker rm -f" not in remote_script


def test_vm_rollback_agent_warns_when_previous_image_unavailable(monkeypatch) -> None:
    monkeypatch.delenv("DOCKER_IMAGE", raising=False)
    monkeypatch.delenv("GHCR_IMAGE", raising=False)
    monkeypatch.delenv("VM_SSH_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("VM_SSH_KEY_PATH", raising=False)
    monkeypatch.setattr(
        vm_rollback_agent,
        "run_command",
        lambda command: Completed(returncode=2, stderr="No previous checkout-service container or image found."),
    )

    result = vm_rollback_agent.run({"vm_host": "203.0.113.10"})

    assert result["status"] == "warning"
    assert "No unrelated containers were modified." in result["details"]
