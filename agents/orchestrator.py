"""Executive-friendly orchestrator for the Agentic DevOps pipeline."""

from __future__ import annotations

import argparse
import json
import os
import selectors
import shutil
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.config import (
    deployment_target,
    docker_image,
    local_port,
    kube_namespace,
    service_name,
    slo_base_url,
    vm_app_port,
    vm_host,
    vm_user,
)
from agents.cost_agent import run as run_cost_agent
from agents import deploy_agent
from agents.k8s_agent import run as run_k8s_agent
from agents.llm_client import ask_llm
from agents.planner_agent import run as run_planner_agent
from agents.release_notes_agent import run as run_release_notes_agent
from agents.rollback_agent import run as run_rollback_agent
from agents.security_agent import run as run_security_agent
from agents.slo_agent import run as run_slo_agent
from agents.terraform_agent import run as run_terraform_agent
from agents.test_agent import run as run_test_agent
from agents.vm_deploy_agent import run as run_vm_deploy_agent
from agents.vm_rollback_agent import run as run_vm_rollback_agent

DEFAULT_INTENT = "Deploy a new checkout microservice"
DEFAULT_NAMESPACE = kube_namespace()
TOTAL_STAGES = 10
EXECUTIVE_SUMMARY_SYSTEM_PROMPT = """You are the executive narrator for an Agentic DevOps deployment.
Write a concise plain-text summary for a live demo audience.
Show what reasoning, decisions, and tradeoffs the agents performed to complete or stop the deployment.
Do not claim humans made manual decisions. Do not include markdown tables.
Keep it under 180 words."""

AgentResult = dict[str, Any]
PipelineContext = dict[str, Any]


def terminal_supports_emoji() -> bool:
    encoding = (sys.stdout.encoding or "").lower()
    term = os.getenv("TERM", "")
    return "utf" in encoding and term != "dumb"


def status_label(status: str) -> str:
    normalized = status.lower()
    if not terminal_supports_emoji():
        return normalized.upper()

    icons = {
        "passed": "✅ PASSED",
        "warning": "⚠️ WARNING",
        "failed": "❌ FAILED",
        "skipped": "SKIPPED",
    }
    return icons.get(normalized, normalized.upper())


def log_banner(context: PipelineContext) -> None:
    print("\nAgentic DevOps Pipeline Demo")
    print("=" * 52)
    print(f"Intent: {context['intent']}")
    print(f"Namespace: {context['namespace']}")
    print(f"Deploy enabled: {context['deploy']}")
    print(f"Deployment target: {context['deployment_target']}")
    print(f"Validate only: {context['validate_only']}")
    print(f"Simulate failure: {context['simulate_failure']}")
    if context.get("keep_port_forward"):
        print("Keep port-forward: true")
    if context["dry_run"]:
        print("Mode: dry-run")
    print("=" * 52)


def log_stage_banner(step_number: int, stage_name: str) -> None:
    print(f"\n[{step_number}/{TOTAL_STAGES}] {stage_name}")
    print("-" * 52)


def display_width(max_width: int = 110) -> int:
    return min(shutil.get_terminal_size((max_width, 20)).columns, max_width)


def compact_text(value: Any, max_chars: int = 260) -> str:
    text = " ".join(str(value).split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def print_wrapped(prefix: str, value: Any, max_chars: int = 260) -> None:
    width = display_width()
    text = compact_text(value, max_chars=max_chars)
    wrapped = textwrap.wrap(
        text,
        width=max(width - len(prefix), 40),
        break_long_words=False,
        break_on_hyphens=False,
    )
    if not wrapped:
        print(prefix.rstrip())
        return
    print(f"{prefix}{wrapped[0]}")
    for line in wrapped[1:]:
        print(f"{' ' * len(prefix)}{line}")


def log_result(result: AgentResult) -> None:
    print(f"Status: {status_label(result.get('status', 'unknown'))}")
    print_wrapped("Summary: ", result.get("summary", "No summary provided."), max_chars=220)

    for detail in result.get("details", []):
        print_wrapped("- ", detail, max_chars=220)

    if result.get("pipeline_actions"):
        print("Upcoming agent actions:")
        for action in result["pipeline_actions"]:
            print_wrapped("  - ", action, max_chars=180)

    for artifact in result.get("artifacts", []):
        print_wrapped("Artifact: ", artifact, max_chars=160)


def store_result(context: PipelineContext, result: AgentResult) -> None:
    context["results"].append(result)
    context["agent_outputs"][result["agent"]] = result


def deployment_decision(results: list[AgentResult]) -> str:
    rollback = next((result for result in results if result["agent"] == "rollback"), None)
    if rollback and rollback["status"] == "passed":
        return "Rolled Back"
    if any(result["status"] == "failed" for result in results):
        return "Rolled Back"
    return "Approved"


def executive_summary_evidence(results: list[AgentResult]) -> dict[str, Any]:
    return {
        "deployment_decision": deployment_decision(results),
        "agent_reasoning_trace": [
            {
                "agent": result.get("agent", "unknown"),
                "status": result.get("status", "unknown"),
                "summary": result.get("summary", ""),
                "evidence": result.get("details", [])[:4],
                "pipeline_actions": result.get("pipeline_actions", [])[:3],
            }
            for result in results
        ],
        "failed_stages": [
            result["agent"] for result in results if result.get("status") == "failed"
        ],
        "warning_stages": [
            result["agent"] for result in results if result.get("status") == "warning"
        ],
        "skipped_stages": [
            result["agent"] for result in results if result.get("status") == "skipped"
        ],
    }


def build_executive_summary_prompt(evidence: dict[str, Any]) -> str:
    return (
        "Create the final deployment summary from this agent evidence.\n"
        "Include:\n"
        "- The deployment decision.\n"
        "- The key reasoning path across planning, validation, deploy, SLO, and rollback.\n"
        "- What the agentic system decided automatically and why.\n"
        "- A clear business outcome.\n\n"
        f"{json.dumps(evidence, indent=2, default=str)}"
    )


def fallback_executive_summary(evidence: dict[str, Any]) -> str:
    decision = evidence["deployment_decision"]
    failed = evidence["failed_stages"]
    warnings = evidence["warning_stages"]
    skipped = evidence["skipped_stages"]
    trace = evidence["agent_reasoning_trace"]

    notable = [
        item
        for item in trace
        if item["status"] in {"failed", "warning", "passed"}
    ][:5]
    reasoning_lines = [
        f"- {item['agent']} assessed {item['status']}: {item['summary']}"
        for item in notable
    ]
    if not reasoning_lines:
        reasoning_lines = ["- The agents did not produce enough evidence for a narrative summary."]

    risk_notes: list[str] = []
    if failed:
        risk_notes.append(f"failed stage(s): {', '.join(failed)}")
    if warnings:
        risk_notes.append(f"warning stage(s): {', '.join(warnings)}")
    if skipped:
        risk_notes.append(f"skipped stage(s): {', '.join(skipped)}")
    risk_summary = "; ".join(risk_notes) if risk_notes else "all required stages passed"

    return "\n".join(
        [
            f"Decision: {decision}",
            "",
            "Agentic reasoning:",
            *reasoning_lines,
            "",
            (
                "Automated decision: the pipeline converted stage evidence into a "
                f"deployment outcome and selected {decision.lower()} because {risk_summary}."
            ),
            (
                "Business outcome: release governance, validation, and recovery were "
                "completed by specialist agents with auditable evidence."
            ),
        ]
    )


def generate_executive_summary(results: list[AgentResult]) -> tuple[str, str]:
    evidence = executive_summary_evidence(results)

    try:
        summary = ask_llm(
            EXECUTIVE_SUMMARY_SYSTEM_PROMPT,
            build_executive_summary_prompt(evidence),
        )
        if not summary.strip():
            raise ValueError("OpenAI returned an empty executive summary.")
    except Exception as exc:
        return fallback_executive_summary(evidence), f"safe_defaults ({exc})"

    return summary.strip(), "openai"


def log_executive_summary(results: list[AgentResult]) -> None:
    summary, source = generate_executive_summary(results)

    print("\nExecutive Summary")
    print("=" * 52)
    print(f"Summary source: {source}")
    print(summary)


def align_plan_namespace(context: PipelineContext, result: AgentResult) -> None:
    plan = result.get("plan")
    if isinstance(plan, dict):
        plan["namespace"] = context["namespace"]
        context["deployment_plan"] = plan
        result["details"] = [
            f"Namespace: {context['namespace']}" if detail.startswith("Namespace: ") else detail
            for detail in result.get("details", [])
        ]


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    print(f"$ {' '.join(command)}")
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.stdout.strip():
        print(completed.stdout.strip())
    if completed.stderr.strip():
        print(completed.stderr.strip())
    return completed


def start_port_forward(context: PipelineContext) -> subprocess.Popen[str]:
    command = [
        "kubectl",
        "port-forward",
        f"service/{context['service_name']}",
        f"{context['local_port']}:80",
        "-n",
        context["namespace"],
    ]
    print(f"$ {' '.join(command)}")
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    wait_for_port_forward_ready(context, process)
    return process


def process_output(process: subprocess.Popen[str]) -> str:
    try:
        stdout, stderr = process.communicate(timeout=0.2)
    except subprocess.TimeoutExpired:
        return ""
    return "\n".join(part.strip() for part in [stdout, stderr] if part and part.strip())


def wait_for_port_forward_ready(
    context: PipelineContext,
    process: subprocess.Popen[str],
    timeout_seconds: int = 30,
) -> None:
    port = context["local_port"]
    deadline = time.monotonic() + timeout_seconds
    output_lines: list[str] = []

    print(f"Waiting for local port-forward: http://127.0.0.1:{port}")
    selector = selectors.DefaultSelector()
    if process.stdout:
        selector.register(process.stdout, selectors.EVENT_READ)
    if process.stderr:
        selector.register(process.stderr, selectors.EVENT_READ)

    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process_output(process)
            if output:
                output_lines.append(output)
            selector.close()
            raise RuntimeError(
                "kubectl port-forward exited before SLO validation could run. "
                f"{' '.join(output_lines)}".strip()
            )

        ready = selector.select(timeout=0.2)
        for key, _ in ready:
            line = key.fileobj.readline()
            if not line:
                continue
            line = line.strip()
            output_lines.append(line)
            print(line)
            if "Forwarding from" in line:
                if local_port_is_listening(port):
                    print("Local port-forward is ready.")
                    selector.close()
                    return

    selector.close()

    raise RuntimeError(
        f"Timed out waiting for local port-forward to listen on 127.0.0.1:{port}. "
        f"{' '.join(output_lines)}".strip()
    )


def simulate_failure(context: PipelineContext) -> None:
    commands = [
        [
            "kubectl",
            "set",
            "env",
            f"deployment/{context['service_name']}",
            "FAIL_MODE=true",
            "-n",
            context["namespace"],
        ],
        [
            "kubectl",
            "rollout",
            "status",
            f"deployment/{context['service_name']}",
            "-n",
            context["namespace"],
            "--timeout=120s",
        ],
    ]

    for command in commands:
        completed = run_command(command)
        if completed.returncode != 0:
            raise RuntimeError(f"Failure simulation command failed: {' '.join(command)}")


def run_deploy_agent(context: PipelineContext) -> AgentResult:
    if context["validate_only"]:
        return {
            "agent": "deploy",
            "status": "skipped",
            "summary": "Validate-only mode enabled. Deployment was skipped.",
            "details": ["Use --deploy to deploy to minikube."],
        }

    if not context["deploy"]:
        return {
            "agent": "deploy",
            "status": "skipped",
            "summary": "Deployment skipped. Run with --deploy to deploy to minikube.",
            "details": ["No Kubernetes resources were changed by the orchestrator."],
        }

    if context["deployment_target"] == "digitalocean-vm":
        return run_vm_deploy_agent(context)

    try:
        kube_namespace = context["namespace"]
        print("Deploy Agent Execution Plan")
        print("---------------------------")
        print("1. Ensure minikube is running")
        print("2. Ensure target namespace exists")
        print("3. Build image inside minikube")
        print("4. Apply Kubernetes manifests")
        print("5. Restart deployment to pick up rebuilt local image")
        print("6. Wait for rollout")
        print("7. Start localhost port-forward")

        deploy_agent.print_minikube_docker_env_reminder()
        deploy_agent.ensure_minikube_running()
        deploy_agent.ensure_namespace(kube_namespace)
        deploy_agent.build_image()
        deploy_agent.apply_manifests(kube_namespace)
        deploy_agent.restart_rollout(kube_namespace)
        deploy_agent.wait_for_rollout(kube_namespace)

        if context["simulate_failure"]:
            simulate_failure(context)

        context["port_forward_process"] = start_port_forward(context)
    except Exception as exc:
        return {
            "agent": "deploy",
            "status": "failed",
            "summary": "Deployment to minikube failed.",
            "details": [
                str(exc),
                "Check: kubectl config current-context",
                f"Check: kubectl get pods -n {context['namespace']}",
                "Check: minikube status",
            ],
            "stop_pipeline": True,
        }

    return {
        "agent": "deploy",
        "status": "passed",
        "summary": f"Deployed {context['service_name']} to minikube and started port-forward.",
        "details": [
            "Minikube: running",
            f"Namespace: {context['namespace']}",
            f"Image: {context['image']}",
            "Image build: minikube image build completed.",
            "Manifests: namespace, deployment, service, and HPA applied.",
            "Rollout restart: triggered so existing pods pick up the rebuilt local image.",
            f"Rollout: deployment/{context['service_name']} completed.",
            (
                f"Port-forward: 127.0.0.1:{context['local_port']} -> "
                f"service/{context['service_name']}:80"
            ),
        ],
    }


def run_slo_stage(context: PipelineContext) -> AgentResult:
    if context["validate_only"] or not context["deploy"]:
        slo_context = dict(context)
        slo_context["dry_run"] = True
        return run_slo_agent(slo_context)

    if context.get("deployment_target", "minikube") == "minikube":
        ensure_port_forward_for_slo(context)
    result = run_slo_agent(context)
    if not slo_failed_due_to_readiness(result):
        return result

    if context.get("deployment_target", "minikube") != "minikube":
        return result

    print("SLO readiness check failed. Restarting port-forward and retrying once.")
    stop_port_forward(context)
    context["port_forward_process"] = start_port_forward(context)
    retry_result = run_slo_agent(context)
    retry_result["details"] = [
        "SLO retry: restarted local port-forward after readiness failure.",
        *retry_result.get("details", []),
    ]
    return retry_result


def slo_failed_due_to_readiness(result: AgentResult) -> bool:
    return (
        result.get("agent") == "slo"
        and result.get("status") == "failed"
        and "local health endpoint" in result.get("summary", "")
    )


def stop_port_forward(context: PipelineContext) -> None:
    process = context.get("port_forward_process")
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def local_port_is_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def ensure_port_forward_for_slo(context: PipelineContext) -> None:
    if (
        context["validate_only"]
        or not context["deploy"]
        or context.get("deployment_target", "minikube") != "minikube"
    ):
        return

    port = context["local_port"]
    process = context.get("port_forward_process")

    if process and process.poll() is None and local_port_is_listening(port):
        return

    if process and process.poll() is not None:
        output = process_output(process)
        if output:
            print("Existing port-forward exited before SLO validation:")
            print(output)

    print("Restarting local port-forward for SLO validation.")
    stop_port_forward(context)
    context["port_forward_process"] = start_port_forward(context)


def port_forward_command(context: PipelineContext) -> str:
    return (
        f"kubectl port-forward service/{context['service_name']} "
        f"{context['local_port']}:80 -n {context['namespace']}"
    )


def service_urls(context: PipelineContext) -> list[str]:
    port = context["local_port"]
    return [
        f"http://127.0.0.1:{port}/",
        f"http://127.0.0.1:{port}/health",
        f"http://127.0.0.1:{port}/checkout",
    ]


def log_access_instructions(context: PipelineContext) -> None:
    if not context.get("deploy") or not context.get("port_forward_process"):
        return

    print("\nService Access")
    print("=" * 52)
    for url in service_urls(context):
        print(f"Open: {url}")

    if context.get("keep_port_forward"):
        print("\nPort-forward is still running. Press Ctrl+C to stop it.")
    else:
        print("\nThe pipeline port-forward closes when the orchestrator exits.")
        print("To access the service after the run, start it again:")
        print(f"  {port_forward_command(context)}")


def hold_port_forward(context: PipelineContext) -> None:
    process = context.get("port_forward_process")
    if not context.get("keep_port_forward") or not process or process.poll() is not None:
        return

    try:
        process.wait()
    except KeyboardInterrupt:
        print("\nStopping port-forward.")


def run_pipeline(
    intent: str = DEFAULT_INTENT,
    namespace: str | None = None,
    deploy: bool = False,
    validate_only: bool = False,
    simulate_failure_flag: bool = False,
    dry_run: bool = False,
    apply_fixes: bool = False,
    keep_port_forward: bool = False,
) -> list[AgentResult]:
    """Run the deployment pipeline for a user intent."""
    context: PipelineContext = {
        "intent": intent,
        "namespace": namespace or kube_namespace(),
        "deploy": deploy,
        "validate_only": validate_only,
        "simulate_failure": simulate_failure_flag,
        "dry_run": dry_run,
        "apply_fixes": apply_fixes,
        "keep_port_forward": keep_port_forward,
        "service_name": service_name(),
        "local_port": local_port(),
        "deployment_target": deployment_target(),
        "slo_base_url": slo_base_url(),
        "vm_host": vm_host(),
        "vm_user": vm_user(),
        "vm_app_port": vm_app_port(),
        "docker_image": docker_image(),
        "image": f"{service_name()}:latest",
        "results": [],
        "agent_outputs": {},
    }

    log_banner(context)

    stages = [
        ("Planning Agent", run_planner_agent),
        ("Terraform Agent", run_terraform_agent),
        ("Security Agent", run_security_agent),
        ("Cost Agent", run_cost_agent),
        ("Kubernetes Agent", run_k8s_agent),
        ("Test Agent", run_test_agent),
        ("Deploy Agent", run_deploy_agent),
        ("SLO Agent", run_slo_stage),
        ("Release Notes Agent", run_release_notes_agent),
    ]

    try:
        for step_number, (stage_name, agent) in enumerate(stages, start=1):
            log_stage_banner(step_number, stage_name)
            try:
                result = agent(context)
            except Exception as exc:
                result = {
                    "agent": stage_name.lower().replace(" agent", "").replace(" ", "_"),
                    "status": "failed",
                    "summary": f"{stage_name} crashed unexpectedly.",
                    "details": [
                        f"Error: {exc}",
                        "Pipeline stopped cleanly so the failure can be reviewed.",
                    ],
                    "stop_pipeline": True,
                }
            if result["agent"] == "planner":
                align_plan_namespace(context, result)
            store_result(context, result)
            log_result(result)

            if result.get("stop_pipeline"):
                print("\nPipeline stopped cleanly.")
                print(f"Reason: {result['agent']} agent returned {result['status']}.")
                log_executive_summary(context["results"])
                return context["results"]

        log_stage_banner(10, "Rollback Agent")
        slo_result = context["agent_outputs"].get("slo", {})
        if slo_result.get("status") == "failed":
            if context["deployment_target"] == "digitalocean-vm":
                rollback_result = run_vm_rollback_agent(context)
            else:
                rollback_result = run_rollback_agent(context)
        else:
            rollback_result = {
                "agent": "rollback",
                "status": "skipped",
                "summary": "No rollback required.",
                "details": ["SLO validation did not fail."],
            }
            print("No rollback required")

        store_result(context, rollback_result)
        log_result(rollback_result)

        log_executive_summary(context["results"])
        print("\nPipeline finished.")
        print("Review docs/release-notes.md for the generated release summary.\n")
        log_access_instructions(context)
        hold_port_forward(context)
        return context["results"]
    finally:
        stop_port_forward(context)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Agentic DevOps demo pipeline.")
    parser.add_argument("--intent", default=DEFAULT_INTENT, help="User intent.")
    parser.add_argument(
        "--namespace",
        default=kube_namespace(),
        help="Kubernetes namespace for deploy and validation.",
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="Deploy to minikube and validate the live localhost endpoint.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Run planning, reviews, and tests without deploying.",
    )
    parser.add_argument(
        "--simulate-failure",
        action="store_true",
        help="After deployment, set FAIL_MODE=true before SLO validation.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Keep external validation demo-safe where supported.",
    )
    parser.add_argument(
        "--apply-fixes",
        action="store_true",
        help="Allow agents with safe fixers to modify files.",
    )
    parser.add_argument(
        "--keep-port-forward",
        action="store_true",
        help="Keep localhost access open after SLO validation until Ctrl+C.",
    )
    args = parser.parse_args()
    if args.deploy and args.validate_only:
        parser.error("--deploy and --validate-only cannot be used together.")
    return args


if __name__ == "__main__":
    args = parse_args()
    run_pipeline(
        intent=args.intent,
        namespace=args.namespace,
        deploy=args.deploy,
        validate_only=args.validate_only,
        simulate_failure_flag=args.simulate_failure,
        dry_run=args.dry_run,
        apply_fixes=args.apply_fixes,
        keep_port_forward=args.keep_port_forward,
    )
