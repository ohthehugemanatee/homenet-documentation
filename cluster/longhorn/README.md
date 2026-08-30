# Longhorn

Longhorn v1.8.2, deployed by ArgoCD from `cluster/argocd/apps/longhorn.yaml`
(chart source, manual sync) into `longhorn-system`. Custom StorageClasses live
in `cluster/StorageClass/`. `recurring-jobs.yaml` holds the schedule,
`backup-target.yaml` the destination. ArgoCD syncs neither. Names match the
live CRs, so an apply adopts them:

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

`cluster/helm/longhorn/values.yaml` states this install as Longhorn chart 1.8.2
values. `live-state.yaml` beside it is the 29 Aug 2026 capture of what the
cluster runs, and `test-cluster.yaml`'s `Dry-run longhorn` step renders the
chart and fails when the two part.

Longhorn's StorageClass and its settings are not chart objects. The chart writes
each into a ConfigMap and longhorn-manager applies it, stamping the class with
`longhorn.io/last-applied-configmap`, so what the chart renders does reach live
config.

The `longhorn` StorageClass is entirely 1.7.2 default. The values pin it anyway,
because `parameters` are immutable and every Longhorn-backed PVC uses the class.
`staleReplicaTimeout` and `volumeBindingMode` are template constants in the
chart, so nothing pins those. 1.8 added `persistence.backupTargetName`,
defaulting to `"default"`; pinned to `""` for the same reason, since adding it
now would change the live, immutable `parameters`.

The three classes in `cluster/StorageClass/` are untouched. The chart renders no
StorageClass object, so it cannot duplicate them.

## Settings

Thirteen of the 88 `settings.longhorn.io` CRs sit off the Longhorn 1.7.2
built-in default, which is what the chart falls back to for each `~` in its
`defaultSettings`. `values.yaml` recorded all thirteen through 1.7.2; from
1.8 the chart stopped templating `backup-target` into
`longhorn-default-setting`, so `values.yaml` records the other twelve and
`backup-target.yaml`'s `BackupTarget` CR is `backup-target`'s only source.

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
ConfigMap, already at its built-in default. The chart writes it regardless.

Two rows differ from the StorageClass by design. `default-data-locality` is
`best-effort` here and `dataLocality: disabled` in the class;
`default-replica-count` is 2 against `numberOfReplicas: "3"`. These are what the
UI stamps on a volume created outside a PVC; the class parameters win for every
PVC, and all 21 volumes came from one.

`backup-target` was also held by `backup-target.yaml` under 1.7.2, which kept
both the setting and the `BackupTarget` CR in step. From 1.8 the chart no
longer templates a `backup-target` setting at all; `backup-target.yaml`'s
`BackupTarget` CR is the only place it lives now.

The other 67 sit at their default, bar 8 that longhorn-manager maintains itself:
`current-longhorn-version`, `crd-api-version`, and the image and version
settings.

### The upgrade hooks

`values.yaml` pins `preUpgradeChecker.jobEnabled` and `upgradeVersionCheck` to
true, so a sync renders `longhorn-pre-upgrade` (and, on an upgrade,
`longhorn-post-upgrade`) as ArgoCD `PreSync`/`PostSync` hooks. Upstream's chart
README says to disable the checker under ArgoCD. This repo keeps it enabled:
it enforces the sequential-minor rule and the faulted-volume block that the
five-hop upgrade chain (#281 through #285) depends on.

`cluster/argocd/hooks/longhorn/` runs its own faulted-volume gate one sync wave
ahead of `longhorn-pre-upgrade`, so a bad volume blocks the sync before the
chart's own Job starts. The gate itself fetches the volume and backing-image
state with `kubectl` in an initContainer, onto a shared `emptyDir`; the script
that decides pass or fail only ever reads that JSON, so a throttled or slow
API server is `kubectl`'s problem, not the readiness check's.

The initContainer's image is `alpine/kubectl`, not upstream's
`registry.k8s.io/kubectl`: that image is distroless and has no shell, so
`sh -c` fails at container init before `kubectl` ever runs. `backoffLimit: 0`
turns that single start failure into a failed `PreSync` hook, which is what
blocked the 1.7.2 → 1.8.2 hop the first time this gate ran (#294).

### CRDs stay OutOfSync on one field

The chart sets `spec.preserveUnknownFields: false` on 7 of its 22 CRDs. The
Kubernetes API server accepts only `false` there and drops the field from the
stored object, so it never round-trips and ArgoCD reports those 7 as
permanently OutOfSync. `cluster/argocd/apps/longhorn.yaml` carries an
`ignoreDifferences` entry for `/spec/preserveUnknownFields` on
`CustomResourceDefinition` to stop the false diff; nothing in the chart's own
values controls it.

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