"""Tests for the enhanced test agent."""

from agents import test_agent


class Completed:
    def __init__(self, returncode: int = 0, stdout: str = "48 passed in 1.23s\n") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def test_test_agent_generates_runs_and_scores_tests(monkeypatch) -> None:
    pytest_called = False

    def fake_llm(system, user):
        if "API test design agent" in system:
            return {
                "scenarios": [
                    {
                        "name": "health probe",
                        "method": "GET",
                        "path": "/health",
                        "env": {"FAIL_MODE": "false"},
                        "expected_status": 200,
                        "expected_json_contains": {"status": "healthy"},
                    }
                ]
            }
        return {
            "confidence_score": 91,
            "confidence_level": "High",
            "summary": "Unit and generated API tests passed.",
            "tested": ["FastAPI health endpoint", "pytest suite"],
            "gaps": ["Live SLO validation happens later."],
        }

    monkeypatch.setattr(test_agent, "ask_llm_json", fake_llm)
    monkeypatch.setattr(
        test_agent.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("pytest should be skipped")),
    )

    result = test_agent.run({"intent": "Deploy checkout-service"})

    assert result["status"] == "passed"
    assert pytest_called is False
    assert result["pytest"]["enabled"] is False
    assert result["generated_tests"]["source"] == "openai"
    assert result["generated_tests"]["result"]["passed"] == 1
    assert result["confidence"]["confidence_score"] == 91
    assert any("Agent-generated tests: 1/1 passed" in detail for detail in result["details"])
    assert any("Pytest: skipped deterministic suite" in detail for detail in result["details"])


def test_test_agent_fails_when_generated_test_fails(monkeypatch) -> None:
    def fake_llm(system, user):
        if "API test design agent" in system:
            return {
                "scenarios": [
                    {
                        "name": "bad checkout expectation",
                        "method": "GET",
                        "path": "/checkout",
                        "env": {"FAIL_MODE": "false"},
                        "expected_status": 503,
                        "expected_json_contains": {"status": "error"},
                    }
                ]
            }
        return {
            "confidence_score": 30,
            "confidence_level": "Low",
            "summary": "Generated functional test failed.",
            "tested": ["Generated checkout scenario"],
            "gaps": ["Fix failed generated scenario."],
        }

    monkeypatch.setattr(test_agent, "ask_llm_json", fake_llm)
    monkeypatch.setattr(test_agent.subprocess, "run", lambda *args, **kwargs: Completed())

    result = test_agent.run({"intent": "Deploy checkout-service"})

    assert result["status"] == "failed"
    assert result["stop_pipeline"] is True
    assert result["generated_tests"]["result"]["passed"] == 0
    assert any("status or JSON expectation mismatch" in detail for detail in result["details"])


def test_test_agent_discovers_new_fastapi_route(monkeypatch) -> None:
    route_path = "/orders"

    async def orders():
        return {"status": "success", "resource": "orders"}

    before_count = len(test_agent.app.router.routes)
    test_agent.app.add_api_route(route_path, orders, methods=["GET"], name="orders")
    route = test_agent.app.router.routes[-1]

    def fake_llm(system, user):
        if "API test design agent" in system:
            assert route_path in user
            return {
                "scenarios": [
                    {
                        "name": "orders endpoint",
                        "method": "GET",
                        "path": route_path,
                        "env": {"FAIL_MODE": "false"},
                        "expected_status": 200,
                        "expected_json_contains": {
                            "status": "success",
                            "resource": "orders",
                        },
                    }
                ]
            }
        return {
            "confidence_score": 88,
            "confidence_level": "High",
            "summary": "Dynamic route test passed.",
            "tested": ["Generated /orders functional test"],
            "gaps": [],
        }

    monkeypatch.setattr(test_agent, "ask_llm_json", fake_llm)
    monkeypatch.setattr(test_agent.subprocess, "run", lambda *args, **kwargs: Completed())

    try:
        result = test_agent.run({"intent": "Deploy checkout-service"})
    finally:
        if route in test_agent.app.router.routes:
            test_agent.app.router.routes.remove(route)
        assert len(test_agent.app.router.routes) == before_count

    assert result["status"] == "passed"
    assert result["generated_tests"]["scenarios"][0]["path"] == route_path
    assert result["generated_tests"]["result"]["passed"] == 1


def test_test_agent_can_run_pytest_when_opted_in(monkeypatch) -> None:
    def fake_llm(system, user):
        if "API test design agent" in system:
            return {
                "scenarios": [
                    {
                        "name": "health probe",
                        "method": "GET",
                        "path": "/health",
                        "env": {"FAIL_MODE": "false"},
                        "expected_status": 200,
                        "expected_json_contains": {"status": "healthy"},
                    }
                ]
            }
        return {
            "confidence_score": 88,
            "confidence_level": "High",
            "summary": "Generated and pytest checks passed.",
            "tested": ["Generated API scenario", "Opt-in pytest suite"],
            "gaps": [],
        }

    calls = []
    monkeypatch.setattr(test_agent, "ask_llm_json", fake_llm)
    monkeypatch.setattr(
        test_agent.subprocess,
        "run",
        lambda *args, **kwargs: calls.append(args[0]) or Completed(stdout="56 passed in 1.00s\n"),
    )

    result = test_agent.run({"intent": "Deploy checkout-service", "run_pytest": True})

    assert result["status"] == "passed"
    assert result["pytest"]["enabled"] is True
    assert result["pytest"]["summary"] == "56 passed in 1.00s"
    assert calls == [[test_agent.sys.executable, "-m", "pytest", "tests/", "-q"]]


def test_test_agent_discovers_checkout_commons_route() -> None:
    routes = test_agent.discover_app_routes()

    assert {
        "method": "GET",
        "path": "/checkout-commons",
        "name": "checkout_commons",
        "purpose": "shared checkout capabilities",
    } in routes
