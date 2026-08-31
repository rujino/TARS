#!/usr/bin/env bash
# ==============================================================================
# TARS K3s Automated Build & Deployment Script
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "================================================================="
echo "🚀 TARS K3s Production Deployment Protocol"
echo "📂 Project Root: ${PROJECT_ROOT}"
echo "================================================================="

# 1. Build Local Backend Image
echo "🔨 Step 1: Building local Docker image (tars-backend:latest)..."
cd "${PROJECT_ROOT}"
docker build -t tars-backend:latest .

# 2. Import Image to K3s Containerd Engine
echo "📦 Step 2: Importing Docker image into K3s containerd runtime..."
docker save tars-backend:latest | sudo k3s ctr -n k8s.io images import -

# 3. Apply Kubernetes Manifests
echo "⚙️  Step 3: Applying Kubernetes manifests..."
if [ ! -f "${PROJECT_ROOT}/k8s/01-secret.yaml" ]; then
    echo "⚠️  k8s/01-secret.yaml not found. Initializing from 01-secret.example.yaml..."
    cp "${PROJECT_ROOT}/k8s/01-secret.example.yaml" "${PROJECT_ROOT}/k8s/01-secret.yaml"
    echo "👉 Please edit k8s/01-secret.yaml with your actual passwords and keys!"
fi

if [ ! -f "${PROJECT_ROOT}/k8s/04-cluster-issuer.yaml" ] && [ -f "${PROJECT_ROOT}/k8s/04-cluster-issuer.example.yaml" ]; then
    echo "⚠️  k8s/04-cluster-issuer.yaml not found. Initializing from 04-cluster-issuer.example.yaml..."
    cp "${PROJECT_ROOT}/k8s/04-cluster-issuer.example.yaml" "${PROJECT_ROOT}/k8s/04-cluster-issuer.yaml"
fi

if [ ! -f "${PROJECT_ROOT}/k8s/05-ingress.yaml" ] && [ -f "${PROJECT_ROOT}/k8s/05-ingress.example.yaml" ]; then
    echo "⚠️  k8s/05-ingress.yaml not found. Initializing from 05-ingress.example.yaml..."
    cp "${PROJECT_ROOT}/k8s/05-ingress.example.yaml" "${PROJECT_ROOT}/k8s/05-ingress.yaml"
fi

kubectl apply -f "${PROJECT_ROOT}/k8s/00-namespace.yaml"
kubectl apply -f "${PROJECT_ROOT}/k8s/01-config.yaml"
kubectl apply -f "${PROJECT_ROOT}/k8s/01-secret.yaml"
kubectl apply -f "${PROJECT_ROOT}/k8s/02-db.yaml"
kubectl apply -f "${PROJECT_ROOT}/k8s/03-backend.yaml"

if [ -f "${PROJECT_ROOT}/k8s/04-cluster-issuer.yaml" ]; then
    echo "🔐 Step 4: Applying Cert-Manager ClusterIssuer & Ingress..."
    kubectl apply -f "${PROJECT_ROOT}/k8s/04-cluster-issuer.yaml" || echo "⚠️ cert-manager not yet ready, skip ClusterIssuer."
fi

if [ -f "${PROJECT_ROOT}/k8s/05-ingress.yaml" ]; then
    kubectl apply -f "${PROJECT_ROOT}/k8s/05-ingress.yaml"
fi

echo "🔄 Step 5: Rolling restart backend deployment to pick up any changes..."
kubectl rollout restart deployment tars-backend -n tars || true

echo "================================================================="
echo "🎉 Deployment Applied Successfully!"
echo "📊 Current Status in namespace 'tars':"
kubectl get pods,svc,pvc,ingress -n tars
echo "================================================================="
echo "👉 Check backend logs with: kubectl logs -f deployment/tars-backend -n tars"
