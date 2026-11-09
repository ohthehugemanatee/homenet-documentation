# Backup and restore

Backing up and restoring one Longhorn-backed claim of an app by hand. Every app
runs as a StatefulSet in `default`, with its state on one claim named
`<template>-<app>-0`. The examples use radarr; set the two variables for the
app in front of you:

```sh
app=radarr
claim=radarr-db-radarr-0
```

Both paths go through the CSI snapshot API and the `longhorn-backup`
`VolumeSnapshotClass` (`type: bak`), so every snapshot here is a Longhorn backup
on the shoebox NFS target. `cluster/longhorn/README.md` covers the schedule, the
class and why it is `bak`.

## Pausing an app

An auto-sync app self-heals: ArgoCD puts the replica count back as soon as you
scale it to 0. Pause its Application first, and resume it when you are done:

```sh
kubectl -n argocd annotate application "$app" argocd.argoproj.io/skip-reconcile=true
kubectl -n argocd annotate application "$app" argocd.argoproj.io/skip-reconcile-
```

The root app-of-apps leaves the annotation alone because it is not in git. A
paused Application gets no status updates, so its `on-sync-failed` and
`on-health-degraded` Pushover alerts stop until you resume it. Manual-sync apps
do not need the pause; they show `OutOfSync` until scaled back.

## Take a backup

Scaling to 0 first makes the backup clean-shutdown consistent. Detach follows
unmount, so waiting for the `VolumeAttachment` to go means the filesystem is
flushed.

```sh
kubectl -n argocd annotate application "$app" argocd.argoproj.io/skip-reconcile=true
kubectl -n default scale statefulset "$app" --replicas=0
kubectl -n default wait --for=delete "pod/$app-0" --timeout=5m
pv=$(kubectl -n default get pvc "$claim" -o jsonpath='{.spec.volumeName}')
while kubectl get volumeattachments -o jsonpath="{.items[?(@.spec.source.persistentVolumeName==\"$pv\")].metadata.name}" | grep -q .; do
  sleep 5
done

snap="$app-manual-$(date -u +%Y%m%d%H%M%S)"
kubectl -n default apply -f - <<YAML
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: $snap
spec:
  volumeSnapshotClassName: longhorn-backup
  source:
    persistentVolumeClaimName: $claim
YAML
kubectl -n default wait --for=jsonpath='{.status.readyToUse}'=true "volumesnapshot/$snap" --timeout=45m

kubectl -n default scale statefulset "$app" --replicas=1
kubectl -n argocd annotate application "$app" argocd.argoproj.io/skip-reconcile-
```

`readyToUse` takes about a minute for a small first backup; a volume with a
weekly backup chain uploads only the blocks changed since.

The class has `deletionPolicy: Delete`: deleting the `VolumeSnapshot` deletes
the backup on shoebox. Nothing prunes these, so delete it once you no longer
need it:

```sh
kubectl -n default get volumesnapshot
kubectl -n default delete volumesnapshot "$snap"
```

## Restore a claim from a VolumeSnapshot

A StatefulSet finds its claim by name, so a restore deletes the claim and
recreates it under the same name from the snapshot. The old Longhorn volume goes
with the claim (`reclaimPolicy: Delete`); its backups stay on shoebox as an
orphan `BackupVolume`, which nothing prunes.

```sh
snap=radarr-manual-20261109090000
size=$(kubectl -n default get volumesnapshot "$snap" -o jsonpath='{.status.restoreSize}')
class=$(kubectl -n default get pvc "$claim" -o jsonpath='{.spec.storageClassName}')

kubectl -n argocd annotate application "$app" argocd.argoproj.io/skip-reconcile=true
kubectl -n default scale statefulset "$app" --replicas=0
kubectl -n default wait --for=delete "pod/$app-0" --timeout=5m
# Every pod still naming the claim, Completed ones included.
kubectl -n default get pods -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.volumes[*].persistentVolumeClaim.claimName}{"\n"}{end}' \
  | awk -v c="$claim" '{for (i = 2; i <= NF; i++) if ($i == c) print $1}'
```

Delete each pod that lists, then the claim, and recreate it:

```sh
kubectl -n default delete pvc "$claim" --timeout=5m
kubectl -n default apply -f - <<YAML
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $claim
spec:
  storageClassName: $class
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: $size
  dataSource:
    apiGroup: snapshot.storage.k8s.io
    kind: VolumeSnapshot
    name: $snap
YAML
kubectl -n default scale statefulset "$app" --replicas=1
kubectl -n default wait --for=condition=Ready "pod/$app-0" --timeout=15m
kubectl -n argocd annotate application "$app" argocd.argoproj.io/skip-reconcile-
```

`size` must be at least the snapshot's `restoreSize`; a larger request is fine.
The restore runs while the claim provisions, so on a `WaitForFirstConsumer`
class (`longhorn-performance`) the claim stays `Pending` until the pod is
scheduled. A restore took 1m13s in the #212 drill, mostly provisioning and
attaching.

Delete the snapshot once the app is healthy, unless you want to keep it as a
backup.

## Restore from a weekly backup

The `backups` RecurringJob writes Longhorn backups that have no
`VolumeSnapshot`. Expose one through a pre-provisioned
`VolumeSnapshotContent`, the path `backup-verify` runs every Monday, then restore
from it as above.

List the backups of the claim's volume, newest last:

```sh
vol=$(kubectl -n default get pvc "$claim" -o jsonpath='{.spec.volumeName}')
kubectl -n longhorn-system get backups.longhorn.io --sort-by=.status.backupCreatedAt \
  -o custom-columns=NAME:.metadata.name,VOLUME:.status.volumeName,STATE:.status.state,CREATED:.status.backupCreatedAt,SIZE:.status.volumeSize \
  | awk -v v="$vol" 'NR == 1 || $2 == v'
```

If the claim is already gone, drop the `awk` filter and find the volume by date
and size, or in the Longhorn UI's Backup page. Pick a `Completed` backup:

```sh
backup=backup-0123456789abcdef
snap="$app-restore-$(date -u +%Y%m%d%H%M%S)"
kubectl apply -f - <<YAML
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotContent
metadata:
  name: $snap
spec:
  # Delete would remove the backup along with this object.
  deletionPolicy: Retain
  driver: driver.longhorn.io
  volumeSnapshotClassName: longhorn-backup
  source:
    snapshotHandle: bak://$vol/$backup
  volumeSnapshotRef:
    name: $snap
    namespace: default
---
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: $snap
  namespace: default
spec:
  volumeSnapshotClassName: longhorn-backup
  source:
    volumeSnapshotContentName: $snap
YAML
kubectl -n default wait --for=jsonpath='{.status.readyToUse}'=true "volumesnapshot/$snap" --timeout=5m
```

Then follow [Restore a claim from a VolumeSnapshot](#restore-a-claim-from-a-volumesnapshot)
with this `snap`. Afterwards delete both objects; `Retain` keeps the backup:

```sh
kubectl -n default delete volumesnapshot "$snap"
kubectl delete volumesnapshotcontent "$snap"
```

To look at a backup without touching the app, restore it into a claim with a
new name and mount that in a throwaway pod instead.

## When backup-verify pages

`backup-verify` runs Mondays at 11:00 UTC. A failure raises `KubeJobFailed` for
a `backup-verify-<n>` Job in namespace `backup-verify`. Its steps run as
containers in order: `fetch`, `currency`, `select`, then `restore`. Read each
log; a step that never started has none:

```sh
job=$(kubectl -n backup-verify get jobs -o name --sort-by=.metadata.creationTimestamp | tail -1)
for c in fetch currency select restore; do
  echo "== $c"; kubectl -n backup-verify logs "$job" -c "$c" || true
done
```

| Failed step | Meaning | Fix |
| --- | --- | --- |
| `fetch` | Could not read Longhorn's CRs | API server or RBAC; the log names it |
| `currency` | Named claims have no `Completed` backup from the last 8 days | See below |
| `select` | None of `RESTORE_CLAIMS` has a `Completed` backup | Same causes as `currency`, or a claim was renamed: update `RESTORE_CLAIMS` in `cluster/jobs/backup-verify.yaml` |
| `restore` | The restored claim did not provision or did not read back | The log names the claim and backup. Restore that backup by hand to see where it fails |

A stale claim usually means one of:

- The `backups` job did not run or failed. Check
  `kubectl -n longhorn-system get jobs --sort-by=.metadata.creationTimestamp`
  and `kubectl -n longhorn-system get backuptargets`; an unreachable shoebox NFS
  export fails every backup.
- The volume was detached all week. Longhorn skips recurring jobs on a
  detached volume. Attach it, or move it to a group without `backups`.
- The volume is retired but still exists. Delete the claim and its Longhorn
  volume; its backups stay on shoebox.

The restore step's cleanup deletes what it created. If that failed too,
`restore-<timestamp>` objects remain: delete the pod, claim and
`VolumeSnapshot` in `backup-verify`, then the cluster-scoped
`VolumeSnapshotContent` of the same name.

After the fix, run the check again and delete the failed Job. `KubeJobFailed`
keeps firing while a failed Job exists, and a passing run does not remove it:

```sh
kubectl -n backup-verify create job --from=cronjob/backup-verify "backup-verify-manual-$(date -u +%s)"
kubectl -n backup-verify delete "$job"
```

## Known snags

### A claim stays `Terminating`

The `kubernetes.io/pvc-protection` finalizer
holds it while any pod names it, including a `Completed` one. Find and delete
those pods with the listing in the restore section.

### A `VolumeSnapshot` stays `Terminating`

The snapshot-controller adds
`snapshot.storage.kubernetes.io/volumesnapshot-as-source-protection` while a
claim is provisioning from the snapshot, and a failed restore can leave it set.
Delete the claim restored from it first. If the finalizer is still there once no
claim is provisioning, remove that one finalizer; the `test` op refuses the
patch if the index points at a different one:

```sh
kubectl -n default get volumesnapshot "$snap" -o jsonpath='{.metadata.finalizers}'
kubectl -n default patch volumesnapshot "$snap" --type=json -p '[
  {"op": "test", "path": "/metadata/finalizers/0", "value": "snapshot.storage.kubernetes.io/volumesnapshot-as-source-protection"},
  {"op": "remove", "path": "/metadata/finalizers/0"}]'
```

Use the index the first command shows.
