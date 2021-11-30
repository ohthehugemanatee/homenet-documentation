#!/bin/bash
set -eux

helm repo add bitnami https://charts.bitnami.com/bitnami
helm install galera bitnami/mariadb-galera -f values.yaml

