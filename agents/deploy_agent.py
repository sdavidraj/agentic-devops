"""Deployment agent for the local minikube checkout-service demo."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from agents.config import DEFAULT_KUBE_NAMESPACE, kube_namespace, local_port, service_name

K8S_DIR = Path("k8s")


def run_command(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print(f"\n$ {' '.join(command)}")
    completed = subprocess.run(command, capture_output=True, text=True, check=False)

    if completed.stdout.strip():
        print(completed.stdout.strip())
    if completed.stderr.strip():
        print(completed.stderr.strip())

    if check and completed.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}: {' '.join(command)}"
        )

    return completed


def namespace() -> str:
    load_dotenv()
    return kube_namespace(DEFAULT_KUBE_NAMESPACE)


def deployment_name() -> str:
    return service_name()


def image_name() -> str:
    return f"{service_name()}:latest"


def print_minikube_docker_env_reminder() -> None:
    print("\nMinikube image strategy")
    print("-----------------------")
    print("Using 'minikube image build' so no manual docker-env step is required.")


def ensure_minikube_running() -> None:
    result = run_command(["minikube", "status"], check=False)
    if result.returncode == 0:
        print("Minikube is running.")
        return

    print("Minikube is not running. Starting minikube...")
    run_command(["minikube", "start"])


def ensure_namespace(kube_namespace: str) -> None:
    result = run_command(
        ["kubectl", "get", "namespace", kube_namespace],
        check=False,
    )
    if result.returncode == 0:
        print(f"Namespace '{kube_namespace}' already exists.")
        return

    print(f"Creating namespace '{kube_namespace}'...")
    run_command(["kubectl", "create", "namespace", kube_namespace])


def namespaced_manifest(kind: str) -> bool:
    return kind in {
        "Deployment",
        "Service",
        "HorizontalPodAutoscaler",
        "ConfigMap",
        "Secret",
        "Ingress",
        "ServiceAccount",
        "Role",
        "RoleBinding",
    }


def load_manifest_docs(path: Path) -> list[dict[str, Any]]:
    docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    return [doc for doc in docs if doc]


def manifest_paths() -> list[Path]:
    return [
        K8S_DIR / "namespace.yaml",
        K8S_DIR / "deployment.yaml",
        K8S_DIR / "service.yaml",
        K8S_DIR / "hpa.yaml",
    ]


def render_manifests_for_namespace(kube_namespace: str) -> Path:
    rendered_docs: list[dict[str, Any]] = []

    for path in manifest_paths():
        if not path.exists():
            raise FileNotFoundError(f"Missing Kubernetes manifest: {path}")

        for doc in load_manifest_docs(path):
            metadata = doc.setdefault("metadata", {})
            kind = doc.get("kind")
            if kind == "Namespace":
                metadata["name"] = kube_namespace
            elif namespaced_manifest(kind):
                metadata["namespace"] = kube_namespace
            rendered_docs.append(doc)

    rendered = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".yaml",
        prefix=f"{kube_namespace}-",
        delete=False,
        encoding="utf-8",
    )
    with rendered:
        yaml.safe_dump_all(rendered_docs, rendered, sort_keys=False)

    return Path(rendered.name)


def build_image() -> None:
    run_command(["minikube", "image", "build", "-t", image_name(), "./app"])


def apply_manifests(kube_namespace: str) -> None:
    rendered_path = render_manifests_for_namespace(kube_namespace)
    print(f"Applying rendered manifests for namespace '{kube_namespace}'.")
    print(f"Rendered manifest: {rendered_path}")
    run_command(["kubectl", "apply", "-f", str(rendered_path)])


def wait_for_rollout(kube_namespace: str) -> None:
    run_command(
        [
            "kubectl",
            "rollout",
            "status",
            f"deployment/{deployment_name()}",
            "-n",
            kube_namespace,
            "--timeout=120s",
        ]
    )


def restart_rollout(kube_namespace: str) -> None:
    run_command(
        [
            "kubectl",
            "rollout",
            "restart",
            f"deployment/{deployment_name()}",
            "-n",
            kube_namespace,
        ]
    )


def start_port_forward(kube_namespace: str) -> None:
    print("\nStarting port-forward. Press Ctrl+C to stop.")
    run_command(
        [
            "kubectl",
            "port-forward",
            f"deployment/{service_name()}",
            f"{local_port()}:8080",
            "-n",
            kube_namespace,
        ]
    )


def main() -> int:
    kube_namespace = namespace()

    try:
        print(f"Deploying {deployment_name()} to namespace '{kube_namespace}'.")
        print_minikube_docker_env_reminder()
        ensure_minikube_running()
        ensure_namespace(kube_namespace)
        build_image()
        apply_manifests(kube_namespace)
        restart_rollout(kube_namespace)
        wait_for_rollout(kube_namespace)
        start_port_forward(kube_namespace)
    except KeyboardInterrupt:
        print("\nPort-forward stopped.")
        return 0
    except Exception as exc:
        print(f"\nDeployment failed: {exc}", file=sys.stderr)
        print("\nHelpful checks:", file=sys.stderr)
        print("  kubectl config current-context", file=sys.stderr)
        print(f"  kubectl get pods -n {kube_namespace}", file=sys.stderr)
        print("  eval $(minikube docker-env)", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
