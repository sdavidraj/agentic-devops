terraform {
  required_version = ">= 1.6.0"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
  }
}

provider "digitalocean" {
  token = var.do_token
}

resource "digitalocean_ssh_key" "checkout_demo" {
  count      = var.ssh_public_key != "" && var.ssh_key_fingerprint == "" ? 1 : 0
  name       = "${var.droplet_name}-github-actions"
  public_key = var.ssh_public_key
}

locals {
  ssh_key_ids = compact([
    var.ssh_key_fingerprint,
    try(digitalocean_ssh_key.checkout_demo[0].fingerprint, ""),
  ])
}

resource "digitalocean_droplet" "checkout_demo" {
  image    = var.image
  name     = var.droplet_name
  region   = var.region
  size     = var.size
  ssh_keys = local.ssh_key_ids

  tags = [
    "agentic-devops",
    "checkout-service",
  ]
}

resource "digitalocean_firewall" "checkout_demo" {
  name        = "${var.droplet_name}-firewall"
  droplet_ids = [digitalocean_droplet.checkout_demo.id]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = var.allowed_ssh_cidrs
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "8080"
    source_addresses = var.allowed_app_cidrs
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
