#!/bin/sh
# Pin comes from the ArgoCD Application.
set -eu

app="$(dirname "$0")/../../argocd/apps/loki.yaml"
version=$(python3 -c '
import sys, yaml
sources = yaml.safe_load(open(sys.argv[1]))["spec"]["sources"]
print(next(s["targetRevision"] for s in sources if s.get("chart") == "loki"))
' "$app")

helm upgrade --install loki \
  oci://ghcr.io/grafana-community/helm-charts/loki \
  --version "$version" \
  -n loki --create-namespace \
  -f values.yaml
