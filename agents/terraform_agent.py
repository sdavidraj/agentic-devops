"""IaC/Terraform agent for local and cloud deployment targets."""

from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path
from typing import Any

from agents.config import deployment_target
from agents.llm_client import ask_llm_json

DIGITALOCEAN_TERRAFORM_DIR = Path("infra/digitalocean")
TERRAFORM_DIR = Path("infra/terraform")
REQUIRED_TERRAFORM_FILES = [
    TERRAFORM_DIR / "main.tf",
    TERRAFORM_DIR / "variables.tf",
    TERRAFORM_DIR / "outputs.tf",
]

SYSTEM_PROMPT = """You are a senior Infrastructure-as-Code architect specializing in Kubernetes, Terraform, GCP, DigitalOcean, GKE, and VM deployments.

Review the deployment target and Terraform files.
Use the intent, deployment plan, Kubernetes context, and Terraform file contents to reason about whether IaC is required.
Keep the output concise for a command-line executive demo.

For local minikube deployments, decide whether Terraform is applicable. Explain the reasoning in local-development terms: minikube uses the local Docker daemon/profile, Kubernetes manifests are the deployment artifact, and Terraform should usually be optional unless the demo intentionally provisions a remote VM or GKE cluster.
For GKE deployments, check whether Terraform should define a GKE cluster, node pools, IAM, networking, and outputs.
For VM deployments, check whether Terraform defines an appropriate Compute Engine VM, machine type, boot disk, networking, and outputs.
For digitalocean-vm deployments, check infra/digitalocean for a DigitalOcean provider, Droplet, firewall, SSH key support, and VM/app URL outputs.

Return only JSON with:
{
  "status": "pass" | "warn" | "fail" | "skipped",
  "target": "minikube" | "gke" | "vm" | "digitalocean-vm",
  "infrastructure_required": boolean,
  "intent_interpretation": string,
  "summary": string,
  "reasoning": string,
  "findings": [{"check": string, "status": "pass" | "warn" | "fail", "message": string}],
  "recommendations": [string]
}

Length rules:
- intent_interpretation: one sentence, max 140 characters.
- summary: one sentence, max 160 characters.
- reasoning: one sentence, max 180 characters.
- findings: max 3 items, each message max 140 characters.
- recommendations: max 3 items, each max 140 characters."""


def concise(value: Any, width: int = 120) -> str:
    text = " ".join(str(value).split())
    return textwrap.shorten(text, width=width, placeholder="...")


def compact_items(values: list[Any], limit: int, width: int = 120) -> list[Any]:
    compacted: list[Any] = []
    for value in values[:limit]:
        if isinstance(value, dict):
            item = dict(value)
            item["check"] = concise(item.get("check", "check"), 54)
            item["message"] = concise(item.get("message", "No message provided."), width)
            compacted.append(item)
        else:
            compacted.append(concise(value, width))
    return compacted


def print_row(label: str, value: Any, width: int = 96) -> None:
    print(f"{label:<24} {concise(value, width)}")


def target_from_context(context: dict[str, Any]) -> str:
    explicit = context.get("deployment_target")
    if explicit:
        return str(explicit).lower()

    intent = str(context.get("intent", "")).lower()
    if "minikube" in intent or "local" in intent:
        return "minikube"
    if "gke" in intent or "google kubernetes engine" in intent:
        return "gke"
    if "digitalocean" in intent or "droplet" in intent:
        return "digitalocean-vm"
    if "vm" in intent or "compute engine" in intent:
        return "vm"

    return deployment_target()


def terraform_dir_for_target(target: str) -> Path:
    if target == "digitalocean-vm":
        return DIGITALOCEAN_TERRAFORM_DIR
    return TERRAFORM_DIR


def read_terraform_files(target: str) -> dict[str, str]:
    terraform_dir = terraform_dir_for_target(target)
    if not terraform_dir.exists():
        return {}
    return {
        str(path): path.read_text(encoding="utf-8")
        for path in sorted(terraform_dir.glob("*.tf"))
    }


def local_skip_result(target: str = "minikube") -> dict[str, Any]:
    return {
        "status": "skipped",
        "target": target,
        "infrastructure_required": False,
        "intent_interpretation": "Deploy the checkout service into a local minikube Kubernetes cluster.",
        "summary": "Local minikube deployment does not require Terraform cloud infrastructure.",
        "reasoning": "The selected target runs on the developer machine, so Kubernetes manifests and the local Docker image flow are sufficient for this demo.",
        "findings": [
            {
                "check": "cloud infrastructure",
                "status": "pass",
                "message": "Minikube uses the local machine and Docker environment.",
            }
        ],
        "recommendations": [
            "Use Kubernetes manifests and minikube docker-env for local deployment.",
            "Keep Terraform optional for cloud demos such as GKE or GCP VM.",
        ],
    }


def local_cloud_review(target: str, terraform_files: dict[str, str]) -> dict[str, Any]:
    content = "\n".join(terraform_files.values())
    findings: list[dict[str, str]] = []
    recommendations: list[str] = []
    status = "pass"

    if not terraform_files:
        return {
            "status": "fail",
            "target": target,
            "infrastructure_required": True,
            "intent_interpretation": f"Deploy the checkout service to {target.upper()} using Terraform-managed infrastructure.",
            "summary": f"{target.upper()} deployment requires Terraform files, but none were found.",
            "reasoning": "Cloud deployment targets need explicit infrastructure definitions so the runtime environment can be recreated.",
            "findings": [
                {
                    "check": "terraform files",
                    "status": "fail",
                    "message": "No Terraform files found under infra/terraform.",
                }
            ],
            "recommendations": [f"Add Terraform modules for the {target.upper()} deployment target."],
        }

    if target == "digitalocean-vm":
        provider_ok = "digitalocean/digitalocean" in content
        droplet_ok = "digitalocean_droplet" in content
        firewall_ok = "digitalocean_firewall" in content
        output_ok = "droplet_ipv4_address" in content and "app_url" in content

        findings.append(
            {
                "check": "provider",
                "status": "pass" if provider_ok else "fail",
                "message": "DigitalOcean provider is configured."
                if provider_ok
                else "DigitalOcean provider is missing.",
            }
        )
        findings.append(
            {
                "check": "droplet",
                "status": "pass" if droplet_ok else "fail",
                "message": "DigitalOcean Droplet resource found."
                if droplet_ok
                else "No digitalocean_droplet resource found.",
            }
        )
        findings.append(
            {
                "check": "firewall outputs",
                "status": "pass" if firewall_ok and output_ok else "warn",
                "message": "Firewall and app URL outputs found."
                if firewall_ok and output_ok
                else "Firewall or VM URL outputs are incomplete.",
            }
        )

        if not provider_ok or not droplet_ok:
            status = "fail"
        elif not firewall_ok or not output_ok:
            status = "warn"
        return {
            "status": status,
            "target": target,
            "infrastructure_required": True,
            "intent_interpretation": "Deploy checkout-service to a DigitalOcean Droplet VM.",
            "summary": "Reviewed DigitalOcean Terraform for VM deployment.",
            "reasoning": "The DigitalOcean target requires Terraform-managed Droplet, firewall, SSH, and endpoint outputs.",
            "findings": findings,
            "recommendations": recommendations
            or ["Use infra/digitalocean for the DigitalOcean VM GitHub Actions demo."],
        }

    if "hashicorp/google" in content:
        findings.append(
            {"check": "provider", "status": "pass", "message": "Google provider is configured."}
        )
    else:
        status = "fail"
        findings.append(
            {"check": "provider", "status": "fail", "message": "Google provider is missing."}
        )
        recommendations.append("Configure the hashicorp/google provider.")

    if target == "gke":
        if "google_container_cluster" in content:
            findings.append(
                {"check": "gke cluster", "status": "pass", "message": "GKE cluster resource found."}
            )
        else:
            status = "warn"
            findings.append(
                {
                    "check": "gke cluster",
                    "status": "warn",
                    "message": "No google_container_cluster resource found.",
                }
            )
            recommendations.append("Add google_container_cluster and node pool resources for GKE.")
    elif target == "vm":
        if "google_compute_instance" in content:
            findings.append(
                {"check": "compute vm", "status": "pass", "message": "Compute Engine VM resource found."}
            )
        else:
            status = "fail"
            findings.append(
                {
                    "check": "compute vm",
                    "status": "fail",
                    "message": "No google_compute_instance resource found.",
                }
            )
            recommendations.append("Add a google_compute_instance resource for VM deployment.")

        machine_types = re.findall(r'(?:machine_type|default)\s*=\s*"([^"]+)"', content)
        if machine_types:
            findings.append(
                {
                    "check": "machine type",
                    "status": "pass",
                    "message": f"Machine type values found: {', '.join(sorted(set(machine_types)))}.",
                }
            )
        else:
            status = "warn" if status != "fail" else status
            recommendations.append("Declare machine_type as a variable with a small default.")

    return {
        "status": status,
        "target": target,
        "infrastructure_required": True,
        "intent_interpretation": f"Deploy the checkout service to {target.upper()} using Terraform-managed infrastructure.",
        "summary": f"Reviewed Terraform files for {target.upper()} deployment.",
        "reasoning": "The selected target is cloud-based, so Terraform should describe the required GCP runtime resources and outputs.",
        "findings": findings,
        "recommendations": recommendations
        or ["Terraform files match the selected cloud deployment target."],
    }


def ask_openai_review(target: str, context: dict[str, Any], terraform_files: dict[str, str]) -> dict[str, Any]:
    payload = {
        "deployment_target": target,
        "intent": context.get("intent"),
        "deployment_plan": context.get("deployment_plan"),
        "kubernetes": {
            "namespace": context.get("namespace")
            or context.get("deployment_plan", {}).get("namespace"),
            "service_name": context.get("service_name")
            or context.get("deployment_plan", {}).get("service_name"),
            "replicas": context.get("deployment_plan", {}).get("replicas"),
            "deployment_target": target,
        },
        "terraform_files": terraform_files,
    }
    return ask_llm_json(SYSTEM_PROMPT, json.dumps(payload, indent=2))


def normalize_review(review: dict[str, Any], target: str) -> dict[str, Any]:
    status = review.get("status", "warn")
    if status not in {"pass", "warn", "fail", "skipped"}:
        status = "warn"
    return {
        "status": status,
        "target": review.get("target", target),
        "infrastructure_required": bool(review.get("infrastructure_required", status != "skipped")),
        "intent_interpretation": review.get(
            "intent_interpretation",
            "Reviewed the requested deployment target and repository IaC context.",
        ),
        "summary": review.get("summary", "Reviewed infrastructure as code."),
        "reasoning": review.get(
            "reasoning",
            "The IaC decision was based on the selected deployment target and Terraform files.",
        ),
        "findings": compact_items(review.get("findings") or [], limit=3, width=140),
        "recommendations": compact_items(review.get("recommendations") or [], limit=3, width=140),
    }


def agent_status(review_status: str, fallback_used: bool) -> str:
    if review_status == "skipped":
        return "skipped"
    if review_status == "fail":
        return "failed"
    if review_status == "warn" or fallback_used:
        return "warning"
    return "passed"


def minikube_review(source: str) -> dict[str, Any]:
    return {
        "agent": "terraform",
        "status": "skipped",
        "target": "minikube",
        "infrastructure_required": False,
        "review_status": "skipped",
        "review_source": source,
        "intent_interpretation": "Local minikube deployment uses Kubernetes manifests, not Terraform.",
        "reasoning": "No cloud infrastructure will be provisioned for this target.",
        "summary": "Terraform skipped for local minikube deployment.",
        "details": [
            "Target: minikube",
            "Infrastructure: not required",
            "Action: deploy agent will build the image, apply Kubernetes manifests, and restart rollout.",
        ],
        "recommendations": [],
        "artifacts": [],
    }


def run(context: dict[str, Any]) -> dict[str, Any]:
    target = target_from_context(context)
    terraform_files = read_terraform_files(target)
    fallback_used = False

    try:
        review = normalize_review(ask_openai_review(target, context, terraform_files), target)
    except Exception as exc:
        fallback_used = True
        if target == "minikube":
            review = local_skip_result(target)
        else:
            review = local_cloud_review(target, terraform_files)
        review["recommendations"].append(f"OpenAI IaC review unavailable: {exc}")
        review["findings"] = compact_items(review.get("findings") or [], limit=3, width=140)
        review["recommendations"] = compact_items(
            review.get("recommendations") or [], limit=3, width=140
        )

    status = agent_status(review["status"], fallback_used)
    source = "safe fallback" if fallback_used else "openai"

    if target == "minikube" and not review["infrastructure_required"]:
        return minikube_review(source)

    print("\nIaC Agent Report")
    print("================")
    print_row("Review source", source)
    print_row("Target", target)
    print_row("Infrastructure", "required" if review["infrastructure_required"] else "not required")
    print_row("Review status", review["status"])
    print_row("Intent", review["intent_interpretation"], 120)
    print_row("Reasoning", review["reasoning"], 140)
    print_row("Summary", review["summary"], 140)

    if review["findings"]:
        print("\nFindings:")
        for finding in review["findings"]:
            print(
                f"- {finding.get('check', 'check')}: "
                f"{finding.get('status', 'warn')} - "
                f"{finding.get('message', 'No message provided.')}"
            )

    if review["recommendations"]:
        print("\nRecommendations:")
        for recommendation in review["recommendations"]:
            print(f"- {recommendation}")

    details = [
        f"IaC review source: {source}",
        f"Deployment target: {target}",
        f"Infrastructure required: {review['infrastructure_required']}",
        f"IaC review status: {review['status']}",
        f"Intent: {concise(review['intent_interpretation'], 120)}",
        f"Reasoning: {concise(review['reasoning'], 140)}",
    ]
    for finding in review["findings"][:2]:
        details.append(
            f"{finding.get('check', 'check')}: {finding.get('status', 'warn')} - "
            f"{finding.get('message', 'No message provided.')}"
        )
    for recommendation in review["recommendations"][:2]:
        details.append(f"Recommendation: {recommendation}")

    return {
        "agent": "terraform",
        "status": status,
        "target": target,
        "infrastructure_required": review["infrastructure_required"],
        "review_status": review["status"],
        "review_source": source,
        "intent_interpretation": review["intent_interpretation"],
        "reasoning": review["reasoning"],
        "summary": review["summary"],
        "details": details,
        "recommendations": review["recommendations"],
        "artifacts": list(terraform_files.keys()),
    }
