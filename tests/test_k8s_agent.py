"""Tests for the Kubernetes manifest review agent."""

from pathlib import Path

import yaml

from agents import k8s_agent


DEPLOYMENT = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: checkout-service
  namespace: agentic-devops
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: checkout-service
          image: checkout-service:latest
          imagePullPolicy: Never
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 256Mi
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
"""

SERVICE = """apiVersion: v1
kind: Service
metadata:
  name: checkout-service
  namespace: agentic-devops
spec:
  ports:
    - port: 80
      targetPort: 8080
"""


def write_manifests(tmp_path: Path, deployment: str = DEPLOYMENT, service: str = SERVICE) -> None:
    k8s_dir = tmp_path / "k8s"
    k8s_dir.mkdir()
    (k8s_dir / "deployment.yaml").write_text(deployment, encoding="utf-8")
    (k8s_dir / "service.yaml").write_text(service, encoding="utf-8")


def fake_live_state(deployment, service, namespace, app_name):
    return {
        "available": True,
        "namespace": namespace,
        "namespace_exists": True,
        "deployment": {
            "exists": True,
            "name": app_name,
            "replicas": 2,
            "ready_replicas": 2,
            "image": "checkout-service:latest",
        },
        "service": {"exists": True, "name": app_name, "type": "ClusterIP", "ports": []},
        "pods": {"count": 2, "ready": 2, "names": ["checkout-a", "checkout-b"]},
        "note": "",
    }


def test_k8s_agent_uses_openai_review_without_modifying_files(monkeypatch, tmp_path) -> None:
    write_manifests(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(k8s_agent, "live_cluster_state", fake_live_state)
    monkeypatch.setattr(
        k8s_agent,
        "ask_openai_review",
        lambda deployment, service, namespace, replicas, live_state, planned_actions: {
            "status": "pass",
            "findings": [],
            "recommendations": ["Looks ready."],
        },
    )

    before = (tmp_path / "k8s/deployment.yaml").read_text(encoding="utf-8")
    result = k8s_agent.run({"deployment_plan": {"namespace": "agentic-devops", "replicas": 2}})
    after = (tmp_path / "k8s/deployment.yaml").read_text(encoding="utf-8")

    assert result["status"] == "passed"
    assert result["review_status"] == "pass"
    assert result["live_state"]["deployment"]["exists"] is True
    assert any("Deployment action:" in detail for detail in result["details"])
    assert before == after


def test_k8s_agent_falls_back_to_local_warning(monkeypatch, tmp_path) -> None:
    write_manifests(tmp_path, DEPLOYMENT.replace("namespace: agentic-devops", "namespace: demo"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        k8s_agent,
        "live_cluster_state",
        lambda deployment, service, namespace, app_name: {
            "available": False,
            "namespace": namespace,
            "note": "kubectl not installed",
        },
    )

    def fail_review(deployment, service, namespace, replicas, live_state, planned_actions):
        raise RuntimeError("OPENAI_API_KEY is missing")

    monkeypatch.setattr(k8s_agent, "ask_openai_review", fail_review)

    result = k8s_agent.run({"deployment_plan": {"namespace": "agentic-devops", "replicas": 2}})

    assert result["status"] == "warning"
    assert result["review_status"] == "warn"
    assert any("Live cluster: not inspected" in detail for detail in result["details"])
    assert any("namespace correctness" in detail for detail in result["details"])


def test_k8s_agent_apply_fixes_updates_namespace(monkeypatch, tmp_path) -> None:
    write_manifests(
        tmp_path,
        DEPLOYMENT.replace("namespace: agentic-devops", "namespace: demo"),
        SERVICE.replace("namespace: agentic-devops", "namespace: demo"),
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(k8s_agent, "live_cluster_state", fake_live_state)
    monkeypatch.setattr(
        k8s_agent,
        "ask_openai_review",
        lambda deployment, service, namespace, replicas, live_state, planned_actions: {
            "status": "warn",
            "findings": [],
            "recommendations": ["Fix namespace."],
        },
    )

    result = k8s_agent.run(
        {
            "apply_fixes": True,
            "deployment_plan": {"namespace": "agentic-devops", "replicas": 2},
        }
    )
    deployment = yaml.safe_load((tmp_path / "k8s/deployment.yaml").read_text(encoding="utf-8"))
    service = yaml.safe_load((tmp_path / "k8s/service.yaml").read_text(encoding="utf-8"))

    assert result["status"] == "warning"
    assert deployment["metadata"]["namespace"] == "agentic-devops"
    assert service["metadata"]["namespace"] == "agentic-devops"
