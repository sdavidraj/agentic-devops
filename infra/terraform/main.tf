# Optional GCP VM demo infrastructure.
# This example intentionally avoids real project IDs and credentials.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

resource "google_compute_instance" "checkout_demo" {
  name         = "checkout-demo-vm"
  machine_type = var.machine_type
  zone         = var.zone

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 20
      type  = "pd-balanced"
    }
  }

  network_interface {
    network = "default"

    access_config {
      # Ephemeral external IP for optional demo access.
    }
  }

  labels = {
    app         = "checkout-service"
    environment = "demo"
  }
}
