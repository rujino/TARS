#!/usr/bin/env bash
# ==============================================================================
# TARS K3s Automated Build & Deployment Script
# Usage:
#   bash k8s/deploy.sh           # Deploy all (Backend + Frontend + K8s Manifests)
#   bash k8s/deploy.sh frontend  # Fast deploy Frontend only (~5s)
#   bash k8s/deploy.sh backend   # Deploy Backend only
# ==============================================================================
set -euo pipefail

TARGET="${1:-all}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "================================================================="
echo "🚀 TARS K3s Production Deployment Protocol"
echo "🎯 Target: ${TARGET}"
echo "📂 Project Root: ${PROJECT_ROOT}"
echo "================================================================="

# --- 1. FRONTEND ONLY DEPLOY ---
if [ "${TARGET}" = "frontend" ]; then
    echo "🔨 Step 1: Building Frontend Docker image (127.0.0.1:5000/tars-frontend:latest)..."
    cd "${PROJECT_ROOT}"
    docker build -t 127.0.0.1:5000/tars-frontend:latest -t tars-frontend:latest -f frontend/Dockerfile frontend

    echo "📦 Step 2: Pushing Frontend image to local registry..."
    docker push 127.0.0.1:5000/tars-frontend:latest

    echo "⚙️  Step 3: Applying Frontend manifest..."
    kubectl apply -f "${PROJECT_ROOT}/k8s/08-frontend.yaml"

    echo "🔄 Step 4: Rolling restart frontend deployment..."
    kubectl rollout restart deployment tars-frontend -n tars
    kubectl rollout status deployment tars-frontend -n tars --timeout=60s

    echo "🎉 Frontend Deployment Finished!"
    exit 0
fi

# --- 2. BACKEND ONLY DEPLOY ---
if [ "${TARGET}" = "backend" ]; then
    echo "🔨 Step 1: Building Backend Docker image (127.0.0.1:5000/tars-backend:latest)..."
    cd "${PROJECT_ROOT}"
    docker build -t 127.0.0.1:5000/tars-backend:latest -t tars-backend:latest .

    echo "📦 Step 2: Pushing Backend image to local registry..."
    docker push 127.0.0.1:5000/tars-backend:latest

    echo "⚙️  Step 3: Applying Backend manifest..."
    kubectl apply -f "${PROJECT_ROOT}/k8s/03-backend.yaml"

    echo "🔄 Step 4: Rolling restart backend deployment..."
    kubectl rollout restart deployment tars-backend -n tars
    kubectl rollout status deployment tars-backend -n tars --timeout=60s

    echo "🎉 Backend Deployment Finished!"
    exit 0
fi

# --- 3. FULL DEPLOY (DEFAULT) ---
echo "🔨 Step 1-1: Building Backend Docker image (127.0.0.1:5000/tars-backend:latest)..."
cd "${PROJECT_ROOT}"
docker build -t 127.0.0.1:5000/tars-backend:latest -t tars-backend:latest .

echo "🔨 Step 1-2: Building Frontend Docker image (127.0.0.1:5000/tars-frontend:latest)..."
docker build -t 127.0.0.1:5000/tars-frontend:latest -t tars-frontend:latest -f frontend/Dockerfile frontend

echo "📦 Step 2: Pushing Docker images to local registry (127.0.0.1:5000)..."
docker push 127.0.0.1:5000/tars-backend:latest
docker push 127.0.0.1:5000/tars-frontend:latest

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
echo "📦 Applying SeaweedFS S3 Storage..."
kubectl apply -f "${PROJECT_ROOT}/k8s/07-seaweedfs.yaml"
kubectl apply -f "${PROJECT_ROOT}/k8s/03-backend.yaml"
kubectl apply -f "${PROJECT_ROOT}/k8s/08-frontend.yaml"

if [ -f "${PROJECT_ROOT}/k8s/04-cluster-issuer.yaml" ]; then
    echo "🔐 Step 4: Applying Cert-Manager ClusterIssuer & Ingress..."
    kubectl apply -f "${PROJECT_ROOT}/k8s/04-cluster-issuer.yaml" || echo "⚠️ cert-manager not yet ready, skip ClusterIssuer."
fi

if [ -f "${PROJECT_ROOT}/k8s/05-ingress.yaml" ]; then
    kubectl apply -f "${PROJECT_ROOT}/k8s/05-ingress.yaml"
fi

echo "🔄 Step 5: Rolling restart backend & frontend deployment to pick up any changes..."
kubectl rollout restart deployment tars-backend -n tars || true
kubectl rollout restart deployment tars-frontend -n tars || true

echo "================================================================="
echo "🎉 Deployment Applied Successfully!"
echo "📊 Current Status in namespace 'tars':"
kubectl get pods,svc,pvc,ingress -n tars
echo "================================================================="
echo "👉 Check backend logs:  kubectl logs -f deployment/tars-backend -n tars"
echo "👉 Check frontend logs: kubectl logs -f deployment/tars-frontend -n tars"
