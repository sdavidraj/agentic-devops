"""Tests for the planner agent."""

from agents import planner_agent


def test_planner_uses_openai_plan(monkeypatch) -> None:
    plan = planner_agent.safe_default_plan()
    plan["namespace"] = "agentic-devops"
    plan["repo_observations"] = [
        "Deployment manifest uses checkout-service:latest with imagePullPolicy Never.",
        "Service exposes port 80 to the checkout container on port 8080.",
    ]
    monkeypatch.setattr(planner_agent, "ask_llm_json", lambda system, user: plan)

    context = {}
    result = planner_agent.run(context)

    assert result["status"] == "passed"
    assert result["plan"] == plan
    assert context["deployment_plan"] == plan
    assert "Plan source: openai" in result["details"]
    assert any("Observation:" in detail for detail in result["details"])


def test_planner_falls_back_to_safe_defaults_when_openai_fails(monkeypatch) -> None:
    monkeypatch.setenv("KUBE_NAMESPACE", "agentic-checkout")

    def fail(system, user):
        raise RuntimeError("OPENAI_API_KEY is missing")

    monkeypatch.setattr(planner_agent, "ask_llm_json", fail)

    result = planner_agent.run({})

    assert result["status"] == "passed"
    assert result["plan"] == planner_agent.safe_default_plan()
    assert "Plan source: safe_defaults" in result["details"]


def test_planner_falls_back_when_openai_plan_is_invalid(monkeypatch) -> None:
    monkeypatch.setenv("KUBE_NAMESPACE", "agentic-checkout")
    monkeypatch.setattr(planner_agent, "ask_llm_json", lambda system, user: {"bad": "plan"})

    result = planner_agent.run({})

    assert result["plan"] == planner_agent.safe_default_plan()
    assert "Plan source: safe_defaults" in result["details"]


def test_planner_prompt_includes_repo_configuration(monkeypatch) -> None:
    captured = {}
    plan = planner_agent.safe_default_plan()

    def fake_llm(system, user):
        captured["system"] = system
        captured["user"] = user
        return plan

    monkeypatch.setattr(planner_agent, "ask_llm_json", fake_llm)

    planner_agent.run({"intent": "Deploy checkout-service to local minikube"})

    assert "repository context" in captured["system"]
    assert "checkout-service" in captured["user"]
    assert "LOCAL_PORT" in captured["user"]
    assert "image_pull_policy" in captured["user"]
    assert "terraform" in captured["user"]


def test_planner_safe_defaults_support_digitalocean_vm(monkeypatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_TARGET", "digitalocean-vm")

    plan = planner_agent.safe_default_plan()

    assert plan["deployment_target"] == "digitalocean-vm"
    assert "digitalocean_terraform_review" in plan["checks"]
    assert any("SSH" in step for step in plan["execution_plan"])
    assert "DigitalOcean" in " ".join(plan["repo_observations"])
