# DigitalOcean VM Agentic Deployment Demo

This demo uses the same agentic pipeline as the local minikube flow, but routes
deployment to a DigitalOcean Droplet from GitHub Actions.

## Architecture

```text
GitHub Actions
  -> build app/Dockerfile
  -> push ghcr.io/<owner>/<repo>/checkout-service:<sha>
  -> terraform apply infra/digitalocean
  -> run agents/orchestrator.py with DEPLOYMENT_TARGET=digitalocean-vm
  -> SSH to Droplet
  -> docker run checkout-service on port 8080
  -> SLO check http://<droplet-ip>:8080/checkout
  -> rollback with Docker container/image restore if needed
```

The local minikube path remains separate. It still uses Kubernetes manifests,
`kubectl`, port-forwarding, and Kubernetes rollback.

## Agent Flow

1. Planner Agent builds a DigitalOcean VM deployment plan.
2. Terraform Agent reviews `infra/digitalocean` for provider, Droplet, firewall, and outputs.
3. Security Agent runs available repository and IaC scans.
4. Cost Agent reports expected local/cloud cost context.
5. Kubernetes Agent reviews manifests as repo evidence, but the VM deploy path does not apply them.
6. Test Agent generates and runs fast API scenarios.
7. VM Deploy Agent deploys the pushed image over SSH and Docker.
8. SLO Agent validates the public VM endpoint.
9. Release Notes Agent writes `docs/release-notes.md`.
10. VM Rollback Agent restores the previous container/image if SLO fails.

## GitHub Actions Flow

Workflow file:

```text
.github/workflows/digitalocean-agentic-deploy.yml
```

Trigger:

```text
workflow_dispatch only
```

The workflow does not run on push by default, so it does not affect the local
minikube demo or normal CI.

## Required Secrets

```text
OPENAI_API_KEY
DIGITALOCEAN_TOKEN
VM_SSH_PRIVATE_KEY
VM_SSH_PUBLIC_KEY or DIGITALOCEAN_SSH_KEY_FINGERPRINT
```

Optional when the Droplet needs credentials to pull a private GHCR image:

```text
GHCR_USERNAME
GHCR_TOKEN
```

## SLO Validation

For `DEPLOYMENT_TARGET=digitalocean-vm`, the SLO agent uses:

```text
SLO_BASE_URL=http://<droplet-ip>:8080
```

It checks:

```text
GET /health
GET /checkout
```

For minikube, the SLO agent still uses localhost through the orchestrator's
temporary port-forward.

## Rollback

The VM deploy agent renames the existing app container to:

```text
checkout-service-previous
```

The VM rollback agent only touches:

```text
checkout-service
checkout-service-previous
```

It does not remove unrelated containers.

## Safety Notes

- The workflow is manual-only.
- DigitalOcean secrets are read from GitHub Actions secrets.
- Terraform variables do not contain committed tokens.
- The default firewall allows app traffic on port `8080`; restrict CIDRs for private demos.
- Destroy the Droplet after the demo to avoid ongoing cost.

## Cleanup

From a machine with Terraform and `DIGITALOCEAN_TOKEN` configured:

```bash
terraform -chdir=infra/digitalocean destroy
```
