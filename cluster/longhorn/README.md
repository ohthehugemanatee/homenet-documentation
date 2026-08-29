# Longhorn

Longhorn v1.7.2, installed by `install.sh` from a pinned upstream commit into
`longhorn-system`. Custom StorageClasses live in `cluster/StorageClass/`.
`recurring-jobs.yaml` holds the schedule, `backup-target.yaml` the destination.
ArgoCD syncs neither. Names match the live CRs, so an apply adopts them:

```sh
kubectl apply -f cluster/longhorn/recurring-jobs.yaml
kubectl apply -f cluster/longhorn/backup-target.yaml
```

## What is scheduled

| Job | Task | Cron (UTC) | Retain | Concurrency | Group |
| --- | --- | --- | --- | --- | --- |
| `daily-snapshots2` | `snapshot` | `33 4 * * ?` | 7 | 1 | `default` |
| `snapshot-cleanup` | `snapshot-cleanup` | `3 3 * * *` | 0 | 1 | `default` |
| `fs-trim` | `filesystem-trim` | `0 5 */6 * *` | 0 | 1 | `default` |
| `backups` | `backup` | `0 5 * * 1` | 4 | 1 | `default` |

`retain` applies to `snapshot` and `backup` only; it reads 0 elsewhere. Nodes and
longhorn-manager run UTC.

## Chart values

`cluster/helm/longhorn/values.yaml` states this install as Longhorn chart 1.7.2
values, ahead of the ArgoCD adoption in #60.
`cluster/helm/longhorn/live-state.yaml` is the 29 Aug 2026 capture it was
written from, and the `Dry-run longhorn` step in `test-cluster.yaml` renders the
chart against it and fails when the two part.

Neither object is a chart object. The chart writes each into a ConfigMap in
`longhorn-system`, and longhorn-manager applies it, stamping what it applied
onto the StorageClass as `longhorn.io/last-applied-configmap`. A drifted render
reaches live config.

The `longhorn` StorageClass is entirely 1.7.2 default: `numberOfReplicas: "3"`,
`staleReplicaTimeout: "30"`, `fsType: ext4`, `dataLocality: disabled`,
`reclaimPolicy: Delete`, `volumeBindingMode: Immediate`. The values pin all of
it anyway. `parameters` are immutable and every Longhorn-backed PVC uses this
class, so a chart bump that moved a default would force a Replace; pinned, it
shows up as a diff on the values file instead. `staleReplicaTimeout` and
`volumeBindingMode` are template constants in this chart and cannot be pinned.

The three classes in `cluster/StorageClass/` are untouched. The chart renders no
StorageClass object at all, so it cannot duplicate them.

## Settings, and what drifted

Thirteen of the 88 `settings.longhorn.io` CRs differ from the Longhorn 1.7.2
built-in default, which is what the chart falls back to for each `~` in its
`defaultSettings`. None of it was in the repo. It accumulated over the two
years since the install. `values.yaml` records all thirteen, so the chart
asserts them instead of reverting them.

| Setting | 1.7.2 default | Live |
| --- | --- | --- |
| `backup-compression-method` | `lz4` | `gzip` |
| `backup-target` | *(empty)* | `nfs://shoebox:/longhorn-backups` |
| `concurrent-automatic-engine-upgrade-per-node-limit` | `0` | `5` |
| `default-data-locality` | `disabled` | `best-effort` |
| `default-replica-count` | `3` | `2` |
| `detach-manually-attached-volumes-when-cordoned` | `false` | `true` |
| `node-down-pod-deletion-policy` | `do-nothing` | `delete-both-statefulset-and-deployment-pod` |
| `node-drain-policy` | `block-if-contains-last-replica` | `allow-if-replica-is-stopped` |
| `orphan-auto-deletion` | `false` | `true` |
| `priority-class` | *(empty)* | `longhorn-critical` |
| `remove-snapshots-during-filesystem-trim` | `false` | `true` |
| `replica-auto-balance` | `disabled` | `best-effort` |
| `v2-data-engine-hugepage-limit` | `2048` | `1024` |

`disable-revision-counter: true` is a fourteenth entry in the rendered
ConfigMap. It sits at its built-in default, but the chart writes it regardless.

Two rows differ from the StorageClass by design. `default-data-locality` is
`best-effort` here and `dataLocality: disabled` in the class;
`default-replica-count` is 2 here and `numberOfReplicas: "3"` in the class. The
settings are what the UI stamps on a volume created outside a PVC; the class
parameters win for every PVC, and all 21 volumes came from one.

`backup-target` is also held by `backup-target.yaml`. Longhorn 1.7.2 keeps both
the setting and the `BackupTarget` CR, and they agree; change one and change the
other.

The other 67 settings sit at their default, bar 8 that longhorn-manager
maintains itself: `current-longhorn-version`, `crd-api-version`, and the image
and version settings. No chart value feeds those.

### Gap: the upgrade hooks

`preUpgradeChecker.jobEnabled` defaults true, so the chart renders
`longhorn-pre-upgrade` and `longhorn-post-upgrade` Jobs as Helm hooks. The live
cluster has never had either, because `deploy/longhorn.yaml` carries no hooks.
ArgoCD translates them into its own hooks and would run them on sync, and
upstream's chart README says to disable the setting under ArgoCD. Left unset
here, because it changes what a sync does rather than what is running now. #60
owns it.

## Snapshot is not backup

Snapshots live on the volume's own replicas, so a dead node takes them with it.
Only the weekly `backups` job writes a durable copy, to the shoebox NFS target
that Duplicacy carries offsite. Losing `backups` while keeping the snapshot jobs
leaves a healthy-looking UI covering nothing durable, and the weekly cadence
leaves a volume created on a Tuesday with no durable copy for six days.

## Coverage

All four jobs select `groups: [default]`, and Longhorn stamps
`recurring-job-group.longhorn.io/default: enabled` on each volume at creation.
All 21 carry it, so every Longhorn volume is covered with no manual labelling.
Removing the label does not opt a volume out: `datastore.FixupRecurringJob` runs
on both `CreateVolume` and `UpdateVolume`, and re-adds `default` to any volume
carrying zero job or group labels. Excluding a volume means giving it a
different group, via the `recurringJobSelector` StorageClass parameter.

Those 21 are every Longhorn-backed PVC: ten stateful app volumes (`duplicacy`,
`its-mytabs`, `mariadb`, `nextcloud-www`, `ombi`, `plex`, `radarr`, `sonarr`,
`songhub`, `unifi-db`), three `/config` volumes migrated off NFS (`jackett`,
`nzbget`, `delugevpn`), `nextcloud-previews`, `nextcloud-mcp`,
`calibre` (#268), and four monitoring volumes (`loki`, `prometheus`, `grafana`,
`alertmanager`). Those four plus `nextcloud-previews` are regenerable scratch,
snapshotted daily anyway. Narrowing that changes behaviour. Plex transcode was
the exception and is now an `emptyDir` (#277).

## Audit, 23 Aug 2026

`retain: 7` held 5 snapshots per volume, covering 4 days. Nothing ran on 18 or 19
Aug, spanning a cluster restart visible in the `csi-snapshotter` logs. 22 and 23
Aug ran at 02:33 rather than 04:33, and 23 Aug ran twice, while the `CronJob`
reported `lastScheduleTime` 04:33 throughout. The 02:33 runs are unexplained; a
double run costs two of the seven slots.

Backups outlive their volumes. 20 of 37 `BackupVolume` objects had no live
volume, the oldest last backed up 2024-08-02. `retain` prunes inside a live
volume's chain and never collects an orphan, so these grow without bound on
shoebox. Three `Backup` CRs sat in `Error`, all for the deleted `pvc-e3c59c7b`.

#277 deleted those three and 19 of the orphans, reclaiming 51 GiB. Eleven were
plex transcode, one per pod restart, which is why that volume moved to
`emptyDir`. The Longhorn system backup `pvc-6847cfb4` was kept deliberately.
Nothing prunes orphans automatically, so the set regrows whenever a volume is
retired and needs the same manual sweep.

No `snapshot.storage.k8s.io` API group is served: no `VolumeSnapshotClass`, no
snapshot-controller. Longhorn's `csi-snapshotter` sidecar runs but only watches
`VolumeSnapshotContent`. k3s does not install external-snapshotter, so snapshots
are reachable through Longhorn's own CRs and UI only.