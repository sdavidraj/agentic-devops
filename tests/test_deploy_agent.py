"""Tests for the minikube deploy agent."""

from pathlib import Path

import yaml

from agents import deploy_agent


def write_manifest(path: Path, kind: str, name: str, namespace: str = "demo") -> None:
    manifest = {
        "apiVersion": "v1",
        "kind": kind,
        "metadata": {"name": name, "namespace": namespace},
    }
    if kind == "Namespace":
        manifest["metadata"].pop("namespace")
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")


def test_render_manifests_for_namespace_rewrites_namespaces(monkeypatch, tmp_path) -> None:
    k8s_dir = tmp_path / "k8s"
    k8s_dir.mkdir()
    write_manifest(k8s_dir / "namespace.yaml", "Namespace", "demo")
    write_manifest(k8s_dir / "deployment.yaml", "Deployment", "checkout-service")
    write_manifest(k8s_dir / "service.yaml", "Service", "checkout-service")
    write_manifest(k8s_dir / "hpa.yaml", "HorizontalPodAutoscaler", "checkout-service")
    monkeypatch.setattr(deploy_agent, "K8S_DIR", k8s_dir)

    rendered_path = deploy_agent.render_manifests_for_namespace("agentic-checkout")
    docs = list(yaml.safe_load_all(rendered_path.read_text(encoding="utf-8")))

    assert docs[0]["metadata"]["name"] == "agentic-checkout"
    assert docs[1]["metadata"]["namespace"] == "agentic-checkout"
    assert docs[2]["metadata"]["namespace"] == "agentic-checkout"
    assert docs[3]["metadata"]["namespace"] == "agentic-checkout"


def test_build_image_uses_app_context(monkeypatch) -> None:
    commands = []
    monkeypatch.setattr(deploy_agent, "run_command", lambda command: commands.append(command))

    deploy_agent.build_image()

    assert commands == [["minikube", "image", "build", "-t", "checkout-service:latest", "./app"]]


def test_ensure_minikube_running_starts_when_status_fails(monkeypatch) -> None:
    commands = []

    class Result:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    def fake_run(command, check=True):
        commands.append(command)
        return Result(1 if command == ["minikube", "status"] else 0)

    monkeypatch.setattr(deploy_agent, "run_command", fake_run)

    deploy_agent.ensure_minikube_running()

    assert commands == [["minikube", "status"], ["minikube", "start"]]


def test_restart_rollout_restarts_checkout_deployment(monkeypatch) -> None:
    commands = []
    monkeypatch.setattr(deploy_agent, "run_command", lambda command: commands.append(command))

    deploy_agent.restart_rollout("agentic-devops")

    assert commands == [
        [
            "kubectl",
            "rollout",
            "restart",
            "deployment/checkout-service",
            "-n",
            "agentic-devops",
        ]
    ]
