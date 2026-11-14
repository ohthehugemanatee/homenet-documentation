#!/usr/bin/env bash
set -euo pipefail

kubectl -n "$NAMESPACE" create secret generic mariadb \
  --from-literal=rootpass=ci-root-password \
  --from-literal=nextcloudpass=ci-nextcloud-password
