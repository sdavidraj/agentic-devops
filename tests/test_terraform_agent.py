"""Tests for the IaC/Terraform agent."""

from agents import terraform_agent


def test_terraform_agent_uses_openai_for_local_minikube(monkeypatch) -> None:
    monkeypatch.setattr(
        terraform_agent,
        "ask_openai_review",
        lambda target, context, files: {
            "status": "skipped",
            "target": "minikube",
            "infrastructure_required": False,
            "intent_interpretation": "Deploy checkout-service into local minikube.",
            "summary": "Terraform is not required for this local minikube deployment.",
            "reasoning": "The repo already has Kubernetes manifests and uses a local Docker image flow.",
            "findings": [
                {
                    "check": "local target",
                    "status": "pass",
                    "message": "Minikube runs locally and does not need GCP infrastructure.",
                }
            ],
            "recommendations": ["Keep Terraform as an optional cloud-path artifact."],
        },
    )

    result = terraform_agent.run(
        {"intent": "Deploy checkout-service to local minikube in a new namespace"}
    )

    assert result["status"] == "skipped"
    assert result["target"] == "minikube"
    assert result["infrastructure_required"] is False
    assert result["review_source"] == "openai"
    assert result["summary"] == "Terraform skipped for local minikube deployment."
    assert result["artifacts"] == []
    assert any("deploy agent will build the image" in detail for detail in result["details"])


def test_terraform_agent_uses_openai_for_gke(monkeypatch) -> None:
    monkeypatch.setattr(
        terraform_agent,
        "ask_openai_review",
        lambda target, context, files: {
            "status": "warn",
            "target": "gke",
            "infrastructure_required": True,
            "intent_interpretation": "Deploy checkout-service to GKE.",
            "summary": "GKE Terraform needs cluster resources.",
            "reasoning": "GKE requires cloud infrastructure beyond Kubernetes manifests.",
            "findings": [
                {
                    "check": "gke cluster",
                    "status": "warn",
                    "message": "No GKE cluster resource found.",
                }
            ],
            "recommendations": ["Add google_container_cluster."],
        },
    )

    result = terraform_agent.run({"deployment_target": "gke"})

    assert result["status"] == "warning"
    assert result["target"] == "gke"
    assert result["infrastructure_required"] is True
    assert result["review_source"] == "openai"
    assert "Add google_container_cluster." in result["recommendations"]


def test_terraform_agent_falls_back_for_vm_when_openai_fails(monkeypatch) -> None:
    def fail(target, context, files):
        raise RuntimeError("OPENAI_API_KEY is missing")

    monkeypatch.setattr(terraform_agent, "ask_openai_review", fail)

    result = terraform_agent.run({"deployment_target": "vm"})

    assert result["status"] == "warning"
    assert result["target"] == "vm"
    assert result["infrastructure_required"] is True
    assert result["review_source"] == "safe fallback"
    assert any("OpenAI IaC review unavailable" in item for item in result["recommendations"])


def test_terraform_agent_falls_back_for_minikube_when_openai_fails(monkeypatch) -> None:
    def fail(target, context, files):
        raise RuntimeError("OPENAI_API_KEY is missing")

    monkeypatch.setattr(terraform_agent, "ask_openai_review", fail)

    result = terraform_agent.run({"deployment_target": "minikube"})

    assert result["status"] == "skipped"
    assert result["target"] == "minikube"
    assert result["review_source"] == "safe fallback"
    assert result["recommendations"] == []
    assert result["artifacts"] == []


def test_terraform_agent_reviews_digitalocean_files_when_openai_fails(monkeypatch) -> None:
    def fail(target, context, files):
        assert target == "digitalocean-vm"
        assert files
        assert all("infra/digitalocean" in path for path in files)
        raise RuntimeError("OPENAI_API_KEY is missing")

    monkeypatch.setattr(terraform_agent, "ask_openai_review", fail)

    result = terraform_agent.run({"deployment_target": "digitalocean-vm"})

    assert result["status"] in {"passed", "warning"}
    assert result["target"] == "digitalocean-vm"
    assert result["infrastructure_required"] is True
    assert result["review_source"] == "safe fallback"
    assert any("DigitalOcean" in detail for detail in result["details"])
    assert all("infra/digitalocean" in artifact for artifact in result["artifacts"])
