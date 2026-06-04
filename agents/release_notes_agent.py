"""Release notes agent for the Agentic DevOps demo."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.config import service_name
from agents.llm_client import ask_llm


RELEASE_NOTES_PATH = Path("docs/release-notes.md")

SYSTEM_PROMPT = """You are a release manager writing executive-friendly release notes.
Return markdown only. Keep it concise and readable for a deployment review.
Include these sections:
- Service
- Namespace
- Deployment Strategy
- Validation Summary
- Risk Summary
- Deployment Decision"""


def result_for(context: dict[str, Any], agent_name: str) -> dict[str, Any]:
    return context.get("agent_outputs", {}).get(agent_name, {})


def deployment_decision(context: dict[str, Any]) -> str:
    rollback = result_for(context, "rollback")
    slo = result_for(context, "slo")
    failed = [
        result
        for result in context.get("results", [])
        if result.get("status") == "failed"
    ]

    if rollback.get("status") == "passed" or slo.get("status") == "failed" or failed:
        return "Rolled Back"
    return "Approved"


def release_evidence(context: dict[str, Any]) -> dict[str, Any]:
    plan = context.get("deployment_plan", {})
    return {
        "deployment_plan": plan,
        "test_result": result_for(context, "test"),
        "security_result": result_for(context, "security"),
        "k8s_review_result": result_for(context, "k8s"),
        "slo_result": result_for(context, "slo"),
        "rollback_result": result_for(context, "rollback"),
        "deployment_decision": deployment_decision(context),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def fallback_markdown(evidence: dict[str, Any]) -> str:
    plan = evidence.get("deployment_plan", {})
    release_service_name = plan.get("service_name", service_name())
    namespace = plan.get("namespace", "unknown")
    strategy = plan.get("deployment_strategy", "rolling")
    decision = evidence["deployment_decision"]
    test = evidence.get("test_result", {})
    security = evidence.get("security_result", {})
    k8s = evidence.get("k8s_review_result", {})
    slo = evidence.get("slo_result", {})
    rollback = evidence.get("rollback_result", {})

    return "\n".join(
        [
            "# Release Notes",
            "",
            f"Generated: {evidence['generated_at']}",
            "",
            "## Service",
            "",
            f"- Name: {release_service_name}",
            "",
            "## Namespace",
            "",
            f"- Namespace: {namespace}",
            "",
            "## Deployment Strategy",
            "",
            f"- Strategy: {strategy}",
            "",
            "## Validation Summary",
            "",
            f"- Tests: {test.get('status', 'unknown')} - {test.get('summary', 'No test summary.')}",
            f"- Kubernetes review: {k8s.get('status', 'unknown')} - {k8s.get('summary', 'No Kubernetes summary.')}",
            f"- SLO validation: {slo.get('status', 'unknown')} - {slo.get('summary', 'No SLO summary.')}",
            "",
            "## Risk Summary",
            "",
            f"- Security: {security.get('status', 'unknown')} - {security.get('summary', 'No security summary.')}",
            f"- Rollback: {rollback.get('status', 'skipped')} - {rollback.get('summary', 'No rollback required.')}",
            "",
            "## Deployment Decision",
            "",
            f"- Decision: {decision}",
            "",
        ]
    )


def build_user_prompt(evidence: dict[str, Any]) -> str:
    return (
        "Write release notes from this deployment evidence.\n\n"
        f"{json.dumps(evidence, indent=2, default=str)}"
    )


def run(context: dict[str, Any]) -> dict[str, Any]:
    RELEASE_NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    evidence = release_evidence(context)
    source = "openai"

    try:
        markdown = ask_llm(SYSTEM_PROMPT, build_user_prompt(evidence))
        if not markdown.strip():
            raise ValueError("OpenAI returned empty release notes.")
    except Exception as exc:
        source = "safe_defaults"
        markdown = fallback_markdown(evidence)
        fallback_reason = str(exc)
    else:
        fallback_reason = ""

    RELEASE_NOTES_PATH.write_text(markdown.strip() + "\n", encoding="utf-8")

    details = [
        f"Release notes source: {source}",
        f"Service: {evidence['deployment_plan'].get('service_name', service_name())}",
        f"Namespace: {evidence['deployment_plan'].get('namespace', 'unknown')}",
        f"Deployment decision: {evidence['deployment_decision']}",
    ]
    if fallback_reason:
        details.append(f"Fallback reason: {fallback_reason}")

    return {
        "agent": "release_notes",
        "status": "passed",
        "summary": "Wrote release notes for the checkout deployment.",
        "details": details,
        "artifacts": [str(RELEASE_NOTES_PATH)],
    }
