"""Tests for the release notes agent."""

from agents import release_notes_agent


def context():
    return {
        "deployment_plan": {
            "service_name": "checkout-service",
            "namespace": "agentic-devops",
            "deployment_strategy": "rolling",
        },
        "results": [
            {"agent": "test", "status": "passed", "summary": "Tests passed."},
            {"agent": "security", "status": "warning", "summary": "Scanner missing."},
            {"agent": "k8s", "status": "passed", "summary": "Manifests reviewed."},
            {"agent": "slo", "status": "passed", "summary": "SLO passed."},
        ],
        "agent_outputs": {
            "test": {"agent": "test", "status": "passed", "summary": "Tests passed."},
            "security": {
                "agent": "security",
                "status": "warning",
                "summary": "Scanner missing.",
            },
            "k8s": {"agent": "k8s", "status": "passed", "summary": "Manifests reviewed."},
            "slo": {"agent": "slo", "status": "passed", "summary": "SLO passed."},
        },
    }


def test_release_notes_agent_uses_openai_markdown(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        release_notes_agent,
        "ask_llm",
        lambda system, user: "# Release Notes\n\n## Service\n\ncheckout-service",
    )

    result = release_notes_agent.run(context())

    assert result["status"] == "passed"
    assert "Release notes source: openai" in result["details"]
    assert (tmp_path / "docs/release-notes.md").read_text(encoding="utf-8").startswith(
        "# Release Notes"
    )


def test_release_notes_agent_falls_back_when_openai_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    def fail(system, user):
        raise RuntimeError("OPENAI_API_KEY is missing")

    monkeypatch.setattr(release_notes_agent, "ask_llm", fail)

    result = release_notes_agent.run(context())
    content = (tmp_path / "docs/release-notes.md").read_text(encoding="utf-8")

    assert result["status"] == "passed"
    assert "Release notes source: safe_defaults" in result["details"]
    assert "## Validation Summary" in content
    assert "## Risk Summary" in content
    assert "Decision: Approved" in content


def test_release_notes_decision_is_rolled_back_when_slo_failed() -> None:
    data = context()
    data["agent_outputs"]["slo"] = {
        "agent": "slo",
        "status": "failed",
        "summary": "SLO failed.",
    }

    assert release_notes_agent.deployment_decision(data) == "Rolled Back"
