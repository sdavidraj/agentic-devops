"""FastAPI checkout microservice for the Agentic DevOps demo."""

import os
from uuid import uuid4

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

SERVICE_NAME = os.getenv("SERVICE_NAME", "checkout-service")
SERVICE_VERSION = "0.1.0"
SERVICE_PORT = int(os.getenv("LOCAL_PORT", "8080"))

app = FastAPI(title="Checkout Microservice", version=SERVICE_VERSION)


def fail_mode_enabled() -> bool:
    """Return true when checkout failure mode is enabled."""
    return os.getenv("FAIL_MODE", "false").lower() == "true"


@app.get("/")
def root() -> dict[str, str | int]:
    """Return service metadata."""
    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "status": "running",
        "port": SERVICE_PORT,
    }


@app.get("/health")
def health() -> dict[str, str]:
    """Basic health endpoint for Kubernetes probes."""
    return {"status": "healthy", "service": SERVICE_NAME}


@app.get("/checkout")
def checkout():
    """Create a mock checkout order or return a failure payload."""
    if fail_mode_enabled():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "service": SERVICE_NAME,
                "message": "Checkout service is in FAIL_MODE.",
            },
        )

    return {
        "status": "success",
        "service": SERVICE_NAME,
        "orderId": str(uuid4()),
    }


@app.get("/checkout-commons")
def checkout_commons() -> dict[str, str | list[str]]:
    """Return shared checkout capabilities used by downstream clients."""
    return {
        "status": "success",
        "service": SERVICE_NAME,
        "resource": "checkout-commons",
        "capabilities": ["cart-validation", "payment-routing", "order-audit"],
    }
