variable "do_token" {
  description = "DigitalOcean API token. Provide through TF_VAR_do_token."
  type        = string
  sensitive   = true
}

variable "region" {
  description = "DigitalOcean region for the demo Droplet."
  type        = string
  default     = "nyc3"
}

variable "droplet_name" {
  description = "DigitalOcean Droplet name."
  type        = string
  default     = "checkout-service-demo"
}

variable "size" {
  description = "DigitalOcean Droplet size."
  type        = string
  default     = "s-1vcpu-1gb"
}

variable "image" {
  description = "DigitalOcean Droplet base image."
  type        = string
  default     = "ubuntu-22-04-x64"
}

variable "ssh_public_key" {
  description = "Optional SSH public key to create in DigitalOcean."
  type        = string
  default     = ""
}

variable "ssh_key_fingerprint" {
  description = "Existing DigitalOcean SSH key fingerprint. Used when ssh_public_key is empty."
  type        = string
  default     = ""
}

variable "allowed_ssh_cidrs" {
  description = "CIDRs allowed to SSH to the Droplet."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "allowed_app_cidrs" {
  description = "CIDRs allowed to reach the checkout app port."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}
