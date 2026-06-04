# Outputs for the optional GCP VM demo.

output "instance_name" {
  description = "Name of the demo VM."
  value       = google_compute_instance.checkout_demo.name
}

output "instance_zone" {
  description = "Zone where the demo VM is created."
  value       = google_compute_instance.checkout_demo.zone
}

output "machine_type" {
  description = "Machine type used by the demo VM."
  value       = google_compute_instance.checkout_demo.machine_type
}

output "external_ip" {
  description = "Ephemeral external IP assigned to the demo VM."
  value       = google_compute_instance.checkout_demo.network_interface[0].access_config[0].nat_ip
}
