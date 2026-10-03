#!/bin/sh
# Shared upgrade PreSync snapshot. See cluster/argocd/CLAUDE.md.
set -eu
target="${WORKLOAD_KIND:?}/${WORKLOAD_NAME:?}"
state="$WORKLOAD_NAME-upgrade-state"
k() { kubectl --cache-dir=/tmp/kube-cache "$@"; }
record() { k create configmap "$state" "$@" --dry-run=client -o yaml | k apply -f - >/dev/null; }
until_empty() {
  left=$1; shift
  while [ -n "$("$@")" ]; do
    [ "$left" -gt 0 ] || return 1
    left=$((left - 5)); sleep 5
  done
}

replicas=$(k get "$target" -o jsonpath='{.spec.replicas}')
selector=$(k get "$target" \
  -o go-template="{{range \$k, \$v := .spec.selector.matchLabels}}{{\$k}}={{\$v}},{{end}}")
pv=$(k get pvc "${CLAIM_NAME:?}" -o jsonpath='{.spec.volumeName}')
snapshot="$WORKLOAD_NAME-upgrade-$(date -u +%Y%m%d%H%M%S)"

restore() {
  rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "snapshot step failed; scaling $target back to $replicas replicas" >&2
    k scale "$target" --replicas="$replicas" || true
    k delete volumesnapshot "$snapshot" --ignore-not-found --wait=false || true
  fi
  exit "$rc"
}
trap restore EXIT

record --from-literal=replicas="$replicas"
k scale "$target" --replicas=0
until_empty 300 k get pods -l "${selector%,}" -o name
# Detach follows unmount, so the filesystem is flushed before the snapshot.
until_empty 300 k get volumeattachments \
  -o jsonpath="{.items[?(@.spec.source.persistentVolumeName==\"$pv\")].metadata.name}"
k apply -f - <<YAML
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: $snapshot
spec:
  volumeSnapshotClassName: ${SNAPSHOT_CLASS:?}
  source:
    persistentVolumeClaimName: $CLAIM_NAME
YAML
k wait --for=jsonpath='{.status.readyToUse}'=true "volumesnapshot/$snapshot" \
  --timeout="${SNAPSHOT_TIMEOUT:?}"
record --from-literal=replicas="$replicas" --from-literal=snapshot="$snapshot"
echo "$target is at 0 replicas; snapshot $snapshot of $CLAIM_NAME is ready."
