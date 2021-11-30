#!/bin/sh

helm repo add percona https://percona.github.io/percona-helm-charts/
helm repo update
helm install percona-op percona/pxc-operator
helm install percona-db percona/pxc-db -f values.yaml
