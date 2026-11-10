#!/bin/sh
# Fetches the state gate.py reads into /data. Usage: fetch.sh gate|watchdog.
# See cluster/argocd/CLAUDE.md.
set -eu
target="${WORKLOAD_KIND:?}/${WORKLOAD_NAME:?}"
state="$WORKLOAD_NAME-upgrade-state"
k() { kubectl --cache-dir=/data/kube-cache "$@"; }

if [ "${1:?}" = gate ]; then
  k get configmap "$state" --ignore-not-found -o jsonpath='{.data.stopped}' > /data/stopped
  # A stale record would point a restore at an earlier sync's snapshot.
  k delete configmap "$state" --ignore-not-found
else
  # The sync's apply puts back the replicas the snapshot step scaled away.
  left=300
  until [ "$(k get "$target" -o jsonpath='{.spec.replicas}')" -gt 0 ]; do
    if [ "$left" -le 0 ]; then
      echo "$target is still at 0 replicas" > /data/rollout.log
      break
    fi
    left=$((left - 5)); sleep 5
  done
  if [ ! -s /data/rollout.log ]; then
    if k rollout status "$target" --timeout="${WATCHDOG_TIMEOUT:?}" > /data/rollout.out 2>&1; then
      sleep "${WATCHDOG_SETTLE_SECONDS:?}"
    else
      cat /data/rollout.out > /data/rollout.log
    fi
  fi
fi

k get "$target" -o json > /data/workload.json
k get pods -o json > /data/pods.json
if [ -n "${INTEGRITY_COMMAND:-}" ]; then
  rc=0
  k exec "$target" -- sh -c "$INTEGRITY_COMMAND" > /data/integrity.log 2>&1 || rc=$?
  echo "$rc" > /data/integrity.rc
fi
