#!/bin/sh
# Fetches the state gate.py reads into /data. See cluster/argocd/CLAUDE.md.
set -eu
target="${WORKLOAD_KIND:?}/${WORKLOAD_NAME:?}"
state="$WORKLOAD_NAME-upgrade-state"
k() { kubectl --cache-dir=/data/kube-cache "$@"; }

k get configmap "$state" --ignore-not-found -o jsonpath='{.data.stopped}' > /data/stopped
# A stale record would point a restore at an earlier sync's snapshot.
k delete configmap "$state" --ignore-not-found

k get "$target" -o json > /data/workload.json
k get pods -o json > /data/pods.json
if [ -n "${INTEGRITY_COMMAND:-}" ]; then
  rc=0
  k exec "$target" -- sh -c "$INTEGRITY_COMMAND" > /data/integrity.log 2>&1 || rc=$?
  echo "$rc" > /data/integrity.rc
fi
