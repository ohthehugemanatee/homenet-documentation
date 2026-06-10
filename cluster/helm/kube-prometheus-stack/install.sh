#!/bin/sh
# Configures kube-prometheus stack with alertmanager/pushover.

read -p "Enter pushover user key: " user_key

read -p "Enter pushover app key: " app_key

kubectl create namespace monitoring

kubectl create secret generic alertmanager-pushover \
  -n monitoring \
  --from-literal=token=${app_key} \
  --from-literal=user_key=${user_key}

helm upgrade --install kube-prometheus-stack \
  oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack \
  -n monitoring --create-namespace \
  -f values.yaml
printf 'grafana password: '
kubectl get secret -n monitoring kube-prometheus-stack-grafana \
  -o jsonpath="{.data.admin-password}" | base64 --decode
echo
