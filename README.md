# Agentic DevOps Pipeline Demo

This repo demonstrates an intent-driven DevOps workflow for:

```text
Deploy a new checkout microservice
```

The default demo runs locally on minikube. A second manual GitHub Actions demo
can deploy the same app to a DigitalOcean VM with LLM-backed agents.

## Architecture Overview

The pipeline combines a small FastAPI service, local Kubernetes deployment, and a Python agent orchestrator.

- `app/`: FastAPI checkout microservice on port `8080`
- `agents/`: Python orchestrator and individual mock DevOps agents
- `k8s/`: Kubernetes manifests for namespace, deployment, service, and HPA
- `infra/terraform/`: Optional GCP VM Terraform demo using variables only
- `infra/digitalocean/`: DigitalOcean Droplet and firewall Terraform for the VM demo
- `tests/`: Unit tests for the service and agents
- `docs/`: Generated release notes and supporting demo docs
- `.github/workflows/`: CI workflow for tests, image build, scan, and dry-run orchestration

Agent flow:

1. Planning agent creates the deployment plan.
2. Terraform agent validates optional GCP VM Terraform files.
3. Security agent runs Checkov and Trivy if installed.
4. Cost agent estimates monthly cost.
5. Kubernetes agent validates manifests.
6. Test agent generates and executes fast API scenarios, then asks the LLM for release confidence.
7. SLO agent validates `/checkout`.
8. Release notes agent writes `docs/release-notes.md`.
9. Rollback agent rolls back when SLO fails.
10. Orchestrator prints the executive summary.

Set `TEST_AGENT_RUN_PYTEST=true` if you want the test agent to run the full
deterministic pytest suite outside the live demo fast path.

## Prerequisites

Install these for the full local Kubernetes demo:

- Python 3.11+
- Docker
- `kubectl`
- `kind`
- `make`

Optional scanners:

- `checkov`
- `trivy`

If Checkov or Trivy are missing, the security agent prints `tool not installed, skipping in demo mode` and returns a warning instead of breaking the demo.

## Setup Steps

Create `.env`:

```env
KUBE_NAMESPACE=agentic-devops
SERVICE_NAME=checkout-service
LOCAL_PORT=8080
```

```bash
make setup
make test
```

Build the local Docker image:

```bash
make build
```

Run the service without Kubernetes:

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Test the service:

```bash
curl http://localhost:8080/
curl http://localhost:8080/health
curl http://localhost:8080/checkout
```

## Local Minikube Demo

Deploy to a local minikube cluster:

```bash
make deploy
```

The deploy script will:

- Create kind cluster `agentic-devops` if needed
- Create namespace from `KUBE_NAMESPACE`
- Build `checkout-service:latest`
- Load the image into kind
- Apply Kubernetes manifests
- Wait for rollout
- Optionally port-forward `localhost:8080` to the service

If you skipped the port-forward prompt, run:

```bash
kubectl port-forward -n agentic-devops service/checkout-service 8080:80
```

Run the full agent demo:

```bash
PYTHONPATH=. .venv/bin/python agents/orchestrator.py \
  --intent "Deploy checkout-service to local minikube in a new namespace" \
  --deploy
```

The orchestrator opens a temporary port-forward for SLO validation. When the
pipeline exits, that temporary port-forward is closed. To keep browser access
open after the demo, run:

```bash
PYTHONPATH=. .venv/bin/python agents/orchestrator.py \
  --intent "Deploy checkout-service to local minikube in a new namespace" \
  --deploy \
  --keep-port-forward
```

Then open:

```text
http://127.0.0.1:8080/
http://127.0.0.1:8080/health
http://127.0.0.1:8080/checkout
```

For CI or a no-cluster screen-share path:

```bash
PYTHONPATH=. .venv/bin/python agents/orchestrator.py --dry-run
```

## DigitalOcean VM GitHub Actions Demo

The cloud demo is separate from the local demo and runs only when manually
triggered from GitHub Actions.

Required repository secrets:

```text
OPENAI_API_KEY
DIGITALOCEAN_TOKEN
VM_SSH_PRIVATE_KEY
VM_SSH_PUBLIC_KEY or DIGITALOCEAN_SSH_KEY_FINGERPRINT
GHCR_USERNAME and GHCR_TOKEN if the VM must pull from a private GHCR package
```

Trigger the workflow:

1. Open GitHub Actions.
2. Select `Agentic DigitalOcean VM Deploy`.
3. Choose `Run workflow`.
4. Optionally override the Droplet name or region.

The workflow builds and pushes the Docker image to GHCR, provisions a
DigitalOcean Droplet and firewall with Terraform, runs the orchestrator with
`DEPLOYMENT_TARGET=digitalocean-vm`, deploys over SSH with Docker, validates
`http://<droplet-ip>:8080/checkout`, and rolls back by restoring the previous
Docker container/image if SLO validation fails.

Cleanup after the demo:

```bash
terraform -chdir=infra/digitalocean destroy
```

See [docs/digitalocean-demo.md](docs/digitalocean-demo.md) for the full cloud
demo flow and safety notes.

## Simulate Failure

Turn on failure mode in Kubernetes:

```bash
make simulate-failure
```

This patches the deployment:

```bash
kubectl set env deployment/checkout-service FAIL_MODE=true -n agentic-devops
```

Then run:

```bash
PYTHONPATH=. .venv/bin/python agents/orchestrator.py
```

The SLO agent calls `http://127.0.0.1:8080/checkout` 20 times. With `FAIL_MODE=true`, `/checkout` returns errors, SLO validation fails, and rollback is triggered.

## How Rollback Works

Rollback is driven by SLO status.

If SLO passes:

```text
Rollback Agent: skipped
Deployment decision: Approved
```

If SLO fails, the rollback agent runs:

```bash
kubectl rollout undo deployment/checkout-service -n agentic-devops
kubectl rollout status deployment/checkout-service -n agentic-devops --timeout=120s
```

The final executive summary is generated from the agent evidence. It explains
the deployment decision and the reasoning path across validation, SLO checks,
and rollback:

```text
Decision: Rolled Back
Agentic reasoning: the deploy and SLO evidence showed customer-impacting risk,
so the rollback agent restored the previous healthy revision.
```

Manual rollback command:

```bash
make rollback
```

## Suggested Executive Talk Track

Use this short narrative while running the demo:

```text
We start with a business intent: deploy a new checkout microservice.
The pipeline breaks that intent into specialist agent stages: plan, infrastructure, security, cost, Kubernetes, tests, SLO, release notes, and rollback.
Every stage produces readable evidence, not just a pass/fail light.
In the happy path, the system approves deployment and writes release notes.
In the failure path, the SLO agent detects customer-impacting checkout errors and triggers rollback automatically.
This compresses a manual 2-3 day release workflow into a repeatable 15-minute agentic pipeline.
```

Key idea to emphasize:

```text
The final summary is LLM-authored from the agent trace, so it tells the audience
what the agents reasoned about, what they decided automatically, and why the
deployment was approved or rolled back.
```

## Troubleshooting Commands

Cluster and namespace:

```bash
kind get clusters
kubectl config current-context
kubectl get ns
```

Workloads:

```bash
kubectl get pods -n agentic-devops
kubectl get deployment checkout-service -n agentic-devops
kubectl describe deployment checkout-service -n agentic-devops
kubectl logs -n agentic-devops deployment/checkout-service
```

Service and SLO checks:

```bash
kubectl get svc -n agentic-devops
kubectl port-forward -n agentic-devops service/checkout-service 8080:80
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/checkout
make validate-slo
```

Rollout and rollback:

```bash
kubectl rollout status deployment/checkout-service -n agentic-devops
kubectl rollout history deployment/checkout-service -n agentic-devops
kubectl rollout undo deployment/checkout-service -n agentic-devops
```

Reset local demo:

```bash
make clean
make deploy
```
