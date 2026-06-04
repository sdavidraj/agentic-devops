"""LLM-backed planner agent for the Agentic DevOps demo."""

from __future__ import annotations

import json
import textwrap
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from agents.config import deployment_target, kube_namespace, local_port, service_name
from agents.llm_client import ask_llm_json

SAFE_DEFAULT_PLAN: dict[str, Any] = {
    "service_name": "checkout-service",
    "namespace": "agentic-devops",
    "deployment_target": "minikube",
    "local_port": 8080,
    "replicas": 2,
    "deployment_strategy": "rolling",
    "image": "checkout-service:latest",
    "slo": {
        "max_error_rate": 0.01,
        "max_avg_latency_ms": 500,
    },
    "checks": [
        "unit_tests",
        "kubernetes_manifest_review",
        "security_scan",
        "slo_validation",
        "release_notes",
        "rollback_if_failed",
    ],
    "execution_plan": [
        "Review repository configuration and manifests.",
        "Build the local Docker image for minikube.",
        "Deploy Kubernetes manifests to the configured namespace.",
        "Validate rollout, service health, and SLOs.",
        "Generate release notes and roll back if SLO validation fails.",
    ],
    "assumptions": [
        "Local minikube uses imagePullPolicy: Never for locally built images.",
        "The checkout service is exposed through local port-forwarding.",
    ],
    "risks": [
        "OpenAI, scanner, or metrics tooling may be unavailable in demo mode.",
    ],
    "environment_fit": "Local minikube demo using a locally built Docker image and port-forwarded service access.",
    "repo_observations": [
        "Kubernetes manifests define the checkout service deployment, service, and HPA.",
        "Terraform is optional for the local minikube target.",
    ],
}

SYSTEM_PROMPT = """You are a senior DevOps planning agent.

Create a deployment plan from the repository context, not from a fixed template.
Treat the repository context as the source of truth. Reflect the configured deployment target, namespace, service name, local port, Kubernetes manifests, resource settings, probes, autoscaling, Docker image settings, and Terraform file availability.
Do not simply repeat a generic plan. Include observations that are specific to the repository evidence.
Keep the output concise for a command-line executive demo.

For minikube:
- Prefer local Docker image build and imagePullPolicy: Never.
- Do not require cloud Terraform.
- Include SLO, testing, manifest review, release notes, and rollback checks.
- Explain why local cost/IaC behavior differs from cloud deployment.

For cloud targets:
- Include IaC review and cloud-specific validation.
- Mention whether the repository appears ready for GKE or VM deployment.
For digitalocean-vm:
- Include Terraform Droplet/firewall review, Docker image build/push, SSH deployment, public SLO validation, and Docker rollback.

Return only JSON with:
{
  "service_name": string,
  "namespace": string,
  "deployment_target": "minikube" | "gke" | "vm" | "digitalocean-vm",
  "local_port": number,
  "replicas": number,
  "deployment_strategy": string,
  "image": string,
  "slo": {"max_error_rate": number, "max_avg_latency_ms": number},
  "checks": [string],
  "execution_plan": [string],
  "assumptions": [string],
  "risks": [string],
  "environment_fit": string,
  "repo_observations": [string]
}

Length rules:
- environment_fit: one sentence, max 140 characters.
- repo_observations: max 3 items, each max 120 characters.
- execution_plan: max 4 items, each max 120 characters.
- risks: max 2 items, each max 120 characters.
- assumptions: max 2 items, each max 120 characters."""


def concise(value: Any, width: int = 120) -> str:
    text = " ".join(str(value).split())
    return textwrap.shorten(text, width=width, placeholder="...")


def concise_list(values: list[Any], limit: int, width: int = 120) -> list[str]:
    return [concise(value, width) for value in values[:limit]]


def safe_read(path: Path, max_chars: int = 4000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")[:max_chars]


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def first_container(deployment: dict[str, Any]) -> dict[str, Any]:
    containers = (
        deployment.get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("containers", [])
    )
    return containers[0] if containers else {}


def repo_context(intent: str) -> dict[str, Any]:
    deployment = load_yaml(Path("k8s/deployment.yaml"))
    service = load_yaml(Path("k8s/service.yaml"))
    hpa = load_yaml(Path("k8s/hpa.yaml"))
    container = first_container(deployment)
    terraform_files = sorted(str(path) for path in Path("infra/terraform").glob("*.tf"))

    return {
        "intent": intent,
        "env": {
            "KUBE_NAMESPACE": kube_namespace(),
            "SERVICE_NAME": service_name(),
            "LOCAL_PORT": local_port(),
            "DEPLOYMENT_TARGET": deployment_target(),
        },
        "app": {
            "main_py_present": Path("app/main.py").exists(),
            "requirements": safe_read(Path("app/requirements.txt"), max_chars=1000),
            "dockerfile_present": Path("app/Dockerfile").exists(),
            "known_endpoints": ["/", "/health", "/checkout", "/checkout-commons"],
            "failure_mode_env": "FAIL_MODE",
        },
        "kubernetes": {
            "deployment_name": deployment.get("metadata", {}).get("name"),
            "deployment_namespace": deployment.get("metadata", {}).get("namespace"),
            "replicas": deployment.get("spec", {}).get("replicas"),
            "image": container.get("image"),
            "image_pull_policy": container.get("imagePullPolicy"),
            "container_port": (
                container.get("ports", [{}])[0].get("containerPort")
                if container.get("ports")
                else None
            ),
            "resources": container.get("resources"),
            "readiness_probe": container.get("readinessProbe"),
            "liveness_probe": container.get("livenessProbe"),
            "service_name": service.get("metadata", {}).get("name"),
            "service_namespace": service.get("metadata", {}).get("namespace"),
            "service_ports": service.get("spec", {}).get("ports"),
            "hpa_min_replicas": hpa.get("spec", {}).get("minReplicas"),
            "hpa_max_replicas": hpa.get("spec", {}).get("maxReplicas"),
            "hpa_metrics": hpa.get("spec", {}).get("metrics"),
        },
        "terraform": {
            "files": terraform_files,
            "applicable_for_target": deployment_target() != "minikube",
        },
    }


def safe_default_plan() -> dict[str, Any]:
    plan = deepcopy(SAFE_DEFAULT_PLAN)
    plan["service_name"] = service_name()
    plan["namespace"] = kube_namespace()
    plan["deployment_target"] = deployment_target()
    plan["local_port"] = local_port()
    plan["image"] = f"{service_name()}:latest"
    if plan["deployment_target"] == "digitalocean-vm":
        plan["deployment_strategy"] = "docker container replacement with rollback"
        plan["checks"] = [
            "agent_generated_api_tests",
            "digitalocean_terraform_review",
            "security_scan",
            "public_slo_validation",
            "release_notes",
            "docker_rollback_if_failed",
        ]
        plan["execution_plan"] = [
            "Review DigitalOcean Droplet and firewall Terraform.",
            "Build and push the checkout-service Docker image.",
            "Deploy the image to the VM over SSH and Docker.",
            "Validate public SLOs and restore the previous container if needed.",
        ]
        plan["assumptions"] = [
            "GitHub Actions provides DigitalOcean, SSH, registry, and OpenAI secrets.",
            "The VM exposes port 8080 for checkout-service SLO validation.",
        ]
        plan["risks"] = [
            "Private registry pulls require VM docker login credentials.",
            "Firewall or DNS/network restrictions can block public SLO validation.",
        ]
        plan["environment_fit"] = (
            "GitHub Actions deploys a Docker image to a DigitalOcean VM over SSH."
        )
        plan["repo_observations"] = [
            "DigitalOcean Terraform defines the VM and firewall for the cloud demo.",
            "The app Dockerfile can run checkout-service on container port 8080.",
            "SLO validation can target the VM public endpoint instead of localhost.",
        ]
    return plan


def has_required_llm_fields(plan: dict[str, Any]) -> bool:
    required = {
        "service_name",
        "namespace",
        "deployment_target",
        "replicas",
        "deployment_strategy",
        "slo",
        "checks",
    }
    return required.issubset(plan.keys())


def normalize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict) or not has_required_llm_fields(plan):
        raise ValueError("OpenAI returned a deployment plan with missing required fields.")

    defaults = safe_default_plan()
    normalized = deepcopy(defaults)
    for key, value in plan.items():
        if value not in (None, "", []):
            normalized[key] = value

    normalized["service_name"] = str(normalized.get("service_name") or service_name())
    normalized["namespace"] = str(normalized.get("namespace") or kube_namespace())
    normalized["deployment_target"] = str(
        normalized.get("deployment_target") or deployment_target()
    ).lower()
    normalized["local_port"] = int(normalized.get("local_port") or local_port())
    normalized["replicas"] = int(normalized.get("replicas") or defaults["replicas"])
    normalized["image"] = str(normalized.get("image") or f"{service_name()}:latest")

    if not isinstance(normalized.get("slo"), dict):
        normalized["slo"] = defaults["slo"]
    normalized["slo"]["max_error_rate"] = float(
        normalized["slo"].get("max_error_rate", defaults["slo"]["max_error_rate"])
    )
    normalized["slo"]["max_avg_latency_ms"] = int(
        normalized["slo"].get("max_avg_latency_ms", defaults["slo"]["max_avg_latency_ms"])
    )

    if not normalized.get("deployment_strategy"):
        normalized["deployment_strategy"] = defaults["deployment_strategy"]

    if not isinstance(normalized.get("environment_fit"), str) or not normalized[
        "environment_fit"
    ].strip():
        normalized["environment_fit"] = defaults["environment_fit"]

    for list_key in [
        "checks",
        "execution_plan",
        "assumptions",
        "risks",
        "repo_observations",
    ]:
        if not isinstance(normalized.get(list_key), list) or not normalized[list_key]:
            normalized[list_key] = defaults[list_key]
        normalized[list_key] = [str(item) for item in normalized[list_key]]

    return normalized


def valid_plan(plan: dict[str, Any]) -> bool:
    return (
        isinstance(plan.get("service_name"), str)
        and isinstance(plan.get("namespace"), str)
        and plan.get("deployment_target") in {"minikube", "gke", "vm", "digitalocean-vm"}
        and isinstance(plan.get("replicas"), int)
        and plan["replicas"] >= 1
        and isinstance(plan.get("slo"), dict)
        and "max_error_rate" in plan["slo"]
        and "max_avg_latency_ms" in plan["slo"]
        and isinstance(plan.get("checks"), list)
        and bool(plan["checks"])
        and isinstance(plan.get("repo_observations"), list)
        and bool(plan["repo_observations"])
    )


def build_user_prompt(context: dict[str, Any]) -> str:
    return (
        "Create a deployment plan for this repository context.\n\n"
        f"{json.dumps(context, indent=2, default=str)}"
    )


def build_details(plan: dict[str, Any], source: str) -> list[str]:
    checks = [str(check) for check in plan["checks"]]
    checks_preview = ", ".join(checks[:4])
    if len(checks) > 4:
        checks_preview = f"{checks_preview}, +{len(checks) - 4} more"

    details = [
        f"Plan source: {source}",
        f"Service: {plan['service_name']}",
        f"Namespace: {plan['namespace']}",
        f"Deployment target: {plan['deployment_target']}",
        f"Local port: {plan['local_port']}",
        f"Image: {plan['image']}",
        f"Replicas: {plan['replicas']}",
        f"Deployment strategy: {plan['deployment_strategy']}",
        (
            "SLO: error rate <= "
            f"{plan['slo']['max_error_rate']}, average latency <= "
            f"{plan['slo']['max_avg_latency_ms']}ms"
        ),
        f"Checks: {checks_preview}",
        f"Environment fit: {concise(plan['environment_fit'], 140)}",
    ]

    details.extend(
        f"Observation: {item}"
        for item in concise_list(plan["repo_observations"], limit=3, width=120)
    )
    details.extend(
        f"Next step: {item}"
        for item in concise_list(plan["execution_plan"], limit=3, width=120)
    )
    details.extend(f"Risk: {item}" for item in concise_list(plan["risks"], limit=2, width=120))
    return details


def planned_pipeline_actions(plan: dict[str, Any]) -> list[str]:
    if plan["deployment_target"] == "minikube":
        return [
            "Terraform Agent: decide whether cloud IaC applies to this local target.",
            "Security Agent: run available Trivy/Checkov checks in demo-safe mode.",
            "Kubernetes Agent: review namespace, probes, resources, and local image policy.",
            "Test Agent: run pytest before deployment.",
            "Deploy Agent: start minikube, create namespace, build image, apply manifests, wait for rollout.",
            "SLO Agent: validate localhost checkout traffic through the port-forward.",
            "Rollback Agent: undo the rollout if SLO validation fails.",
        ]

    return [
        "Terraform Agent: review cloud infrastructure requirements.",
        "Security Agent: run available IaC and filesystem scans.",
        "Kubernetes Agent: note that Kubernetes manifests are not applied for VM deployment.",
        "Test Agent: generate and run fast API scenarios before deployment.",
        "Deploy Agent: deploy the pushed Docker image to the VM over SSH.",
        "SLO Agent: validate the public checkout endpoint.",
        "Rollback Agent: restore the previous Docker container/image if SLO validation fails.",
    ]


def run(context: dict[str, Any]) -> dict[str, Any]:
    intent = context.get("intent") or f"Deploy {service_name()} to local minikube."
    source = "openai"
    gathered_context = repo_context(intent)

    try:
        raw_plan = ask_llm_json(SYSTEM_PROMPT, build_user_prompt(gathered_context))
        plan = normalize_plan(raw_plan)
        if not valid_plan(plan):
            raise ValueError("OpenAI returned a deployment plan with missing or invalid fields.")
    except Exception as exc:
        source = "safe_defaults"
        plan = safe_default_plan()
        fallback_reason = str(exc)
    else:
        fallback_reason = ""

    context["deployment_plan"] = plan

    details = build_details(plan, source)
    if fallback_reason:
        details.append(f"Fallback reason: {fallback_reason}")

    return {
        "agent": "planner",
        "status": "passed",
        "summary": (
            f"Plan ready for {plan['service_name']}: validate, build, deploy to "
            f"{plan['namespace']}, check SLOs, and rollback if needed."
        ),
        "details": details,
        "plan": plan,
        "repo_context": gathered_context,
        "pipeline_actions": planned_pipeline_actions(plan),
    }
