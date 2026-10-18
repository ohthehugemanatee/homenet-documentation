#!/bin/sh
# Shared upgrade PostSync cleanup. See cluster/argocd/CLAUDE.md.
set -eu
state="${WORKLOAD_NAME:?}-upgrade-state"
k() { kubectl --cache-dir=/tmp/kube-cache "$@"; }
snapshot=$(k get configmap "$state" -o jsonpath='{.data.snapshot}')
# The class's deletionPolicy: Delete removes the backup along with the snapshot.
k delete volumesnapshot "${snapshot:?no snapshot recorded in $state}" --timeout=10m
k delete configmap "$state"
