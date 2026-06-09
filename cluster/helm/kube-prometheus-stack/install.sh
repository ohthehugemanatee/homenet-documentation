#!/bin/sh
helm upgrade --install kube-prometheus-stack \
  oci://ghcr.io/prometheus-community/helm-charts/kube-prometheus-stack \
  -n monitoring --create-namespace \
  -f values.yaml
printf 'grafana password: '
kubectl get secret -n monitoring kube-prometheus-stack-grafana \
  -o jsonpath="{.data.admin-password}" | base64 --decode
echo
