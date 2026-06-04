"""Tests for the mock agent orchestrator."""

import subprocess
import sys

from agents.orchestrator import (
    DEFAULT_INTENT,
    ensure_port_forward_for_slo,
    generate_executive_summary,
    log_executive_summary,
    port_forward_command,
    run_deploy_agent,
    run_pipeline,
    run_slo_stage,
    wait_for_port_forward_ready,
)


def fake_test_agent(context):
    return {
        "agent": "test",
        "status": "passed",
        "summary": "Mocked pytest run for orchestrator unit tests.",
        "details": ["Command: mocked"],
        "stop_pipeline": False,
    }


def fake_security_agent(context):
    return {
        "agent": "security",
        "status": "passed",
        "summary": "Mocked security scan for orchestrator unit tests.",
        "details": ["Security mocked"],
    }


def fake_k8s_agent(context):
    return {
        "agent": "k8s",
        "status": "passed",
        "summary": "Mocked Kubernetes review for orchestrator unit tests.",
        "details": ["Kubernetes mocked"],
    }


def failing_test_agent(context):
    return {
        "agent": "test",
        "status": "failed",
        "summary": "Mocked pytest failure for orchestrator unit tests.",
        "details": ["Command: mocked"],
        "stop_pipeline": True,
    }


def passing_slo_agent(context):
    return {
        "agent": "slo",
        "status": "passed",
        "summary": "Mocked SLO pass for orchestrator unit tests.",
        "details": ["SLO mocked"],
    }


def fake_deploy_agent(context):
    return {
        "agent": "deploy",
        "status": "passed",
        "summary": "Mocked deploy for orchestrator unit tests.",
        "details": ["Deploy mocked"],
    }


def failing_deploy_agent(context):
    return {
        "agent": "deploy",
        "status": "failed",
        "summary": "Mocked deploy failure for orchestrator unit tests.",
        "details": ["Deploy mocked"],
        "stop_pipeline": True,
    }


def failing_slo_agent(context):
    return {
        "agent": "slo",
        "status": "failed",
        "summary": "Mocked SLO failure for orchestrator unit tests.",
        "details": ["SLO mocked"],
    }


def fake_rollback_agent(context):
    return {
        "agent": "rollback",
        "status": "passed",
        "summary": "Mocked rollback for orchestrator unit tests.",
        "details": ["Rollback mocked"],
    }


def test_pipeline_runs_happy_path_agents(monkeypatch) -> None:
    monkeypatch.setattr("agents.orchestrator.run_security_agent", fake_security_agent)
    monkeypatch.setattr("agents.orchestrator.run_k8s_agent", fake_k8s_agent)
    monkeypatch.setattr("agents.orchestrator.run_test_agent", fake_test_agent)
    monkeypatch.setattr("agents.orchestrator.run_deploy_agent", fake_deploy_agent)
    monkeypatch.setattr("agents.orchestrator.run_slo_agent", passing_slo_agent)
    monkeypatch.setattr("agents.orchestrator.ensure_port_forward_for_slo", lambda context: None)

    results = run_pipeline(DEFAULT_INTENT, deploy=True)

    assert [result["agent"] for result in results] == [
        "planner",
        "terraform",
        "security",
        "cost",
        "k8s",
        "test",
        "deploy",
        "slo",
        "release_notes",
        "rollback",
    ]
    assert results[-1]["status"] == "skipped"


def test_pipeline_runs_rollback_when_slo_fails(monkeypatch) -> None:
    monkeypatch.setattr("agents.orchestrator.run_security_agent", fake_security_agent)
    monkeypatch.setattr("agents.orchestrator.run_k8s_agent", fake_k8s_agent)
    monkeypatch.setattr("agents.orchestrator.run_test_agent", fake_test_agent)
    monkeypatch.setattr("agents.orchestrator.run_deploy_agent", fake_deploy_agent)
    monkeypatch.setattr("agents.orchestrator.run_slo_agent", failing_slo_agent)
    monkeypatch.setattr("agents.orchestrator.run_rollback_agent", fake_rollback_agent)
    monkeypatch.setattr("agents.orchestrator.ensure_port_forward_for_slo", lambda context: None)

    results = run_pipeline(DEFAULT_INTENT, deploy=True)

    assert results[-1]["agent"] == "rollback"
    assert results[-1]["status"] == "passed"


def test_pipeline_stops_cleanly_when_tests_fail(monkeypatch) -> None:
    monkeypatch.setattr("agents.orchestrator.run_security_agent", fake_security_agent)
    monkeypatch.setattr("agents.orchestrator.run_k8s_agent", fake_k8s_agent)
    monkeypatch.setattr("agents.orchestrator.run_test_agent", failing_test_agent)

    results = run_pipeline(DEFAULT_INTENT)

    assert results[-1]["agent"] == "test"
    assert results[-1]["status"] == "failed"
    assert "slo" not in [result["agent"] for result in results]


def test_pipeline_stops_cleanly_when_deploy_fails(monkeypatch) -> None:
    monkeypatch.setattr("agents.orchestrator.run_security_agent", fake_security_agent)
    monkeypatch.setattr("agents.orchestrator.run_k8s_agent", fake_k8s_agent)
    monkeypatch.setattr("agents.orchestrator.run_test_agent", fake_test_agent)
    monkeypatch.setattr("agents.orchestrator.run_deploy_agent", failing_deploy_agent)

    results = run_pipeline(DEFAULT_INTENT, deploy=True)

    assert results[-1]["agent"] == "deploy"
    assert results[-1]["status"] == "failed"
    assert "slo" not in [result["agent"] for result in results]


def test_port_forward_command_targets_service_port() -> None:
    command = port_forward_command(
        {
            "service_name": "checkout-service",
            "local_port": 8080,
            "namespace": "agentic-devops",
        }
    )

    assert command == (
        "kubectl port-forward service/checkout-service "
        "8080:80 -n agentic-devops"
    )


def test_wait_for_port_forward_ready_uses_kubectl_listener_output(monkeypatch) -> None:
    monkeypatch.setattr("agents.orchestrator.local_port_is_listening", lambda port: True)
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import time\n"
                "print('Forwarding from 127.0.0.1:8080 -> 80', flush=True)\n"
                "time.sleep(1)\n"
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        wait_for_port_forward_ready({"local_port": 8080}, process, timeout_seconds=2)
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_ensure_port_forward_for_slo_restarts_dead_process(monkeypatch) -> None:
    dead_process = subprocess.Popen(
        [sys.executable, "-c", "print('port-forward died')"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    dead_process.wait(timeout=5)
    restarted = []

    def fake_start_port_forward(context):
        restarted.append(context["local_port"])
        return "new-process"

    monkeypatch.setattr("agents.orchestrator.start_port_forward", fake_start_port_forward)

    context = {
        "deploy": True,
        "validate_only": False,
        "local_port": 8080,
        "port_forward_process": dead_process,
    }

    ensure_port_forward_for_slo(context)

    assert restarted == [8080]
    assert context["port_forward_process"] == "new-process"


def test_run_slo_stage_retries_once_after_readiness_failure(monkeypatch) -> None:
    calls = iter(
        [
            {
                "agent": "slo",
                "status": "failed",
                "summary": "SLO validation could not reach the local health endpoint.",
                "details": ["Readiness failure: connection refused"],
            },
            {
                "agent": "slo",
                "status": "passed",
                "summary": "Validated /checkout against demo SLO rules.",
                "details": ["Readiness endpoint: ready"],
            },
        ]
    )
    actions = []

    monkeypatch.setattr("agents.orchestrator.ensure_port_forward_for_slo", lambda context: actions.append("ensure"))
    monkeypatch.setattr("agents.orchestrator.stop_port_forward", lambda context: actions.append("stop"))
    monkeypatch.setattr(
        "agents.orchestrator.start_port_forward",
        lambda context: actions.append("start") or "restarted-process",
    )
    monkeypatch.setattr("agents.orchestrator.run_slo_agent", lambda context: next(calls))

    context = {"deploy": True, "validate_only": False, "port_forward_process": "old-process"}

    result = run_slo_stage(context)

    assert result["status"] == "passed"
    assert actions == ["ensure", "stop", "start"]
    assert context["port_forward_process"] == "restarted-process"
    assert result["details"][0] == "SLO retry: restarted local port-forward after readiness failure."


def test_digitalocean_deploy_routes_to_vm_agent(monkeypatch) -> None:
    calls = []

    def fake_vm_deploy(context):
        calls.append(context["deployment_target"])
        return {
            "agent": "deploy",
            "status": "passed",
            "summary": "VM deploy",
            "details": ["Deployment target: digitalocean-vm"],
        }

    monkeypatch.setattr("agents.orchestrator.run_vm_deploy_agent", fake_vm_deploy)
    monkeypatch.setattr(
        "agents.orchestrator.deploy_agent.ensure_minikube_running",
        lambda: (_ for _ in ()).throw(AssertionError("minikube should not be called")),
    )

    result = run_deploy_agent(
        {
            "deployment_target": "digitalocean-vm",
            "validate_only": False,
            "deploy": True,
        }
    )

    assert result["status"] == "passed"
    assert calls == ["digitalocean-vm"]


def test_digitalocean_slo_does_not_start_port_forward(monkeypatch) -> None:
    monkeypatch.setattr(
        "agents.orchestrator.ensure_port_forward_for_slo",
        lambda context: (_ for _ in ()).throw(AssertionError("port-forward should not start")),
    )
    monkeypatch.setattr(
        "agents.orchestrator.run_slo_agent",
        lambda context: {
            "agent": "slo",
            "status": "passed",
            "summary": "VM SLO passed",
            "details": [context["slo_base_url"]],
        },
    )

    result = run_slo_stage(
        {
            "deployment_target": "digitalocean-vm",
            "deploy": True,
            "validate_only": False,
            "slo_base_url": "http://203.0.113.10:8080",
        }
    )

    assert result["status"] == "passed"
    assert result["details"] == ["http://203.0.113.10:8080"]


def test_executive_summary_uses_llm_reasoning(monkeypatch, capsys) -> None:
    def fake_ask_llm(system_prompt, user_prompt):
        assert "Agentic DevOps deployment" in system_prompt
        assert "deployment_decision" in user_prompt
        assert "agent_reasoning_trace" in user_prompt
        return (
            "Decision: Approved\n"
            "The agents planned the rollout, validated controls, and approved release."
        )

    monkeypatch.setattr("agents.orchestrator.ask_llm", fake_ask_llm)

    log_executive_summary(
        [
            {
                "agent": "planner",
                "status": "passed",
                "summary": "Planned a rolling checkout deployment.",
                "details": ["Strategy: rolling"],
            },
            {
                "agent": "deploy",
                "status": "passed",
                "summary": "Deployed checkout-service to minikube.",
                "details": ["Rollout completed"],
            },
        ]
    )

    output = capsys.readouterr().out

    assert "Summary source: openai" in output
    assert "The agents planned the rollout" in output
    assert "Human effort: 2-3 days" not in output
    assert "Agentic pipeline: 15 minutes" not in output


def test_executive_summary_falls_back_when_llm_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "agents.orchestrator.ask_llm",
        lambda system_prompt, user_prompt: (_ for _ in ()).throw(RuntimeError("no key")),
    )

    summary, source = generate_executive_summary(
        [
            {
                "agent": "deploy",
                "status": "failed",
                "summary": "Deployment to minikube failed.",
                "details": ["minikube unavailable"],
            }
        ]
    )

    assert source.startswith("safe_defaults")
    assert "Decision: Rolled Back" in summary
    assert "Automated decision:" in summary
