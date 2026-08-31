#!/bin/sh
helm upgrade --install loki \
  oci://ghcr.io/grafana-community/helm-charts/loki \
  -n loki --create-namespace \
  -f values.yaml
