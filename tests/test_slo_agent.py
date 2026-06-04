"""Tests for the SLO validation agent."""

import http.client

from agents import slo_agent


def test_slo_agent_passes_when_error_rate_and_latency_are_within_limits(monkeypatch) -> None:
    monkeypatch.setattr(slo_agent, "wait_for_readiness", lambda url: (True, "ready"))
    monkeypatch.setattr(
        slo_agent,
        "call_checkout",
        lambda url: (True, 100.0, "HTTP 200"),
    )

    result = slo_agent.run(
        {
            "deployment_plan": {
                "slo": {"max_error_rate": 0.01, "max_avg_latency_ms": 500}
            }
        }
    )

    assert result["status"] == "passed"
    assert result["success_count"] == 20
    assert result["failure_count"] == 0
    assert result["error_rate_percent"] == 0.0
    assert result["average_latency_ms"] == 100.0
    assert result["max_error_rate_percent"] == 1.0
    assert result["max_avg_latency_ms"] == 500.0


def test_slo_agent_uses_context_local_port(monkeypatch) -> None:
    readiness_urls = []
    checkout_urls = []

    def fake_wait_for_readiness(url):
        readiness_urls.append(url)
        return True, "ready"

    def fake_call_checkout(url):
        checkout_urls.append(url)
        return True, 100.0, "HTTP 200"

    monkeypatch.setattr(slo_agent, "wait_for_readiness", fake_wait_for_readiness)
    monkeypatch.setattr(slo_agent, "call_checkout", fake_call_checkout)

    result = slo_agent.run({"local_port": 18080})

    assert result["status"] == "passed"
    assert readiness_urls == ["http://127.0.0.1:18080/health"]
    assert checkout_urls == ["http://127.0.0.1:18080/checkout"] * 20


def test_slo_agent_uses_context_base_url(monkeypatch) -> None:
    readiness_urls = []
    checkout_urls = []
    monkeypatch.setattr(
        slo_agent,
        "wait_for_readiness",
        lambda url: readiness_urls.append(url) or (True, "ready"),
    )
    monkeypatch.setattr(
        slo_agent,
        "call_checkout",
        lambda url: checkout_urls.append(url) or (True, 100.0, "HTTP 200"),
    )

    result = slo_agent.run({"slo_base_url": "http://203.0.113.10:8080"})

    assert result["status"] == "passed"
    assert readiness_urls == ["http://203.0.113.10:8080/health"]
    assert checkout_urls == ["http://203.0.113.10:8080/checkout"] * 20


def test_slo_agent_builds_vm_url_from_context(monkeypatch) -> None:
    readiness_urls = []
    monkeypatch.setattr(
        slo_agent,
        "wait_for_readiness",
        lambda url: readiness_urls.append(url) or (True, "ready"),
    )
    monkeypatch.setattr(slo_agent, "call_checkout", lambda url: (True, 100.0, "HTTP 200"))

    result = slo_agent.run(
        {
            "deployment_target": "digitalocean-vm",
            "vm_host": "203.0.113.11",
            "vm_app_port": 8081,
        }
    )

    assert result["status"] == "passed"
    assert readiness_urls == ["http://203.0.113.11:8081/health"]


def test_slo_agent_fails_when_any_request_fails(monkeypatch) -> None:
    monkeypatch.setattr(slo_agent, "wait_for_readiness", lambda url: (True, "ready"))
    calls = iter([(False, 100.0, "HTTP 503")] + [(True, 100.0, "HTTP 200")] * 19)
    monkeypatch.setattr(slo_agent, "call_checkout", lambda url: next(calls))

    result = slo_agent.run({})

    assert result["status"] == "failed"
    assert result["success_count"] == 19
    assert result["failure_count"] == 1
    assert result["error_rate_percent"] == 5.0


def test_slo_agent_fails_when_average_latency_exceeds_plan(monkeypatch) -> None:
    monkeypatch.setattr(slo_agent, "wait_for_readiness", lambda url: (True, "ready"))
    monkeypatch.setattr(
        slo_agent,
        "call_checkout",
        lambda url: (True, 600.0, "HTTP 200"),
    )

    result = slo_agent.run(
        {
            "deployment_plan": {
                "slo": {"max_error_rate": 0.01, "max_avg_latency_ms": 500}
            }
        }
    )

    assert result["status"] == "failed"
    assert result["success_count"] == 20
    assert result["failure_count"] == 0
    assert result["average_latency_ms"] == 600.0


def test_slo_agent_dry_run_uses_plan_thresholds() -> None:
    result = slo_agent.run(
        {
            "dry_run": True,
            "deployment_plan": {
                "slo": {"max_error_rate": 0.02, "max_avg_latency_ms": 250}
            },
        }
    )

    assert result["status"] == "passed"
    assert result["max_error_rate_percent"] == 2.0
    assert result["max_avg_latency_ms"] == 250.0


def test_call_checkout_handles_remote_disconnect(monkeypatch) -> None:
    def disconnect(url, timeout):
        raise http.client.RemoteDisconnected(
            "Remote end closed connection without response"
        )

    monkeypatch.setattr(slo_agent.urllib.request, "urlopen", disconnect)

    success, latency_ms, note = slo_agent.call_checkout("http://localhost:8080/checkout")

    assert success is False
    assert latency_ms >= 0
    assert "Remote end closed connection without response" in note


def test_slo_agent_fails_cleanly_when_readiness_never_passes(monkeypatch) -> None:
    monkeypatch.setattr(
        slo_agent,
        "wait_for_readiness",
        lambda url: (False, "connection refused"),
    )

    result = slo_agent.run({})

    assert result["status"] == "failed"
    assert result["success_count"] == 0
    assert result["failure_count"] == 20
    assert result["error_rate_percent"] == 100.0
    assert any("Readiness failure: connection refused" in detail for detail in result["details"])
