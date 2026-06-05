## Service
- **Name:** `checkout-service`
- **Target:** Minikube (local)
- **Image:** `checkout-service:latest` *(imagePullPolicy: `Never`; built into Minikube Docker daemon)*
- **Runtime/Ports:** App on `8080`; Service `80 -> 8080`
- **Scale:** `2` replicas; **HPA:** min `2`, max `5`, CPU target `70%`

## Namespace
- **Namespace:** `agentic-devops`
- **Live state at review:** Namespace **not yet present**; deployment/service/pods **not yet created** (planned to be created during execution)

## Deployment Strategy
- **Kubernetes strategy:** `RollingUpdate` (default unless overridden in manifest)
- **Health checks:** Readiness/Liveness HTTP probe `GET /health` on port `8080`
- **Resources:** requests `100m/128Mi`, limits `500m/256Mi`
- **Execution highlights:** Enable `metrics-server`, build/load image into Minikube, apply `Deployment/Service/HPA`, verify rollout, smoke test via port-forward

## Validation Summary
- **K8s manifest review:** **Pass**
  - Namespace/replicas/ports/probes/resources align with plan
  - Artifacts reviewed: `k8s/deployment.yaml`, `k8s/service.yaml`
- **Automated tests:** **Pass** — 5/5 agent-generated endpoint tests
  - Validated routes: `GET /`, `/health`, `/checkout`, `/checkout-commons`
  - Validated failure behavior: `FAIL_MODE=true` returns `503` on `/checkout`
  - Note: deterministic `pytest` suite **skipped** (fast demo mode)
- **SLO check (demo):** **Pass**
  - `/checkout`: **20/20** success, **0.0%** error rate (threshold **≤ 1.0%**)
  - Avg latency **8.71ms** (threshold **≤ 250ms**)
  - Readiness: `/health` reported **ready**
- **Security:** **Warning**
  - **Trivy:** no critical issues reported
  - **Checkov:** did not complete cleanly in demo mode (`checkov -d infra/terraform`, exit code `1`)

## Risk Summary
- **HPA scaling dependency:** HPA will not function without **metrics-server** enabled in Minikube.
- **Probe sensitivity:** Short initial delays (5s/10s) may fail if startup is slow or `FAIL_MODE` impacts behavior; may require tuning (`initialDelaySeconds`, timeouts).
- **Coverage gaps (release confidence: 78/100, Medium):**
  - No real in-cluster Minikube validation of rollout/service routing/probe behavior
  - No concurrency/load testing to validate SLOs under stress
  - Security/IaC policy validation incomplete due to Checkov demo-mode failure

## Deployment Decision
- **Decision:** **Approved**
- **Conditions to proceed (operational):**
  - Enable `metrics-server` addon in Minikube before applying HPA
  - Ensure image is present in Minikube Docker daemon (`eval $(minikube docker-env)` or `minikube image load`)
  - Confirm `/health` stabilizes quickly during rollout; adjust probe timings if needed
