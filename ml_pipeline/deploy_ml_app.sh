#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "=== Step 1: Deleting Kubernetes services with label app=ml-app ==="
kubectl delete services -l app=ml-app --ignore-not-found=true
echo "Services deleted."

echo "=== Step 2: Deleting Kubernetes pods with label app=ml-app ==="
kubectl delete pods -l app=ml-app --ignore-not-found=true
echo "Pods deleted."

echo "=== Step 3: Building Docker image 'local-ml-app' ==="
docker build -t local-ml-app .
echo "Docker image built successfully."

echo "=== Step 4: Applying Kubernetes YAML configurations from 'k8s_yamls/' directory ==="
kubectl apply -f k8s_yamls/
echo "Kubernetes resources applied successfully."

echo "=== Deployment completed successfully ==="
