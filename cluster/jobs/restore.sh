#!/bin/sh
# Weekly restore check: restore one backup into a scratch claim and read it all back.
# See cluster/longhorn/README.md.
set -eu
# restore_target.py writes this when it chose a backup.
# shellcheck source=/dev/null
[ ! -f /data/restore.env ] || . /data/restore.env
if [ -z "${SNAPSHOT_HANDLE:-}" ]; then
  echo "no restore target; skipping restore"
  exit 0
fi
ns=backup-verify
name="restore-$(date -u +%Y%m%d%H%M%S)"
k() { kubectl --cache-dir=/data/kube-cache "$@"; }

cleanup() {
  rc=$?
  # Pod before claim: a finished pod still holds its claim.
  k -n "$ns" delete pod "$name" --ignore-not-found --timeout=120s || rc=1
  k -n "$ns" delete pvc "$name" --ignore-not-found --timeout=300s || rc=1
  k -n "$ns" delete volumesnapshot "$name" --ignore-not-found --timeout=120s || rc=1
  k delete volumesnapshotcontent "$name" --ignore-not-found --timeout=120s || rc=1
  exit "$rc"
}
trap cleanup EXIT

echo "restoring ${CLAIM:?} from $SNAPSHOT_HANDLE"
k apply -f - <<YAML
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotContent
metadata:
  name: $name
  labels: {app.kubernetes.io/name: backup-restore}
spec:
  # Delete would remove the real backup along with this object.
  deletionPolicy: Retain
  driver: ${DRIVER:?}
  volumeSnapshotClassName: ${SNAPSHOT_CLASS:?}
  source: {snapshotHandle: "$SNAPSHOT_HANDLE"}
  volumeSnapshotRef: {name: $name, namespace: $ns}
---
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: $name
  namespace: $ns
  labels: {app.kubernetes.io/name: backup-restore}
spec:
  volumeSnapshotClassName: $SNAPSHOT_CLASS
  source: {volumeSnapshotContentName: $name}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $name
  namespace: $ns
  labels: {app.kubernetes.io/name: backup-restore}
spec:
  storageClassName: ${STORAGE_CLASS:?}
  accessModes: [ReadWriteOnce]
  resources: {requests: {storage: "${SIZE:?}"}}
  dataSource: {apiGroup: snapshot.storage.k8s.io, kind: VolumeSnapshot, name: $name}
---
apiVersion: v1
kind: Pod
metadata:
  name: $name
  namespace: $ns
  labels: {app.kubernetes.io/name: backup-restore}
spec:
  restartPolicy: Never
  # The *arr apps write as PUID 1000.
  securityContext: {runAsNonRoot: true, runAsUser: 1000, runAsGroup: 1000, seccompProfile: {type: RuntimeDefault}}
  containers:
    - name: read
      image: busybox:1.37
      # Legible means a database file is there and every file reads to the end.
      command: [sh, -c, 'find /restore -name "*.db" | grep -q . && find /restore -type f -exec cat {} + > /dev/null']
      securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: [ALL]}}
      resources: {requests: {cpu: 50m, memory: 32Mi}, limits: {memory: 32Mi}}
      volumeMounts: [{name: restored, mountPath: /restore, readOnly: true}]
  volumes: [{name: restored, persistentVolumeClaim: {claimName: $name, readOnly: true}}]
YAML

left=1800
until phase=$(k -n "$ns" get pod "$name" -o jsonpath='{.status.phase}') &&
    { [ "$phase" = Succeeded ] || [ "$phase" = Failed ]; }; do
  [ "$left" -gt 0 ] || { echo "restore did not finish within 30 minutes" >&2; exit 1; }
  left=$((left - 10)); sleep 10
done
k -n "$ns" logs "$name" || true
if [ "$phase" != Succeeded ]; then
  echo "the restored $CLAIM is not readable" >&2
  exit 1
fi
echo "$CLAIM restored and read back from $SNAPSHOT_HANDLE."
