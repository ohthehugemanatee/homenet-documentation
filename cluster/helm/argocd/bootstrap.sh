#!/bin/bash
# One-time ArgoCD bootstrap. After initial install, ArgoCD manages itself.
set -euo pipefail

read -rsp "Enter Pushover app token for ArgoCD: " pushover_token
echo
read -rsp "Enter Pushover user key: " pushover_user_key
echo

helm repo add argo https://argoproj.github.io/argo-helm
helm repo update argo

kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic argocd-notifications-secret \
  -n argocd \
  --from-literal=pushoverToken="${pushover_token}" \
  --from-literal=pushoverUserKey="${pushover_user_key}" \
  --dry-run=client -o yaml | kubectl apply -f -

helm upgrade --install argocd argo/argo-cd \
  -n argocd \
  -f values.yaml

printf 'initial admin password: '
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d
echo
