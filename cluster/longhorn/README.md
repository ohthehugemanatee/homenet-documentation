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