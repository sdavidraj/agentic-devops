#!/usr/bin/env bash
set -euo pipefail

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

CLUSTER_NAME="agentic-devops"
NAMESPACE="${KUBE_NAMESPACE:-agentic-devops}"
SERVICE_NAME="${SERVICE_NAME:-checkout-service}"
IMAGE_NAME="${SERVICE_NAME}:latest"
DEPLOYMENT_NAME="${SERVICE_NAME}"
LOCAL_PORT="${LOCAL_PORT:-8080}"
TARGET_PORT="8080"

need_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    exit 1
  fi
}

cluster_exists() {
  kind get clusters | grep -qx "${CLUSTER_NAME}"
}

wait_for_rollout() {
  kubectl rollout status \
    "deployment/${DEPLOYMENT_NAME}" \
    --namespace "${NAMESPACE}" \
    --timeout=120s
}

print_next_steps() {
  cat <<EOF

Deployment complete.

Useful commands:
  kubectl get pods -n ${NAMESPACE}
  kubectl get svc -n ${NAMESPACE}
  kubectl get hpa -n ${NAMESPACE}
  kubectl describe deployment/${DEPLOYMENT_NAME} -n ${NAMESPACE}
  kubectl logs -n ${NAMESPACE} deployment/${DEPLOYMENT_NAME}
  kubectl rollout restart deployment/${DEPLOYMENT_NAME} -n ${NAMESPACE}
  kubectl rollout undo deployment/${DEPLOYMENT_NAME} -n ${NAMESPACE}

Port-forward manually:
  kubectl port-forward -n ${NAMESPACE} deployment/${DEPLOYMENT_NAME} ${LOCAL_PORT}:${TARGET_PORT}

Then test:
  curl http://localhost:${LOCAL_PORT}/
  curl http://localhost:${LOCAL_PORT}/health
  curl http://localhost:${LOCAL_PORT}/checkout

EOF
}

need_command docker
need_command kind
need_command kubectl

if cluster_exists; then
  echo "kind cluster '${CLUSTER_NAME}' already exists."
else
  echo "Creating kind cluster '${CLUSTER_NAME}'..."
  kind create cluster --name "${CLUSTER_NAME}"
fi

echo "Using kind cluster '${CLUSTER_NAME}'..."
kubectl config use-context "kind-${CLUSTER_NAME}" >/dev/null

echo "Creating namespace '${NAMESPACE}' if needed..."
kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

echo "Building Docker image '${IMAGE_NAME}' from app source..."
docker build -t "${IMAGE_NAME}" -f Dockerfile .

echo "Loading Docker image '${IMAGE_NAME}' into kind cluster..."
kind load docker-image "${IMAGE_NAME}" --name "${CLUSTER_NAME}"

echo "Applying Kubernetes manifests..."
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/hpa.yaml

echo "Waiting for deployment rollout..."
wait_for_rollout

print_next_steps

if [[ "${1:-}" == "--port-forward" ]]; then
  echo "Starting port-forward on http://localhost:${LOCAL_PORT} ..."
  exec kubectl port-forward \
    --namespace "${NAMESPACE}" \
    "deployment/${DEPLOYMENT_NAME}" \
    "${LOCAL_PORT}:${TARGET_PORT}"
else
  read -r -p "Start port-forward now? [y/N] " answer
  case "${answer}" in
    [yY]|[yY][eE][sS])
      echo "Starting port-forward on http://localhost:${LOCAL_PORT} ..."
      exec kubectl port-forward \
        --namespace "${NAMESPACE}" \
        "deployment/${DEPLOYMENT_NAME}" \
        "${LOCAL_PORT}:${TARGET_PORT}"
      ;;
    *)
      echo "Skipping port-forward."
      ;;
  esac
fi
