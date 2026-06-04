# Variables for the optional GCP VM demo.
# Provide values through terraform.tfvars, environment variables, or CLI flags.

variable "project_id" {
  description = "GCP project ID. Do not commit real project IDs to this repository."
  type        = string
}

variable "region" {
  description = "GCP region for provider configuration."
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "GCP zone for the demo VM."
  type        = string
  default     = "us-central1-a"
}

variable "machine_type" {
  description = "GCP Compute Engine machine type for the demo VM."
  type        = string
  default     = "e2-medium"
}
