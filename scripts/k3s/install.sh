#!/usr/bin/env bash
# Install and configure k3d (k3s in Docker) for local Kubernetes development.
# Requires Docker Desktop to be running.
set -euo pipefail

CLUSTER_NAME="local"
K8S_NAMESPACE="openclaw"
KUBECONFIG_PATH="${HOME}/.kube/k3d-local.yaml"

# ── Prerequisites ────────────────────────────────────────────────────────────

if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker is not running. Start Docker Desktop and retry." >&2
    exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
    echo "ERROR: Homebrew not found. Install it from https://brew.sh" >&2
    exit 1
fi

if ! command -v kubectl >/dev/null 2>&1; then
    echo "Installing kubectl..."
    brew install kubectl
fi

if ! command -v k3d >/dev/null 2>&1; then
    echo "Installing k3d..."
    brew install k3d
fi

echo "k3d $(k3d version | head -1)"
echo "kubectl $(kubectl version --client --short 2>/dev/null || kubectl version --client | head -1)"

# ── Cluster ──────────────────────────────────────────────────────────────────

if k3d cluster list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "${CLUSTER_NAME}"; then
    echo "k3d cluster '${CLUSTER_NAME}' already exists — skipping creation"
else
    echo "Creating k3d cluster '${CLUSTER_NAME}'..."
    k3d cluster create "${CLUSTER_NAME}" \
        --agents 1 \
        --api-port 6550 \
        --port "18080:80@loadbalancer" \
        --wait
    echo "Cluster created."
fi

# ── Kubeconfig ───────────────────────────────────────────────────────────────

echo "Exporting kubeconfig → ${KUBECONFIG_PATH}"
k3d kubeconfig get "${CLUSTER_NAME}" > "${KUBECONFIG_PATH}"
chmod 600 "${KUBECONFIG_PATH}"

CONTEXT="k3d-${CLUSTER_NAME}"

# ── Namespace ────────────────────────────────────────────────────────────────

echo "Creating namespace '${K8S_NAMESPACE}'..."
kubectl --kubeconfig "${KUBECONFIG_PATH}" --context "${CONTEXT}" \
    create namespace "${K8S_NAMESPACE}" --dry-run=client -o yaml \
    | kubectl --kubeconfig "${KUBECONFIG_PATH}" --context "${CONTEXT}" apply -f -

# ── Smoke test ───────────────────────────────────────────────────────────────

echo ""
echo "Cluster nodes:"
kubectl --kubeconfig "${KUBECONFIG_PATH}" --context "${CONTEXT}" get nodes

echo ""
echo "Namespaces:"
kubectl --kubeconfig "${KUBECONFIG_PATH}" --context "${CONTEXT}" get namespaces

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  k3d cluster '${CLUSTER_NAME}' is ready"
echo "  Kubeconfig : ${KUBECONFIG_PATH}"
echo "  Context    : ${CONTEXT}"
echo "  Namespace  : ${K8S_NAMESPACE}"
echo ""
echo "  Quick access:"
echo "    export KUBECONFIG=${KUBECONFIG_PATH}"
echo "    kubectl get pods -n ${K8S_NAMESPACE}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
