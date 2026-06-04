"""SLO validation agent for the Agentic DevOps demo."""

from __future__ import annotations

import time
import http.client
import urllib.error
import urllib.request
from typing import Any

from agents.config import deployment_target, local_port, slo_base_url, vm_app_port, vm_host

REQUEST_COUNT = 20
TIMEOUT_SECONDS = 2
READINESS_TIMEOUT_SECONDS = 30
MAX_ERROR_RATE_PERCENT = 1.0
MAX_AVERAGE_LATENCY_MS = 500.0


def checkout_url() -> str:
    return f"http://127.0.0.1:{local_port()}/checkout"


def health_url() -> str:
    return f"http://127.0.0.1:{local_port()}/health"


def endpoint_url(port: int, path: str) -> str:
    return f"http://127.0.0.1:{port}{path}"


def base_url_for_context(context: dict[str, Any]) -> str:
    context_url = str(context.get("slo_base_url") or "").rstrip("/")
    if context_url:
        return context_url

    env_url = slo_base_url()
    if env_url:
        return env_url

    target = str(context.get("deployment_target") or deployment_target()).lower()
    if target == "digitalocean-vm":
        host = str(context.get("vm_host") or vm_host()).strip()
        port = int(context.get("vm_app_port") or vm_app_port())
        if host:
            return f"http://{host}:{port}"

    port = int(context.get("local_port", local_port()))
    return f"http://127.0.0.1:{port}"


def call_checkout(url: str) -> tuple[bool, float, str]:
    """Call the checkout endpoint once and return success, latency, and note."""
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            latency_ms = (time.perf_counter() - started) * 1000
            if response.status == 200:
                return True, latency_ms, "HTTP 200"
            return False, latency_ms, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        return False, latency_ms, f"HTTP {exc.code}"
    except (
        urllib.error.URLError,
        TimeoutError,
        http.client.HTTPException,
        OSError,
    ) as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        return False, latency_ms, f"request failed: {exc}"


def wait_for_readiness(url: str, timeout_seconds: int = READINESS_TIMEOUT_SECONDS) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout_seconds
    last_error = "not checked"

    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
                if response.status == 200:
                    return True, "ready"
                last_error = f"HTTP {response.status}"
        except (
            urllib.error.URLError,
            TimeoutError,
            http.client.HTTPException,
            OSError,
        ) as exc:
            last_error = str(exc)

        time.sleep(1)

    return False, last_error


def print_slo_report(report: dict[str, Any]) -> None:
    """Print a compact report for live demos."""
    print("\nSLO Report")
    print("----------")
    print(f"Endpoint: {report['endpoint']}")
    print(f"Requests: {report['request_count']}")
    print(f"Successes: {report['success_count']}")
    print(f"Failures: {report['failure_count']}")
    print(
        "Error rate: "
        f"{report['error_rate_percent']}% "
        f"(threshold <= {report['max_error_rate_percent']}%)"
    )
    print(
        "Average latency: "
        f"{report['average_latency_ms']}ms "
        f"(threshold <= {report['max_avg_latency_ms']}ms)"
    )
    print(f"Status: {report['status'].upper()}")


def slo_thresholds(context: dict[str, Any]) -> tuple[float, float]:
    """Return plan-driven SLO thresholds as error percent and latency ms."""
    plan_slo = context.get("deployment_plan", {}).get("slo", {})
    max_error_rate = plan_slo.get("max_error_rate", MAX_ERROR_RATE_PERCENT / 100)
    max_avg_latency_ms = plan_slo.get("max_avg_latency_ms", MAX_AVERAGE_LATENCY_MS)

    return float(max_error_rate) * 100, float(max_avg_latency_ms)


def run(context: dict[str, Any]) -> dict[str, Any]:
    max_error_rate_percent, max_avg_latency_ms = slo_thresholds(context)

    base_url = base_url_for_context(context)
    url = f"{base_url}/checkout"
    readiness_url = f"{base_url}/health"

    if context.get("dry_run"):
        report: dict[str, Any] = {
            "agent": "slo",
            "status": "passed",
            "summary": "Dry-run SLO validation passed without calling localhost.",
            "endpoint": url,
            "request_count": REQUEST_COUNT,
            "success_count": REQUEST_COUNT,
            "failure_count": 0,
            "error_rate_percent": 0.0,
            "average_latency_ms": 0.0,
            "max_error_rate_percent": max_error_rate_percent,
            "max_avg_latency_ms": max_avg_latency_ms,
            "details": [
                "Dry-run mode enabled for CI.",
                f"Would call {url} {REQUEST_COUNT} times.",
                (
                    "Rules: error rate <= "
                    f"{max_error_rate_percent}%, average latency <= "
                    f"{max_avg_latency_ms}ms."
                ),
            ],
        }
        print_slo_report(report)
        return report

    ready, readiness_note = wait_for_readiness(readiness_url)
    if not ready:
        report = {
            "agent": "slo",
            "status": "failed",
            "summary": "SLO validation could not reach the local health endpoint.",
            "endpoint": url,
            "readiness_endpoint": readiness_url,
            "request_count": REQUEST_COUNT,
            "success_count": 0,
            "failure_count": REQUEST_COUNT,
            "error_rate_percent": 100.0,
            "average_latency_ms": 0.0,
            "max_error_rate_percent": max_error_rate_percent,
            "max_avg_latency_ms": max_avg_latency_ms,
            "details": [
                f"Readiness endpoint: {readiness_url}",
                f"Readiness wait: {READINESS_TIMEOUT_SECONDS}s",
                f"Readiness failure: {readiness_note}",
                "Check: kubectl port-forward service/checkout-service 8080:80 -n agentic-devops",
            ],
        }
        print_slo_report(report)
        return report

    results = [call_checkout(url) for _ in range(REQUEST_COUNT)]

    success_count = sum(1 for success, _, _ in results if success)
    failure_count = REQUEST_COUNT - success_count
    error_rate_percent = round((failure_count / REQUEST_COUNT) * 100, 2)
    average_latency_ms = round(
        sum(latency_ms for _, latency_ms, _ in results) / REQUEST_COUNT,
        2,
    )

    passed = (
        error_rate_percent <= max_error_rate_percent
        and average_latency_ms <= max_avg_latency_ms
    )

    failure_notes = [note for success, _, note in results if not success]
    report: dict[str, Any] = {
        "agent": "slo",
        "status": "passed" if passed else "failed",
        "summary": "Validated /checkout against demo SLO rules.",
        "endpoint": url,
        "request_count": REQUEST_COUNT,
        "success_count": success_count,
        "failure_count": failure_count,
        "error_rate_percent": error_rate_percent,
        "average_latency_ms": average_latency_ms,
        "max_error_rate_percent": max_error_rate_percent,
        "max_avg_latency_ms": max_avg_latency_ms,
        "details": [
            f"Readiness endpoint: {readiness_url} ({readiness_note})",
            f"Endpoint: {url}",
            f"Requests: {REQUEST_COUNT}",
            f"Success count: {success_count}",
            f"Failure count: {failure_count}",
            f"Error rate: {error_rate_percent}% <= {max_error_rate_percent}%",
            f"Average latency: {average_latency_ms}ms <= {max_avg_latency_ms}ms",
        ],
    }

    if failure_notes:
        report["details"].append(f"Failure samples: {', '.join(failure_notes[:3])}")

    print_slo_report(report)
    return report
