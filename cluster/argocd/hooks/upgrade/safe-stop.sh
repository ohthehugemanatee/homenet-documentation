#!/bin/sh
# Shared upgrade watchdog: on a failed verdict, restore the claim and stop the app.
# See cluster/argocd/CLAUDE.md.
set -eu
target="${WORKLOAD_KIND:?}/${WORKLOAD_NAME:?}"
state="$WORKLOAD_NAME-upgrade-state"
k() { kubectl --cache-dir=/tmp/kube-cache "$@"; }

if [ "$(cat /data/verdict)" = 0 ]; then
  echo "$target is healthy after the sync."
  exit 0
fi

snapshot=$(k get configmap "$state" --ignore-not-found -o jsonpath='{.data.snapshot}')
echo "$target failed its checks after the sync; stopping it." >&2
# Self-heal would undo the scale-down.
k -n argocd annotate application "${ARGOCD_APP:?}" argocd.argoproj.io/skip-reconcile=true --overwrite
k scale "$target" --replicas=0
selector=$(k get "$target" \
  -o go-template="{{range \$k, \$v := .spec.selector.matchLabels}}{{\$k}}={{\$v}},{{end}}")
left=300
while [ -n "$(k get pods -l "${selector%,}" -o name)" ]; do
  [ "$left" -gt 0 ] || { echo "pods of $target did not stop within 5 minutes" >&2; exit 1; }
  left=$((left - 5)); sleep 5
done
# pvc-protection holds the claim for any pod naming it, Completed ones included.
for pod in $(k get pods -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.volumes[*].persistentVolumeClaim.claimName}{"\n"}{end}' \
    | awk -v c="${CLAIM_NAME:?}" '{for (i = 2; i <= NF; i++) if ($i == c) print $1}'); do
  k delete pod "$pod" --timeout=120s
done
# Tells the next sync's gate that 0 replicas is this stop, not a fault.
k create configmap "$state" --from-literal=stopped=true --from-literal=snapshot="$snapshot" \
  --dry-run=client -o yaml | k apply -f - >/dev/null

if [ -z "$snapshot" ]; then
  echo "this sync recorded no snapshot; $CLAIM_NAME is left as it is." >&2
  exit 1
fi
size=$(k get volumesnapshot "$snapshot" -o jsonpath='{.status.restoreSize}')
class=$(k get pvc "$CLAIM_NAME" -o jsonpath='{.spec.storageClassName}')
k delete pvc "$CLAIM_NAME" --timeout=300s
k apply -f - <<YAML
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $CLAIM_NAME
spec:
  storageClassName: $class
  accessModes: [ReadWriteOnce]
  resources: {requests: {storage: "${size:?}"}}
  dataSource: {apiGroup: snapshot.storage.k8s.io, kind: VolumeSnapshot, name: $snapshot}
YAML
echo "restored $CLAIM_NAME from $snapshot; $target is at 0 replicas and Application $ARGOCD_APP is paused." >&2
exit 1
