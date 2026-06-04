"""Fast test agent for the Agentic DevOps demo."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from fastapi.testclient import TestClient

from app.main import app
from agents.llm_client import ask_llm_json

TESTS_DIR = Path("tests")

SYSTEM_PROMPT = """You are a senior QA and release confidence analyst.

Review the executable agent-generated tests and discovered test inventory.
Classify confidence for this deployment demo.

Return only JSON:
{
  "confidence_score": number,
  "confidence_level": "Low" | "Medium" | "High",
  "summary": string,
  "tested": [string],
  "gaps": [string]
}

Rules:
- confidence_score must be 0-100.
- Keep summary under 140 characters.
- tested: max 5 concise bullets.
- gaps: max 3 concise bullets.
- If executable tests failed, confidence_score must be below 50."""

TEST_GENERATION_PROMPT = """You are an API test design agent.

Generate supplemental functional test scenarios for the FastAPI checkout service.
Return only JSON:
{
  "scenarios": [
    {
      "name": string,
      "method": "GET",
      "path": string,
      "env": {},
      "expected_status": number,
      "expected_json_contains": {}
    }
  ]
}

Rules:
- Generate 3-5 scenarios.
- Only use GET requests.
- Only test paths listed in discovered_routes.
- Include a FAIL_MODE=true scenario for /checkout only if /checkout exists.
- Do not include Python code."""


def pytest_summary(output: str) -> str:
    """Extract a concise pytest summary line from captured output."""
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped and (
            " passed" in stripped
            or " failed" in stripped
            or " error" in stripped
            or " errors" in stripped
        ):
            return stripped

    return "No pytest summary found."


def classify_test_file(path: Path) -> dict[str, str]:
    name = path.name
    content = path.read_text(encoding="utf-8")

    if name == "test_app.py":
        category = "service unit/functional"
        scope = "FastAPI metadata, health, checkout success, and FAIL_MODE error behavior."
    elif name == "test_orchestrator.py":
        category = "pipeline orchestration"
        scope = "Agent sequencing, clean stop behavior, SLO failure rollback routing."
    elif "TestClient" in content:
        category = "service functional"
        scope = "HTTP behavior through FastAPI test client."
    elif "subprocess" in content or "kubectl" in content or "minikube" in content:
        category = "agent command behavior"
        scope = "Command construction and failure handling with mocked external tools."
    elif name.startswith("test_") and name.endswith("_agent.py"):
        category = "agent unit"
        scope = f"{name.removeprefix('test_').removesuffix('.py')} logic with mocked dependencies."
    else:
        category = "unit"
        scope = "Repository Python behavior."

    return {"file": str(path), "category": category, "scope": scope}


def discover_test_inventory() -> list[dict[str, str]]:
    if not TESTS_DIR.exists():
        return []
    return [classify_test_file(path) for path in sorted(TESTS_DIR.glob("test_*.py"))]


def route_purpose(path: str, name: str) -> str:
    if path == "/":
        return "service metadata"
    if path == "/health":
        return "Kubernetes health probes"
    if path == "/checkout":
        return "mock checkout order"
    if path == "/checkout-commons":
        return "shared checkout capabilities"
    return name.replace("_", " ") or "API endpoint"


def discover_app_routes() -> list[dict[str, Any]]:
    routes = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = sorted(getattr(route, "methods", set()) or [])
        if path.startswith("/docs") or path.startswith("/redoc") or path.startswith("/openapi"):
            continue
        if "GET" not in methods:
            continue
        routes.append(
            {
                "method": "GET",
                "path": path,
                "name": getattr(route, "name", path.strip("/") or "root"),
                "purpose": route_purpose(path, getattr(route, "name", "")),
            }
        )
    return sorted(routes, key=lambda item: item["path"])


def expected_json_for_path(path: str, fail_mode: bool = False) -> dict[str, Any]:
    if path == "/":
        return {"service": "checkout-service", "status": "running"}
    if path == "/health":
        return {"status": "healthy", "service": "checkout-service"}
    if path == "/checkout" and fail_mode:
        return {"status": "error", "service": "checkout-service"}
    if path == "/checkout":
        return {"status": "success", "service": "checkout-service"}
    if path == "/checkout-commons":
        return {
            "status": "success",
            "service": "checkout-service",
            "resource": "checkout-commons",
        }
    return {}


def fallback_scenarios(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scenarios = []
    for route in routes[:5]:
        path = route["path"]
        scenarios.append(
            {
                "name": f"GET {path} returns a successful response",
                "method": "GET",
                "path": path,
                "env": {"FAIL_MODE": "false"},
                "expected_status": 200,
                "expected_json_contains": expected_json_for_path(path),
            }
        )

    if any(route["path"] == "/checkout" for route in routes):
        scenarios.append(
            {
                "name": "GET /checkout returns service error when FAIL_MODE is true",
                "method": "GET",
                "path": "/checkout",
                "env": {"FAIL_MODE": "true"},
                "expected_status": 503,
                "expected_json_contains": expected_json_for_path("/checkout", fail_mode=True),
            }
        )

    return scenarios[:5]


def app_context(context: dict[str, Any]) -> dict[str, Any]:
    routes = discover_app_routes()
    return {
        "intent": context.get("intent"),
        "deployment_plan": context.get("deployment_plan", {}),
        "service": "checkout-service",
        "discovered_routes": routes,
        "failure_mode": "FAIL_MODE=true makes /checkout return HTTP 503.",
    }


def generate_test_scenarios(context: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    routes = discover_app_routes()
    fallback = fallback_scenarios(routes)
    try:
        response = ask_llm_json(
            TEST_GENERATION_PROMPT,
            json.dumps(app_context(context), indent=2),
        )
        scenarios = normalize_scenarios(response.get("scenarios", []), routes)
        if not scenarios:
            raise ValueError("LLM returned no executable scenarios.")
        return scenarios, "openai"
    except Exception:
        return fallback, "safe fallback"


def normalize_scenarios(scenarios: Any, routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed_paths = {route["path"] for route in routes}
    normalized = []
    if not isinstance(scenarios, list):
        return normalized

    for scenario in scenarios[:5]:
        if not isinstance(scenario, dict):
            continue
        if scenario.get("method") != "GET" or scenario.get("path") not in allowed_paths:
            continue
        expected_status = scenario.get("expected_status")
        if not isinstance(expected_status, int):
            continue
        expected_json = scenario.get("expected_json_contains", {})
        if not isinstance(expected_json, dict):
            expected_json = {}
        env = scenario.get("env", {})
        if not isinstance(env, dict):
            env = {}
        normalized.append(
            {
                "name": str(scenario.get("name") or f"GET {scenario['path']}"),
                "method": "GET",
                "path": scenario["path"],
                "env": {str(key): str(value) for key, value in env.items()},
                "expected_status": expected_status,
                "expected_json_contains": expected_json,
            }
        )

    return normalized


def json_contains(body: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(body.get(key) == value for key, value in expected.items())


def run_generated_tests(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    client = TestClient(app)
    env_keys = {"FAIL_MODE"}
    env_keys.update(key for scenario in scenarios for key in scenario["env"])
    previous_env = {key: os.environ.get(key) for key in env_keys}
    results = []

    try:
        for scenario in scenarios:
            effective_env = {"FAIL_MODE": "false", **scenario["env"]}
            for key, value in effective_env.items():
                os.environ[key] = value

            response = client.get(scenario["path"])
            try:
                body = response.json()
            except ValueError:
                body = {}

            status_ok = response.status_code == scenario["expected_status"]
            body_ok = json_contains(body, scenario["expected_json_contains"])
            passed = status_ok and body_ok
            results.append(
                {
                    "name": scenario["name"],
                    "path": scenario["path"],
                    "expected_status": scenario["expected_status"],
                    "actual_status": response.status_code,
                    "passed": passed,
                    "message": "passed" if passed else "status or JSON expectation mismatch",
                }
            )
    finally:
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    passed_count = sum(1 for result in results if result["passed"])
    return {
        "status": "passed" if passed_count == len(results) else "failed",
        "passed": passed_count,
        "total": len(results),
        "results": results,
    }


def inventory_summary(inventory: list[dict[str, str]]) -> list[str]:
    categories: dict[str, int] = {}
    for item in inventory:
        categories[item["category"]] = categories.get(item["category"], 0) + 1

    return [f"{category}: {count} file(s)" for category, count in sorted(categories.items())]


def fallback_confidence(status: str, summary: str, inventory: list[dict[str, str]]) -> dict[str, Any]:
    if status == "failed":
        return {
            "confidence_score": 35,
            "confidence_level": "Low",
            "summary": "Tests failed, so deployment confidence is low.",
            "tested": inventory_summary(inventory)[:5],
            "gaps": ["Fix failing tests before deployment."],
        }

    score = 82
    if any(item["category"] == "service unit/functional" for item in inventory):
        score += 5
    if any(item["category"] == "pipeline orchestration" for item in inventory):
        score += 3
    score = min(score, 90)

    return {
        "confidence_score": score,
        "confidence_level": "High" if score >= 80 else "Medium",
        "summary": f"Agent-generated functional tests passed: {summary}",
        "tested": inventory_summary(inventory)[:5],
        "gaps": [
            "Live Kubernetes behavior is validated later by deploy and SLO agents.",
            "Browser/UI testing is not applicable for this API-only service.",
        ],
    }


def ask_confidence_assessment(
    status: str,
    summary: str,
    output: str,
    inventory: list[dict[str, str]],
    generated_test_result: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "test_status": status,
        "test_summary": summary,
        "test_output_excerpt": output[-2500:],
        "agent_generated_functional_tests": generated_test_result,
        "test_inventory": inventory,
        "deployment_plan": context.get("deployment_plan", {}),
        "intent": context.get("intent"),
    }
    return ask_llm_json(SYSTEM_PROMPT, json.dumps(payload, indent=2))


def normalize_confidence(assessment: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        score = int(assessment.get("confidence_score", fallback["confidence_score"]))
    except (TypeError, ValueError):
        score = fallback["confidence_score"]
    score = max(0, min(score, 100))

    level = assessment.get("confidence_level", fallback["confidence_level"])
    if level not in {"Low", "Medium", "High"}:
        level = fallback["confidence_level"]

    tested = assessment.get("tested")
    gaps = assessment.get("gaps")
    return {
        "confidence_score": score,
        "confidence_level": level,
        "summary": str(assessment.get("summary") or fallback["summary"]),
        "tested": [str(item) for item in tested[:5]] if isinstance(tested, list) else fallback["tested"],
        "gaps": [str(item) for item in gaps[:3]] if isinstance(gaps, list) else fallback["gaps"],
    }


def should_run_pytest(context: dict[str, Any]) -> bool:
    if "run_pytest" in context:
        return bool(context["run_pytest"])
    return os.getenv("TEST_AGENT_RUN_PYTEST", "false").lower() == "true"


def run_pytest_suite() -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "tests/", "-q"]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    output = (completed.stdout + completed.stderr).strip()
    summary = pytest_summary(output)
    return {
        "enabled": True,
        "command": command,
        "exit_code": completed.returncode,
        "status": "passed" if completed.returncode == 0 else "failed",
        "summary": summary,
        "output": output,
    }


def skipped_pytest_suite() -> dict[str, Any]:
    return {
        "enabled": False,
        "command": [],
        "exit_code": None,
        "status": "skipped",
        "summary": "Skipped deterministic pytest suite in fast demo mode.",
        "output": "",
    }


def run(context: dict[str, Any]) -> dict[str, Any]:
    inventory = discover_test_inventory()
    discovered_routes = discover_app_routes()
    scenarios, scenario_source = generate_test_scenarios(context)
    generated_result = run_generated_tests(scenarios)
    pytest_result = run_pytest_suite() if should_run_pytest(context) else skipped_pytest_suite()

    status = "passed" if generated_result["status"] == "passed" else "failed"
    if pytest_result["enabled"] and pytest_result["status"] == "failed":
        status = "failed"

    summary = (
        f"{generated_result['passed']}/{generated_result['total']} generated tests passed"
    )
    if pytest_result["enabled"]:
        summary = f"{summary}; pytest {pytest_result['summary']}"

    output = pytest_result["output"]
    fallback = fallback_confidence(status, summary, inventory)

    try:
        confidence = normalize_confidence(
            ask_confidence_assessment(
                status,
                summary,
                output,
                inventory,
                generated_result,
                context,
            ),
            fallback,
        )
        confidence_source = "openai"
    except Exception as exc:
        confidence = fallback
        confidence_source = "safe fallback"
        confidence["gaps"] = [*confidence["gaps"][:2], f"LLM assessment unavailable: {exc}"]

    details = [
        (
            "Agent-generated tests: "
            f"{generated_result['passed']}/{generated_result['total']} passed ({scenario_source})"
        ),
        "Pytest: skipped deterministic suite in fast demo mode"
        if not pytest_result["enabled"]
        else f"Pytest command: {' '.join(pytest_result['command'])}",
        f"Pytest result: {pytest_result['summary']}",
        f"Test files discovered: {len(inventory)}",
        f"App routes discovered: {len(discovered_routes)}",
    ]
    if pytest_result["enabled"]:
        details.insert(3, f"Pytest exit code: {pytest_result['exit_code']}")
    details.extend(
        f"Discovered route: {route['method']} {route['path']} ({route['purpose']})"
        for route in discovered_routes[:5]
    )
    details.extend(
        f"Generated test: {result['name']} - {result['message']}"
        for result in generated_result["results"][:5]
    )
    details.extend(f"Coverage type: {item}" for item in inventory_summary(inventory)[:4])
    details.extend(f"Tested: {item}" for item in confidence["tested"][:4])
    details.append(
        f"Confidence: {confidence['confidence_score']}/100 ({confidence['confidence_level']}, {confidence_source})"
    )
    details.extend(f"Gap: {item}" for item in confidence["gaps"][:3])

    return {
        "agent": "test",
        "status": status,
        "summary": (
            f"Executable test validation {status}: {summary}. "
            f"Confidence {confidence['confidence_score']}/100 ({confidence['confidence_level']})."
        ),
        "details": details,
        "output": output,
        "pytest": pytest_result,
        "test_inventory": inventory,
        "discovered_routes": discovered_routes,
        "generated_tests": {
            "source": scenario_source,
            "scenarios": scenarios,
            "result": generated_result,
        },
        "confidence": confidence,
        "stop_pipeline": status == "failed",
    }
