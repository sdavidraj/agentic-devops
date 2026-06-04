"""Tests for the FinOps cost agent."""

import subprocess

from agents import cost_agent


def test_manifest_inputs_extracts_kubernetes_and_terraform_values() -> None:
    inputs = cost_agent.manifest_inputs(
        {
            "deployment_plan": {
                "namespace": "agentic-devops",
                "service_name": "checkout-service",
                "replicas": 2,
            }
        }
    )

    assert inputs["namespace"] == "agentic-devops"
    assert inputs["deployment_target"] == "minikube"
    assert inputs["service_name"] == "checkout-service"
    assert inputs["replica_count"] == 2
    assert inputs["cpu_requests"] == "100m"
    assert inputs["cpu_limits"] == "500m"
    assert inputs["memory_requests"] == "128Mi"
    assert inputs["memory_limits"] == "256Mi"
    assert inputs["autoscaling"] == {"min_replicas": 2, "max_replicas": 5}
    assert "e2-medium" in inputs["vm_machine_types"]


def test_cost_agent_uses_openai_response(monkeypatch) -> None:
    monkeypatch.setattr(
        cost_agent,
        "ask_llm_json",
        lambda system, user: {
            "estimated_monthly_cost_range": {"low": 25, "high": 45},
            "cost_drivers": ["2 replicas", "CPU requests"],
            "optimization_opportunities": ["Reduce CPU request"],
            "risk_level": "Low",
            "executive_summary": "Small workload.",
            "waste_percentage": 15,
            "potential_savings": 8,
            "recommendations": ["Right-size requests"],
        },
    )

    result = cost_agent.run(
        {
            "deployment_target": "gke",
            "deployment_plan": {"namespace": "agentic-devops"},
        }
    )

    assert result["status"] == "passed"
    assert result["monthly_cost_range"] == {"low": 25.0, "high": 45.0}
    assert result["waste_percentage"] == 15.0
    assert result["potential_savings"] == 8.0
    assert result["risk_level"] == "Low"


def test_cost_agent_falls_back_when_openai_fails(monkeypatch) -> None:
    def fail(system, user):
        raise RuntimeError("OPENAI_API_KEY is missing")

    monkeypatch.setattr(cost_agent, "ask_llm_json", fail)

    result = cost_agent.run(
        {
            "deployment_target": "gke",
            "deployment_plan": {"namespace": "agentic-devops"},
        }
    )

    assert result["status"] == "passed"
    assert result["monthly_cost_range"]["low"] > 0
    assert result["recommendations"]
    assert any("Fallback reason" in detail for detail in result["details"])


def test_cost_agent_minikube_uses_target_specific_llm_and_sanitizes_cloud_terms(monkeypatch) -> None:
    calls = []

    def fake_llm(system, user):
        calls.append((system, user))
        return {
            "estimated_monthly_cost_range": {"low": 30, "high": 85},
            "cost_drivers": [
                {"driver": "GKE node compute", "notes": "cloud only"},
                {"driver": "2 local replicas", "notes": "local node pressure"},
            ],
            "optimization_opportunities": [
                {"area": "Load balancer", "suggestion": "remove cloud LB"},
                {"area": "Requests", "suggestion": "right-size CPU for local minikube"},
            ],
            "risk_level": "Medium",
            "executive_summary": "GKE node costs dominate this deployment.",
            "waste_percentage": 20,
            "potential_savings": 12,
            "recommendations": [
                {"message": "Use kubectl top pods for local right-sizing."},
                {"message": "Reduce GKE node pool size."},
            ],
        }

    monkeypatch.setattr(cost_agent, "ask_llm_json", fake_llm)

    result = cost_agent.run(
        {
            "deployment_target": "minikube",
            "deployment_plan": {"namespace": "agentic-devops"},
        }
    )

    assert calls
    assert "local minikube" in calls[0][0]
    assert result["monthly_cost_range"] == {"low": 0, "high": 0}
    assert result["potential_savings"] == 0
    assert "GKE" not in " ".join(result["cost_drivers"])
    assert "Load balancer" not in " ".join(result["optimization_opportunities"])
    assert "GKE" not in result["executive_summary"]


def test_normalize_response_formats_dict_items() -> None:
    fallback = cost_agent.minikube_estimate(
        {"replica_count": 2, "autoscaling": {}, "cpu_requests": "100m", "memory_requests": "128Mi"},
        {"recommendations": [], "waste_percentage": 0, "potential_savings": 0},
    )

    result = cost_agent.normalize_response(
        {
            "estimated_monthly_cost_range": {"low": 10, "high": 20},
            "cost_drivers": [{"driver": "GKE node", "notes": "Not relevant to minikube"}],
            "optimization_opportunities": [
                {"area": "Requests", "suggestion": "Right-size CPU"}
            ],
            "recommendations": [{"message": "Use metrics"}],
        },
        fallback,
    )

    assert result["cost_drivers"] == ["GKE node - Not relevant to minikube"]
    assert result["optimization_opportunities"] == ["Requests - Right-size CPU"]
    assert result["recommendations"] == ["Use metrics"]


def test_waste_analysis_compares_requests_to_top_pod_usage() -> None:
    inputs = {"cpu_request_millicores": 500, "memory_request_mib": 256}
    live = {
        "pod_usage": [
            {"pod": "checkout-1", "cpu_millicores": 100, "memory_mib": 128},
            {"pod": "checkout-2", "cpu_millicores": 150, "memory_mib": 128},
        ]
    }

    result = cost_agent.waste_analysis(inputs, live)

    assert result["waste_percentage"] == 75.0
    assert result["potential_savings"] == 33.75


def test_collect_live_inputs_runs_kubectl_commands(monkeypatch) -> None:
    calls = []

    def fake_run_command(command):
        calls.append(command)
        if command[:3] == ["kubectl", "top", "pods"]:
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="NAME CPU(cores) MEMORY(bytes)\npod-a 50m 64Mi\n",
                stderr="",
            )
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(cost_agent, "run_command", fake_run_command)

    result = cost_agent.collect_live_inputs("agentic-devops", should_collect=True)

    assert result["collected"] is True
    assert len(calls) == 3
    assert result["pod_usage"] == [
        {"pod": "pod-a", "cpu_millicores": 50, "memory_mib": 64}
    ]
