#!/bin/sh

helm repo add percona https://percona.github.io/percona-helm-charts/
helm repo update
helm install percona-op percona/pxc-operator
helm install percona-db percona/pxc-db --set backup.schedule.0.storageName="percona-backup" --set backup.storages.percona-backup='{}' --set
