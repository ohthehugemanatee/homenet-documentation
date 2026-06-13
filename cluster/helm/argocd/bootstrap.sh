#!/bin/bash
# One-time ArgoCD bootstrap. After initial install, ArgoCD manages itself.
set -euo pipefail

helm repo add argo https://argoproj.github.io/argo-helm
helm repo update argo

helm upgrade --install argocd argo/argo-cd \
  -n argocd --create-namespace \
  -f values.yaml

printf 'initial admin password: '
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d
echo
