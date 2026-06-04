output "droplet_name" {
  description = "Name of the DigitalOcean Droplet."
  value       = digitalocean_droplet.checkout_demo.name
}

output "droplet_ipv4_address" {
  description = "Public IPv4 address of the DigitalOcean Droplet."
  value       = digitalocean_droplet.checkout_demo.ipv4_address
}

output "app_url" {
  description = "Checkout service URL exposed by the Droplet."
  value       = "http://${digitalocean_droplet.checkout_demo.ipv4_address}:8080"
}

output "ssh_user" {
  description = "Default SSH user for the Droplet image."
  value       = "root"
}
