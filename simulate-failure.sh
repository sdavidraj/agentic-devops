#!/usr/bin/env bash
set -euo pipefail

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

NAMESPACE="${KUBE_NAMESPACE:-agentic-devops}"
SERVICE_NAME="${SERVICE_NAME:-checkout-service}"
DEPLOYMENT_NAME="${SERVICE_NAME}"
CONTAINER_NAME="${SERVICE_NAME}"

need_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    exit 1
  fi
}

need_command kubectl

echo "Simulating ${SERVICE_NAME} failure..."
echo "Setting FAIL_MODE=true on deployment/${DEPLOYMENT_NAME} in namespace ${NAMESPACE}."

kubectl set env \
  "deployment/${DEPLOYMENT_NAME}" \
  "FAIL_MODE=true" \
  --namespace "${NAMESPACE}" \
  --containers "${CONTAINER_NAME}"

echo "Waiting for rollout..."
kubectl rollout status \
  "deployment/${DEPLOYMENT_NAME}" \
  --namespace "${NAMESPACE}" \
  --timeout=120s

cat <<EOF

Failure mode is active.

Run SLO validation:
  PYTHONPATH=. python agents/orchestrator.py

Or call the SLO agent directly from Python:
  PYTHONPATH=. python -c "from agents.slo_agent import run; run({})"

Expected result:
  /checkout should fail SLO validation because FAIL_MODE=true.

EOF
