"""Tests for shared agent configuration."""

from agents import config


def test_deployment_target_defaults_to_minikube(monkeypatch) -> None:
    monkeypatch.delenv("DEPLOYMENT_TARGET", raising=False)

    assert config.deployment_target() == "minikube"


def test_digitalocean_and_vm_config_from_env(monkeypatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_TARGET", "digitalocean-vm")
    monkeypatch.setenv("SLO_BASE_URL", "http://203.0.113.10:8080/")
    monkeypatch.setenv("DIGITALOCEAN_REGION", "sfo3")
    monkeypatch.setenv("DIGITALOCEAN_DROPLET_NAME", "checkout-demo")
    monkeypatch.setenv("DIGITALOCEAN_IMAGE", "ubuntu-24-04-x64")
    monkeypatch.setenv("DIGITALOCEAN_SIZE", "s-2vcpu-2gb")
    monkeypatch.setenv("VM_USER", "deploy")
    monkeypatch.setenv("VM_HOST", "203.0.113.10")
    monkeypatch.setenv("VM_APP_PORT", "9090")
    monkeypatch.setenv("GHCR_IMAGE", "ghcr.io/acme/app:sha")
    monkeypatch.setenv("DOCKER_IMAGE", "ignored:latest")

    assert config.deployment_target() == "digitalocean-vm"
    assert config.slo_base_url() == "http://203.0.113.10:8080"
    assert config.digitalocean_region() == "sfo3"
    assert config.digitalocean_droplet_name() == "checkout-demo"
    assert config.digitalocean_image() == "ubuntu-24-04-x64"
    assert config.digitalocean_size() == "s-2vcpu-2gb"
    assert config.vm_user() == "deploy"
    assert config.vm_host() == "203.0.113.10"
    assert config.vm_app_port() == 9090
    assert config.docker_image() == "ghcr.io/acme/app:sha"
