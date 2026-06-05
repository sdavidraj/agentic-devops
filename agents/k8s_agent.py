"""Kubernetes manifest review agent for the Agentic DevOps demo."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.config import kube_namespace, service_name
from agents.llm_client import ask_llm_json

DEPLOYMENT_PATH = Path("k8s/deployment.yaml")
SERVICE_PATH = Path("k8s/service.yaml")
REQUIRED_MANIFESTS = [DEPLOYMENT_PATH, SERVICE_PATH]


SYSTEM_PROMPT = """You are a Kubernetes release review agent.
Review the provided Deployment and Service YAML for a local minikube deployment.
If live cluster state is provided, compare desired state with what is already running and explain what the deployment will do next.
Keep findings concise and practical for a CLI demo.
Return only one valid JSON object with:
{
  "status": "pass" | "warn" | "fail",
  "findings": [{"check": string, "status": "pass" | "warn" | "fail", "message": string}],
  "recommendations": [string]
}
Use fail only for issues that should block deployment.
Length rules:
- findings: max 5 items, each message max 140 characters.
- recommendations: max 3 items, each max 140 characters."""


def expected_namespace(context: dict[str, Any]) -> str:
    plan = context.get("deployment_plan", {})
    return plan.get("namespace") or context.get("namespace") or kube_namespace()


def expected_replicas(context: dict[str, Any]) -> int:
    plan = context.get("deployment_plan", {})
    return int(plan.get("replicas") or 2)


def expected_service_name(context: dict[str, Any], deployment: dict[str, Any]) -> str:
    plan = context.get("deployment_plan", {})
    return (
        plan.get("service_name")
        or context.get("service_name")
        or deployment.get("metadata", {}).get("name")
        or service_name()
    )


def read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_yaml(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


def first_container(deployment: dict[str, Any]) -> dict[str, Any]:
    containers = (
        deployment.get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("containers", [])
    )
    return containers[0] if containers else {}


def label_selector(deployment: dict[str, Any]) -> str:
    match_labels = deployment.get("spec", {}).get("selector", {}).get("matchLabels", {})
    if not match_labels:
        return f"app={deployment.get('metadata', {}).get('name', service_name())}"
    return ",".join(f"{key}={value}" for key, value in sorted(match_labels.items()))


def kubectl_json(args: list[str], timeout: int = 4) -> tuple[dict[str, Any] | None, str]:
    try:
        completed = subprocess.run(
            ["kubectl", *args, "-o", "json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        return None, "kubectl not installed"
    except subprocess.TimeoutExpired:
        return None, "kubectl command timed out"

    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        return None, message or "kubectl command failed"

    try:
        return json.loads(completed.stdout), ""
    except json.JSONDecodeError:
        return None, "kubectl returned invalid JSON"


def pod_ready(pod: dict[str, Any]) -> bool:
    conditions = pod.get("status", {}).get("conditions", [])
    return any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in conditions
    )


def live_cluster_state(
    deployment: dict[str, Any],
    service: dict[str, Any],
    namespace: str,
    app_name: str,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "available": True,
        "namespace": namespace,
        "namespace_exists": False,
        "deployment": {"exists": False, "name": app_name},
        "service": {"exists": False, "name": app_name},
        "pods": {"count": 0, "ready": 0, "names": []},
        "note": "",
    }

    namespace_doc, error = kubectl_json(["get", "namespace", namespace])
    if error == "kubectl not installed" or error == "kubectl command timed out":
        state["available"] = False
        state["note"] = error
        return state
    if namespace_doc:
        state["namespace_exists"] = True
    else:
        state["note"] = f"Namespace {namespace} not found yet."
        return state

    deployment_doc, deployment_error = kubectl_json(
        ["get", "deployment", app_name, "-n", namespace]
    )
    if deployment_doc:
        container = first_container(deployment_doc)
        state["deployment"] = {
            "exists": True,
            "name": app_name,
            "replicas": deployment_doc.get("spec", {}).get("replicas", 0),
            "ready_replicas": deployment_doc.get("status", {}).get("readyReplicas", 0),
            "image": container.get("image"),
            "generation": deployment_doc.get("metadata", {}).get("generation"),
        }
    else:
        state["deployment"]["note"] = deployment_error or "Deployment not found."

    service_name_from_manifest = service.get("metadata", {}).get("name") or app_name
    service_doc, service_error = kubectl_json(
        ["get", "service", service_name_from_manifest, "-n", namespace]
    )
    if service_doc:
        state["service"] = {
            "exists": True,
            "name": service_name_from_manifest,
            "type": service_doc.get("spec", {}).get("type", "ClusterIP"),
            "ports": service_doc.get("spec", {}).get("ports", []),
        }
    else:
        state["service"]["note"] = service_error or "Service not found."

    pods_doc, pods_error = kubectl_json(
        ["get", "pods", "-n", namespace, "-l", label_selector(deployment)]
    )
    if pods_doc:
        pods = pods_doc.get("items", [])
        state["pods"] = {
            "count": len(pods),
            "ready": sum(1 for pod in pods if pod_ready(pod)),
            "names": [pod.get("metadata", {}).get("name") for pod in pods[:5]],
        }
    else:
        state["pods"]["note"] = pods_error or "Pods not found."

    return state


def desired_state(
    deployment: dict[str, Any],
    service: dict[str, Any],
    namespace: str,
    replicas: int,
    app_name: str,
) -> dict[str, Any]:
    container = first_container(deployment)
    service_port = (service.get("spec", {}).get("ports") or [{}])[0]
    return {
        "namespace": namespace,
        "deployment": app_name,
        "replicas": replicas,
        "image": container.get("image"),
        "image_pull_policy": container.get("imagePullPolicy"),
        "container_port": (container.get("ports") or [{}])[0].get("containerPort"),
        "service_port": service_port.get("port"),
        "target_port": service_port.get("targetPort"),
        "readiness": container.get("readinessProbe", {}).get("httpGet", {}).get("path"),
        "liveness": container.get("livenessProbe", {}).get("httpGet", {}).get("path"),
    }


def deployment_actions(live_state: dict[str, Any], desired: dict[str, Any]) -> list[str]:
    if not live_state.get("available"):
        return ["Live cluster not reachable; deploy agent will validate during deployment."]

    actions = []
    if not live_state.get("namespace_exists"):
        actions.append(f"Create namespace {desired['namespace']}.")
    else:
        actions.append(f"Reuse namespace {desired['namespace']}.")

    live_deployment = live_state.get("deployment", {})
    if not live_deployment.get("exists"):
        actions.append(f"Create deployment/{desired['deployment']} with {desired['replicas']} replicas.")
    else:
        live_replicas = live_deployment.get("replicas")
        live_ready = live_deployment.get("ready_replicas", 0)
        actions.append(
            f"Update deployment/{desired['deployment']} currently {live_ready}/{live_replicas} ready."
        )
        if live_replicas != desired["replicas"]:
            actions.append(f"Change replicas from {live_replicas} to {desired['replicas']}.")

    if live_state.get("service", {}).get("exists"):
        actions.append(f"Keep service port {desired['service_port']} -> {desired['target_port']}.")
    else:
        actions.append(f"Create service on port {desired['service_port']} -> {desired['target_port']}.")

    actions.append("Rebuild local image and restart rollout so existing pods pick it up.")
    return actions


def local_review(
    deployment: dict[str, Any],
    service: dict[str, Any],
    namespace: str,
    replicas: int,
) -> dict[str, Any]:
    container = first_container(deployment)
    resources = container.get("resources", {})

    checks = [
        (
            "namespace correctness",
            deployment.get("metadata", {}).get("namespace") == namespace
            and service.get("metadata", {}).get("namespace") == namespace,
            (
                "Deployment and Service should use namespace "
                f"{namespace}."
            ),
            "warn",
        ),
        (
            "replicas",
            deployment.get("spec", {}).get("replicas") == replicas,
            f"Deployment should run {replicas} replicas.",
            "fail",
        ),
        (
            "readiness probe",
            container.get("readinessProbe", {}).get("httpGet", {}).get("path") == "/health",
            "Container should define a readinessProbe on /health.",
            "fail",
        ),
        (
            "liveness probe",
            container.get("livenessProbe", {}).get("httpGet", {}).get("path") == "/health",
            "Container should define a livenessProbe on /health.",
            "fail",
        ),
        (
            "resource limits",
            bool(resources.get("requests")) and bool(resources.get("limits")),
            "Container should define CPU/memory requests and limits.",
            "fail",
        ),
        (
            "imagePullPolicy for local minikube",
            container.get("imagePullPolicy") == "Never",
            "Local minikube demo should use imagePullPolicy: Never.",
            "fail",
        ),
    ]

    findings = []
    recommendations = []
    worst = "pass"
    for check, passed, message, severity in checks:
        status = "pass" if passed else severity
        findings.append({"check": check, "status": status, "message": message})
        if not passed:
            recommendations.append(message)
            if severity == "fail":
                worst = "fail"
            elif worst != "fail":
                worst = "warn"

    return {
        "status": worst,
        "findings": findings,
        "recommendations": recommendations
        or ["Kubernetes Deployment and Service match the expected demo controls."],
    }


def ask_openai_review(
    deployment_yaml: str,
    service_yaml: str,
    namespace: str,
    replicas: int,
    live_state: dict[str, Any],
    planned_actions: list[str],
) -> dict[str, Any]:
    user_prompt = f"""Expected namespace: {namespace}
Expected replicas: {replicas}
Expected imagePullPolicy for local minikube: Never
Live cluster state:
```json
{json.dumps(live_state, indent=2)}
```

Planned deployment actions:
```json
{json.dumps(planned_actions, indent=2)}
```

Review these manifests for:
- namespace correctness
- replicas
- readiness probe
- liveness probe
- resource limits
- imagePullPolicy for local minikube

Deployment YAML:
```yaml
{deployment_yaml}
```

Service YAML:
```yaml
{service_yaml}
```"""
    return ask_llm_json(SYSTEM_PROMPT, user_prompt)


def normalize_review(review: dict[str, Any]) -> dict[str, Any]:
    status = review.get("status", "warn")
    if status not in {"pass", "warn", "fail"}:
        status = "warn"
    return {
        "status": status,
        "findings": (review.get("findings") or [])[:5],
        "recommendations": (review.get("recommendations") or [])[:3],
    }


def agent_status(review_status: str, fallback_used: bool) -> str:
    if review_status == "fail":
        return "failed"
    if review_status == "warn" or fallback_used:
        return "warning"
    return "passed"


def apply_safe_fixes(
    deployment: dict[str, Any],
    service: dict[str, Any],
    namespace: str,
    replicas: int,
) -> None:
    deployment.setdefault("metadata", {})["namespace"] = namespace
    service.setdefault("metadata", {})["namespace"] = namespace
    deployment.setdefault("spec", {})["replicas"] = replicas

    container = first_container(deployment)
    container["imagePullPolicy"] = "Never"
    container.setdefault("resources", {})
    container["resources"].setdefault("requests", {"cpu": "100m", "memory": "128Mi"})
    container["resources"].setdefault("limits", {"cpu": "500m", "memory": "256Mi"})
    container.setdefault("readinessProbe", {"httpGet": {"path": "/health", "port": 8080}})
    container.setdefault("livenessProbe", {"httpGet": {"path": "/health", "port": 8080}})

    write_yaml(DEPLOYMENT_PATH, deployment)
    write_yaml(SERVICE_PATH, service)


def run(context: dict[str, Any]) -> dict[str, Any]:
    if context.get("deployment_target") == "digitalocean-vm":
        return {
            "agent": "k8s",
            "status": "skipped",
            "review_status": "not_applicable",
            "summary": "Kubernetes review is not applicable for the DigitalOcean VM deployment.",
            "details": [
                "Deployment target: digitalocean-vm",
                "Runtime: Docker container on a DigitalOcean Droplet",
                "Kubernetes manifests are not applied by this deployment path.",
                "No live Kubernetes cluster state was inspected.",
            ],
            "recommendations": [
                "Use the Terraform, Security, Cost, VM Deploy, and SLO agents for this target."
            ],
            "live_state": {"available": False, "note": "not applicable for digitalocean-vm"},
            "planned_actions": [],
            "artifacts": [],
        }

    missing = [str(path) for path in REQUIRED_MANIFESTS if not path.exists()]
    if missing:
        return {
            "agent": "k8s",
            "status": "failed",
            "review_status": "fail",
            "summary": "Kubernetes review failed because required manifests are missing.",
            "details": missing,
        }

    deployment_yaml = DEPLOYMENT_PATH.read_text(encoding="utf-8")
    service_yaml = SERVICE_PATH.read_text(encoding="utf-8")
    deployment = yaml.safe_load(deployment_yaml)
    service = yaml.safe_load(service_yaml)
    namespace = expected_namespace(context)
    replicas = expected_replicas(context)
    app_name = expected_service_name(context, deployment)
    live_state = live_cluster_state(deployment, service, namespace, app_name)
    desired = desired_state(deployment, service, namespace, replicas, app_name)
    planned_actions = deployment_actions(live_state, desired)

    fallback_used = False
    try:
        review = normalize_review(
            ask_openai_review(
                deployment_yaml,
                service_yaml,
                namespace,
                replicas,
                live_state,
                planned_actions,
            )
        )
    except Exception as exc:
        fallback_used = True
        review = local_review(deployment, service, namespace, replicas)
        review["recommendations"].append(f"OpenAI review unavailable: {exc}")

    if context.get("apply_fixes"):
        apply_safe_fixes(deployment, service, namespace, replicas)
        review["recommendations"].append("Applied safe Kubernetes manifest fixes.")
    else:
        review["recommendations"].append(
            "No files modified. Re-run k8s_agent.py with --apply-fixes to apply safe fixes."
        )

    status = agent_status(review["status"], fallback_used)
    details = [
        f"Review status: {review['status']}",
        f"Expected namespace: {namespace}",
        f"Expected replicas: {replicas}",
        (
            "Live cluster: "
            + (
                "reachable"
                if live_state.get("available")
                else f"not inspected ({live_state.get('note')})"
            )
        ),
    ]
    if live_state.get("available"):
        if live_state.get("namespace_exists"):
            deployment_state = live_state.get("deployment", {})
            service_state = live_state.get("service", {})
            pods_state = live_state.get("pods", {})
            details.extend(
                [
                    (
                        "Running deployment: "
                        + (
                            f"{deployment_state.get('ready_replicas', 0)}/"
                            f"{deployment_state.get('replicas', 0)} ready, "
                            f"image {deployment_state.get('image')}"
                            if deployment_state.get("exists")
                            else "not found"
                        )
                    ),
                    (
                        "Running pods: "
                        f"{pods_state.get('ready', 0)}/{pods_state.get('count', 0)} ready"
                    ),
                    (
                        "Running service: "
                        + (
                            f"{service_state.get('type')} exposed on configured cluster port"
                            if service_state.get("exists")
                            else "not found"
                        )
                    ),
                ]
            )
        else:
            details.append(f"Running namespace: {namespace} not found")

    details.extend(f"Deployment action: {action}" for action in planned_actions[:5])
    for finding in review["findings"]:
        details.append(
            f"{finding.get('check', 'check')}: {finding.get('status', 'warn')} - "
            f"{finding.get('message', 'No message provided.')}"
        )
    for recommendation in review["recommendations"]:
        details.append(f"Recommendation: {recommendation}")

    return {
        "agent": "k8s",
        "status": status,
        "review_status": review["status"],
        "summary": "Reviewed Kubernetes manifests and compared them with live cluster state.",
        "details": details,
        "recommendations": review["recommendations"],
        "live_state": live_state,
        "planned_actions": planned_actions,
        "artifacts": [str(path) for path in REQUIRED_MANIFESTS],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review Kubernetes manifests.")
    parser.add_argument(
        "--apply-fixes",
        action="store_true",
        help="Apply safe deterministic fixes to deployment.yaml and service.yaml.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result = run({"apply_fixes": args.apply_fixes})
    print(f"{result['agent']}: {result['status']} - {result['summary']}")
    for detail in result["details"]:
        print(f"- {detail}")
