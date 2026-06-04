"""OpenAI-powered FinOps cost agent for the Agentic DevOps demo."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from agents.config import deployment_target, kube_namespace, service_name
from agents.llm_client import ask_llm_json

DEPLOYMENT_PATH = Path("k8s/deployment.yaml")
HPA_PATH = Path("k8s/hpa.yaml")
TERRAFORM_DIR = Path("infra/terraform")

SYSTEM_PROMPT = """You are a senior cloud FinOps architect specializing in Kubernetes and GCP.

Estimate monthly infrastructure cost based on provided deployment information.

Provide realistic ranges rather than exact values.

Identify over-provisioning, right-sizing opportunities, autoscaling improvements, and waste reduction recommendations.

If deployment_target is minikube, do not estimate GKE, cloud load balancer, or cloud management fees.
For minikube, focus on local resource reservations, right-sizing, and demo environment hygiene.

Return only JSON."""

MINIKUBE_SYSTEM_PROMPT = """You are a senior Kubernetes FinOps advisor reviewing a local minikube deployment.

This target is local minikube, not a cloud cluster.

Rules:
- Direct monthly cloud infrastructure cost must be 0.
- Do not mention GKE, cloud load balancers, cloud logging, node pool costs, cloud management fees, egress, zones, or committed-use discounts.
- Focus on local resource efficiency, CPU/memory requests vs limits, HPA usefulness, laptop capacity, scheduling pressure, and demo reliability.
- Provide recommendations that are useful for a local developer/demo environment.

Return only JSON."""

CLOUD_ONLY_TERMS = [
    "gke",
    "load balancer",
    "load-balancer",
    "cloud logging",
    "cloud monitoring",
    "node pool",
    "management fee",
    "cluster management",
    "egress",
    "inter-zone",
    "committed-use",
    "autopilot",
]


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


def cpu_to_millicores(value: str | int | None) -> int | None:
    if value is None:
        return None
    text = str(value)
    if text.endswith("m"):
        return int(text[:-1])
    return int(float(text) * 1000)


def memory_to_mib(value: str | int | None) -> int | None:
    if value is None:
        return None
    text = str(value)
    units = {
        "Ki": 1 / 1024,
        "Mi": 1,
        "Gi": 1024,
        "Ti": 1024 * 1024,
    }
    for suffix, multiplier in units.items():
        if text.endswith(suffix):
            return int(float(text[: -len(suffix)]) * multiplier)
    return int(float(text) / (1024 * 1024))


def terraform_machine_types() -> list[str]:
    machine_types: set[str] = set()
    for path in TERRAFORM_DIR.glob("*.tf"):
        content = path.read_text(encoding="utf-8")
        machine_types.update(re.findall(r'machine_type\s*=\s*"([^"]+)"', content))
        machine_types.update(re.findall(r'default\s*=\s*"((?:e2|n1|n2|c2|m1|m2)-[^"]+)"', content))
    return sorted(machine_types)


def storage_resources(deployment: dict[str, Any]) -> list[str]:
    volumes = deployment.get("spec", {}).get("template", {}).get("spec", {}).get("volumes", [])
    storage = []
    for volume in volumes:
        if "persistentVolumeClaim" in volume:
            storage.append(volume.get("name", "persistent-volume-claim"))
        if "emptyDir" in volume:
            storage.append(volume.get("name", "empty-dir"))
    return storage


def manifest_inputs(context: dict[str, Any]) -> dict[str, Any]:
    deployment = load_yaml(DEPLOYMENT_PATH)
    hpa = load_yaml(HPA_PATH)
    container = first_container(deployment)
    resources = container.get("resources", {})
    requests = resources.get("requests", {})
    limits = resources.get("limits", {})
    plan = context.get("deployment_plan", {})

    return {
        "deployment_target": context.get("deployment_target") or deployment_target(),
        "namespace": plan.get("namespace")
        or deployment.get("metadata", {}).get("namespace")
        or context.get("namespace")
        or kube_namespace(),
        "service_name": plan.get("service_name")
        or deployment.get("metadata", {}).get("name")
        or context.get("service_name")
        or service_name(),
        "replica_count": plan.get("replicas") or deployment.get("spec", {}).get("replicas"),
        "cpu_requests": requests.get("cpu"),
        "cpu_limits": limits.get("cpu"),
        "memory_requests": requests.get("memory"),
        "memory_limits": limits.get("memory"),
        "cpu_request_millicores": cpu_to_millicores(requests.get("cpu")),
        "cpu_limit_millicores": cpu_to_millicores(limits.get("cpu")),
        "memory_request_mib": memory_to_mib(requests.get("memory")),
        "memory_limit_mib": memory_to_mib(limits.get("memory")),
        "autoscaling": {
            "min_replicas": hpa.get("spec", {}).get("minReplicas"),
            "max_replicas": hpa.get("spec", {}).get("maxReplicas"),
        },
        "vm_machine_types": terraform_machine_types(),
        "storage_resources": storage_resources(deployment),
    }


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def parse_top_pods(output: str) -> list[dict[str, Any]]:
    pods = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 3:
            continue
        pods.append(
            {
                "pod": parts[0],
                "cpu_millicores": cpu_to_millicores(parts[1]),
                "memory_mib": memory_to_mib(parts[2]),
            }
        )
    return pods


def collect_live_inputs(namespace: str, should_collect: bool) -> dict[str, Any]:
    if not should_collect:
        return {"collected": False, "reason": "Deployment has not completed in this run."}

    commands = {
        "deployment_yaml": ["kubectl", "get", "deployment", "-n", namespace, "-o", "yaml"],
        "hpa_yaml": ["kubectl", "get", "hpa", "-n", namespace, "-o", "yaml"],
        "top_pods": ["kubectl", "top", "pods", "-n", namespace],
    }
    live: dict[str, Any] = {"collected": True, "errors": []}

    for key, command in commands.items():
        completed = run_command(command)
        if completed.returncode == 0:
            live[key] = completed.stdout
        else:
            live["errors"].append((completed.stderr or completed.stdout).strip())

    if "top_pods" in live:
        live["pod_usage"] = parse_top_pods(live["top_pods"])

    return live


def waste_analysis(inputs: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
    pods = live.get("pod_usage") or []
    requested_cpu = inputs.get("cpu_request_millicores") or 0
    requested_mem = inputs.get("memory_request_mib") or 0

    if not pods or not requested_cpu or not requested_mem:
        return {
            "waste_percentage": 0,
            "potential_savings": 0,
            "recommendations": ["Collect live pod metrics after deployment for right-sizing."],
        }

    avg_cpu = sum(pod["cpu_millicores"] for pod in pods) / len(pods)
    avg_mem = sum(pod["memory_mib"] for pod in pods) / len(pods)
    cpu_waste = max(0, (requested_cpu - avg_cpu) / requested_cpu * 100)
    mem_waste = max(0, (requested_mem - avg_mem) / requested_mem * 100)
    waste_percentage = round(max(cpu_waste, mem_waste), 2)

    return {
        "waste_percentage": waste_percentage,
        "potential_savings": round(waste_percentage / 100 * 45, 2),
        "recommendations": [
            f"Average CPU usage is {round(avg_cpu, 2)}m against {requested_cpu}m requested.",
            f"Average memory usage is {round(avg_mem, 2)}Mi against {requested_mem}Mi requested.",
        ],
    }


def build_prompt(inputs: dict[str, Any], live: dict[str, Any], waste: dict[str, Any]) -> str:
    payload = {
        "deployment_inputs": inputs,
        "live_kubernetes_inputs": live,
        "computed_waste_analysis": waste,
        "required_output_schema": {
            "estimated_monthly_cost_range": {"low": "number", "high": "number"},
            "cost_drivers": [],
            "optimization_opportunities": [],
            "risk_level": "Low|Medium|High",
            "executive_summary": "",
            "waste_percentage": "number",
            "potential_savings": "number",
            "recommendations": [],
        },
    }
    return json.dumps(payload, indent=2, default=str)


def system_prompt_for_target(target: str) -> str:
    if target == "minikube":
        return MINIKUBE_SYSTEM_PROMPT
    return SYSTEM_PROMPT


def fallback_estimate(inputs: dict[str, Any], waste: dict[str, Any]) -> dict[str, Any]:
    if inputs.get("deployment_target") == "minikube":
        return minikube_estimate(inputs, waste)

    replicas = inputs.get("replica_count") or 2
    min_replicas = inputs.get("autoscaling", {}).get("min_replicas") or replicas
    max_replicas = inputs.get("autoscaling", {}).get("max_replicas") or replicas
    high = max(25, max_replicas * 9)
    low = max(10, min_replicas * 8)

    recommendations = [
        "Keep HPA enabled and verify it can scale down during idle periods.",
        "Compare requested CPU and memory against live usage after deployment.",
        "Avoid adding a cloud LoadBalancer for local minikube demos.",
    ] + waste.get("recommendations", [])

    return {
        "estimated_monthly_cost_range": {"low": low, "high": high},
        "monthly_cost_range": {"low": low, "high": high},
        "cost_drivers": [
            f"{replicas} requested replicas",
            f"CPU request {inputs.get('cpu_requests')}",
            f"Memory request {inputs.get('memory_requests')}",
            f"HPA range {min_replicas}-{max_replicas} replicas",
            "Optional GCP VM Terraform demo resources",
        ],
        "optimization_opportunities": recommendations,
        "risk_level": "Low",
        "executive_summary": (
            "The checkout-service footprint is small. Main cost risk comes from "
            "minimum replicas, oversized requests, and optional GCP VM resources."
        ),
        "waste_percentage": waste.get("waste_percentage", 0),
        "potential_savings": waste.get("potential_savings", 0),
        "recommendations": recommendations,
    }


def minikube_estimate(inputs: dict[str, Any], waste: dict[str, Any]) -> dict[str, Any]:
    replicas = inputs.get("replica_count") or 2
    min_replicas = inputs.get("autoscaling", {}).get("min_replicas") or replicas
    max_replicas = inputs.get("autoscaling", {}).get("max_replicas") or replicas
    recommendations = [
        "No cloud infrastructure cost is estimated for local minikube.",
        "Keep imagePullPolicy set to Never for locally built images.",
        "Use kubectl top pods after deployment to compare real usage against requests.",
        "For laptop demos, consider minReplicas=1 if high availability is not being demonstrated.",
        "Keep requests small enough for the local minikube node to avoid scheduling pressure.",
    ] + waste.get("recommendations", [])

    return {
        "estimated_monthly_cost_range": {"low": 0, "high": 0},
        "monthly_cost_range": {"low": 0, "high": 0},
        "cost_drivers": [
            "Local minikube uses existing laptop/desktop resources",
            f"{replicas} replicas reserve CPU and memory on the local node",
            f"CPU request {inputs.get('cpu_requests')} and memory request {inputs.get('memory_requests')}",
            f"HPA range {min_replicas}-{max_replicas} affects local capacity pressure, not cloud spend",
        ],
        "optimization_opportunities": recommendations,
        "risk_level": "Low",
        "executive_summary": (
            "This is a local minikube deployment, so direct monthly cloud cost is $0. "
            "The main FinOps concern is not cloud spend; it is avoiding oversized local "
            "CPU/memory requests that make the demo harder to schedule or run reliably."
        ),
        "waste_percentage": waste.get("waste_percentage", 0),
        "potential_savings": 0,
        "recommendations": recommendations,
    }


def stringify_item(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        preferred_keys = ["driver", "area", "finding", "impact", "suggestion", "notes", "message"]
        parts = [str(item[key]) for key in preferred_keys if item.get(key)]
        if parts:
            return " - ".join(parts)
        return json.dumps(item, sort_keys=True)
    return str(item)


def normalize_list(items: Any, fallback: list[Any]) -> list[str]:
    source = items if isinstance(items, list) and items else fallback
    return [stringify_item(item) for item in source]


def normalize_response(response: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    cost_range = response.get("estimated_monthly_cost_range") or response.get("monthly_cost_range")
    if not isinstance(cost_range, dict):
        cost_range = fallback["estimated_monthly_cost_range"]

    return {
        "estimated_monthly_cost_range": {
            "low": float(cost_range.get("low", fallback["estimated_monthly_cost_range"]["low"])),
            "high": float(cost_range.get("high", fallback["estimated_monthly_cost_range"]["high"])),
        },
        "monthly_cost_range": {
            "low": float(cost_range.get("low", fallback["monthly_cost_range"]["low"])),
            "high": float(cost_range.get("high", fallback["monthly_cost_range"]["high"])),
        },
        "cost_drivers": normalize_list(response.get("cost_drivers"), fallback["cost_drivers"]),
        "optimization_opportunities": normalize_list(
            response.get("optimization_opportunities"),
            fallback["optimization_opportunities"],
        ),
        "risk_level": response.get("risk_level") or fallback["risk_level"],
        "executive_summary": response.get("executive_summary") or fallback["executive_summary"],
        "waste_percentage": float(response.get("waste_percentage", fallback["waste_percentage"])),
        "potential_savings": float(response.get("potential_savings", fallback["potential_savings"])),
        "recommendations": normalize_list(response.get("recommendations"), fallback["recommendations"]),
    }


def contains_cloud_only_terms(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in CLOUD_ONLY_TERMS)


def sanitize_minikube_estimate(estimate: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(estimate)
    sanitized["estimated_monthly_cost_range"] = {"low": 0, "high": 0}
    sanitized["monthly_cost_range"] = {"low": 0, "high": 0}
    sanitized["potential_savings"] = 0

    sanitized["cost_drivers"] = [
        item for item in normalize_list(sanitized.get("cost_drivers"), fallback["cost_drivers"])
        if not contains_cloud_only_terms(item)
    ] or fallback["cost_drivers"]
    sanitized["optimization_opportunities"] = [
        item
        for item in normalize_list(
            sanitized.get("optimization_opportunities"),
            fallback["optimization_opportunities"],
        )
        if not contains_cloud_only_terms(item)
    ] or fallback["optimization_opportunities"]
    sanitized["recommendations"] = [
        item for item in normalize_list(sanitized.get("recommendations"), fallback["recommendations"])
        if not contains_cloud_only_terms(item)
    ] or fallback["recommendations"]

    summary = str(sanitized.get("executive_summary") or "")
    if contains_cloud_only_terms(summary):
        sanitized["executive_summary"] = fallback["executive_summary"]

    return sanitized


def print_finops_report(inputs: dict[str, Any], estimate: dict[str, Any]) -> None:
    cost_range = estimate["estimated_monthly_cost_range"]
    width = 64
    print("\n" + "=" * width)
    print("FinOps Agent Report")
    print("=" * width)
    print(f"Target: {inputs.get('deployment_target', 'unknown')}")
    print(f"Service: {inputs['service_name']}")
    print(f"Namespace: {inputs['namespace']}")
    print(f"Replicas: {inputs.get('replica_count')}")
    print(f"Requests: CPU {inputs.get('cpu_requests')} / Memory {inputs.get('memory_requests')}")
    print(f"Limits: CPU {inputs.get('cpu_limits')} / Memory {inputs.get('memory_limits')}")
    print(f"HPA: {inputs['autoscaling'].get('min_replicas')}-{inputs['autoscaling'].get('max_replicas')} replicas")
    print("-" * width)
    print(f"Estimated Monthly Cost: ${cost_range['low']:.0f} - ${cost_range['high']:.0f}")
    print(f"Risk: {estimate['risk_level']}")
    print(f"Waste Estimate: {estimate['waste_percentage']}%")
    print(f"Potential Monthly Savings: ${estimate['potential_savings']}")
    print("-" * width)
    print("Top Cost Drivers:")
    for driver in estimate["cost_drivers"]:
        print(f"- {driver}")
    print("\nOptimization Opportunities:")
    for opportunity in estimate["optimization_opportunities"]:
        print(f"- {opportunity}")
    print("\nExecutive Summary:")
    print(estimate["executive_summary"])
    print("=" * width)
    print("")


def run(context: dict[str, Any]) -> dict[str, Any]:
    inputs = manifest_inputs(context)
    live = collect_live_inputs(
        inputs["namespace"],
        should_collect=context.get("agent_outputs", {}).get("deploy", {}).get("status") == "passed",
    )
    waste = waste_analysis(inputs, live)
    fallback = fallback_estimate(inputs, waste)

    target = inputs.get("deployment_target")
    source = "openai"
    try:
        response = ask_llm_json(system_prompt_for_target(target), build_prompt(inputs, live, waste))
        estimate = normalize_response(response, fallback)
        if target == "minikube":
            estimate = sanitize_minikube_estimate(estimate, fallback)
    except Exception as exc:
        source = "safe_defaults"
        estimate = fallback
        estimate["fallback_reason"] = str(exc)

    print_finops_report(inputs, estimate)

    details = [
        f"FinOps source: {source}",
        f"Namespace: {inputs['namespace']}",
        f"Replicas: {inputs.get('replica_count')}",
        f"CPU request/limit: {inputs.get('cpu_requests')} / {inputs.get('cpu_limits')}",
        f"Memory request/limit: {inputs.get('memory_requests')} / {inputs.get('memory_limits')}",
        f"Autoscaling: {inputs['autoscaling'].get('min_replicas')}-{inputs['autoscaling'].get('max_replicas')}",
        f"Waste percentage: {estimate['waste_percentage']}%",
        f"Potential monthly savings: ${estimate['potential_savings']}",
    ]
    if estimate.get("fallback_reason"):
        details.append(f"Fallback reason: {estimate['fallback_reason']}")

    return {
        "agent": "cost",
        "status": "passed",
        "summary": "Generated FinOps cost estimate and optimization recommendations.",
        "details": details,
        "finops_inputs": inputs,
        "live_inputs": live,
        "monthly_cost_range": estimate["monthly_cost_range"],
        "estimated_monthly_cost_range": estimate["estimated_monthly_cost_range"],
        "waste_percentage": estimate["waste_percentage"],
        "potential_savings": estimate["potential_savings"],
        "recommendations": estimate["recommendations"],
        "cost_drivers": estimate["cost_drivers"],
        "optimization_opportunities": estimate["optimization_opportunities"],
        "risk_level": estimate["risk_level"],
        "executive_summary": estimate["executive_summary"],
    }
