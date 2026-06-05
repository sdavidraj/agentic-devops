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

need_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    exit 1
  fi
}

need_command kubectl

echo "Cleaning minikube resources for namespace: ${NAMESPACE}"

namespace_check="$(kubectl get namespace "${NAMESPACE}" 2>&1)" || {
  if [[ "${namespace_check}" == *"NotFound"* ]]; then
    echo "Namespace ${NAMESPACE} does not exist. Nothing to clean."
    exit 0
  fi
  echo "Unable to check namespace ${NAMESPACE}:"
  echo "${namespace_check}"
  exit 1
}

if [[ -z "${namespace_check}" ]]; then
  echo "Namespace ${NAMESPACE} does not exist. Nothing to clean."
  exit 0
fi

echo "Deleting checkout-service Kubernetes resources..."
kubectl delete deployment "${SERVICE_NAME}" -n "${NAMESPACE}" --ignore-not-found
kubectl delete service "${SERVICE_NAME}" -n "${NAMESPACE}" --ignore-not-found
kubectl delete hpa "${SERVICE_NAME}" -n "${NAMESPACE}" --ignore-not-found

echo "Deleting any remaining namespaced resources..."
kubectl delete all --all -n "${NAMESPACE}" --ignore-not-found
kubectl delete configmap --all -n "${NAMESPACE}" --ignore-not-found
kubectl delete secret --all -n "${NAMESPACE}" --ignore-not-found

echo "Deleting namespace ${NAMESPACE}..."
kubectl delete namespace "${NAMESPACE}" --ignore-not-found

echo "Waiting for namespace deletion..."
kubectl wait --for=delete "namespace/${NAMESPACE}" --timeout=120s || true

echo "Minikube resource cleanup complete."
