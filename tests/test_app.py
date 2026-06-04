"""Unit tests for the FastAPI checkout service."""

from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_returns_service_metadata() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "checkout-service",
        "version": "0.1.0",
        "status": "running",
        "port": 8080,
    }


def test_health_returns_healthy() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "checkout-service"}


def test_checkout_returns_success_with_random_order_id(monkeypatch) -> None:
    monkeypatch.setenv("FAIL_MODE", "false")

    response = client.get("/checkout")
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "success"
    assert body["service"] == "checkout-service"
    UUID(body["orderId"])


def test_checkout_returns_error_payload_when_fail_mode_enabled(monkeypatch) -> None:
    monkeypatch.setenv("FAIL_MODE", "true")

    response = client.get("/checkout")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "service": "checkout-service",
        "message": "Checkout service is in FAIL_MODE.",
    }


def test_checkout_commons_returns_shared_capabilities() -> None:
    response = client.get("/checkout-commons")

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "service": "checkout-service",
        "resource": "checkout-commons",
        "capabilities": ["cart-validation", "payment-routing", "order-audit"],
    }
