#!/bin/sh
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
helm upgrade --install -n loki loki grafana/loki-stack  --set grafana.enabled=true,prometheus.enabled=true,loki.persistence.enabled=true,loki.persistence.size=5Gi
# nb: if the helm chart is still running kube-state-metrics 1.x, you need to edit the Deployment to nodeSelector amd64
kubectl apply -f ../../services/grafana.yaml
echo -n "password: "
kubectl get secret --namespace loki loki-grafana -o jsonpath="{.data.admin-password}" | base64 --decode ; echo

