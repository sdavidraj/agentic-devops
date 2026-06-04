"""Shared configuration helpers for agents."""

from __future__ import annotations

import os

from dotenv import load_dotenv

DEFAULT_KUBE_NAMESPACE = "agentic-devops"
DEFAULT_SERVICE_NAME = "checkout-service"
DEFAULT_LOCAL_PORT = 8080
DEFAULT_DEPLOYMENT_TARGET = "minikube"
DEFAULT_DIGITALOCEAN_REGION = "nyc3"
DEFAULT_DIGITALOCEAN_DROPLET_NAME = "checkout-service-demo"
DEFAULT_DIGITALOCEAN_IMAGE = "ubuntu-22-04-x64"
DEFAULT_DIGITALOCEAN_SIZE = "s-1vcpu-1gb"
DEFAULT_VM_USER = "root"
DEFAULT_VM_APP_PORT = 8080


def kube_namespace(default: str = DEFAULT_KUBE_NAMESPACE) -> str:
    """Return the Kubernetes namespace from .env or environment."""
    load_dotenv()
    return os.getenv("KUBE_NAMESPACE", default)


def service_name(default: str = DEFAULT_SERVICE_NAME) -> str:
    """Return the service/deployment name from .env or environment."""
    load_dotenv()
    return os.getenv("SERVICE_NAME", default)


def local_port(default: int = DEFAULT_LOCAL_PORT) -> int:
    """Return the local port from .env or environment."""
    load_dotenv()
    value = os.getenv("LOCAL_PORT")
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError("LOCAL_PORT must be an integer.") from exc


def deployment_target(default: str = DEFAULT_DEPLOYMENT_TARGET) -> str:
    """Return deployment target: minikube, gke, vm, or digitalocean-vm."""
    load_dotenv()
    return os.getenv("DEPLOYMENT_TARGET", default).lower()


def slo_base_url(default: str = "") -> str:
    """Return an optional base URL for SLO checks."""
    load_dotenv()
    return os.getenv("SLO_BASE_URL", default).rstrip("/")


def digitalocean_region(default: str = DEFAULT_DIGITALOCEAN_REGION) -> str:
    load_dotenv()
    return os.getenv("DIGITALOCEAN_REGION", default)


def digitalocean_droplet_name(default: str = DEFAULT_DIGITALOCEAN_DROPLET_NAME) -> str:
    load_dotenv()
    return os.getenv("DIGITALOCEAN_DROPLET_NAME", default)


def digitalocean_image(default: str = DEFAULT_DIGITALOCEAN_IMAGE) -> str:
    load_dotenv()
    return os.getenv("DIGITALOCEAN_IMAGE", default)


def digitalocean_size(default: str = DEFAULT_DIGITALOCEAN_SIZE) -> str:
    load_dotenv()
    return os.getenv("DIGITALOCEAN_SIZE", default)


def vm_user(default: str = DEFAULT_VM_USER) -> str:
    load_dotenv()
    return os.getenv("VM_USER", default)


def vm_host(default: str = "") -> str:
    load_dotenv()
    return os.getenv("VM_HOST", default)


def vm_app_port(default: int = DEFAULT_VM_APP_PORT) -> int:
    load_dotenv()
    value = os.getenv("VM_APP_PORT")
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError("VM_APP_PORT must be an integer.") from exc


def docker_image(default: str = "") -> str:
    """Return the container image to deploy, preferring GHCR_IMAGE over DOCKER_IMAGE."""
    load_dotenv()
    return os.getenv("GHCR_IMAGE") or os.getenv("DOCKER_IMAGE", default)
