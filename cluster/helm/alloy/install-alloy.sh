#!/bin/sh
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update grafana
helm upgrade --install alloy grafana/alloy \
  -n monitoring --create-namespace \
  -f values.yaml
