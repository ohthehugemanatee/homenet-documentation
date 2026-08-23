# Longhorn

Longhorn v1.7.2, installed by `install.sh` (pinned to an upstream commit) into
`longhorn-system`. Custom StorageClasses live in `cluster/StorageClass/`.

`recurring-jobs.yaml` holds the snapshot/trim schedule. It is not wired into
ArgoCD — apply it by hand:

```sh
kubectl apply -f cluster/longhorn/recurring-jobs.yaml
```

Job names match the live `RecurringJob` CRs, so this adopts the running schedule
rather than creating a duplicate one.

## What is scheduled

| Job | Task | Cron (UTC) | Retain | Concurrency | Group | In git |
| --- | --- | --- | --- | --- | --- | --- |
| `daily-snapshots2` | `snapshot` | `33 4 * * ?` | 7 | 1 | `default` | yes |
| `snapshot-cleanup` | `snapshot-cleanup` | `3 3 * * *` | 0 | 1 | `default` | yes |
| `fs-trim` | `filesystem-trim` | `0 5 */6 * *` | 0 | 1 | `default` | yes |
| `backups` | `backup` (assumed) | `0 5 * * 1` | unknown | unknown | unknown | **no** |

`retain` only applies to `snapshot`; Longhorn ignores it for the other tasks,
where it reads 0.

## Snapshot is not backup

`daily-snapshots2` takes snapshots, which live on the volume's own replicas — a
dead node takes its snapshots with it. Only the weekly `backups` job produces a
durable copy, on the shoebox NFS backup target, which Duplicacy then carries
offsite. A schedule that lost `backups` and kept the snapshot jobs would still
look healthy in the UI while covering nothing durable.

## Coverage

All four jobs select `groups: [default]`. A Longhorn volume with no recurring-job
label of its own counts as a member of `default`, so the snapshot schedule covers
every Longhorn volume in the cluster — 20 of them, confirmed against a job run:

```
Got volumes from label recurring-job.longhorn.io/daily-snapshots2=enabled
Got volumes from label recurring-job-group.longhorn.io/default=enabled
Found 20 volumes with recurring job daily-snapshots2
```

That set is every Longhorn-backed PVC: the ten stateful app volumes (`duplicacy`,
`its-mytabs`, `mariadb`, `nextcloud-www`, `ombi`, `plex`, `radarr`, `sonarr`,
`songhub`, `unifi-db`), the three `/config` volumes migrated off NFS (`jackett`,
`nzbget`, `delugevpn`), `nextcloud-previews`, `nextcloud-mcp`, `plex-transcode`,
and the four monitoring volumes (`loki`, `prometheus`, `grafana`, `alertmanager`).

Two consequences of the catch-all worth knowing:

- Regenerable scratch is snapshotted daily along with everything else —
  `plex-transcode`, `loki`, `prometheus`, `alertmanager`, `nextcloud-previews`.
  That is 7 retained snapshots each of data nobody would restore.
- A new Longhorn volume is covered the moment it exists, with no per-volume
  labelling. `calibre` (#241) will be picked up automatically once migrated.

## Known gap

The `backups` job is still UI-only. Its cron (`0 5 * * 1`, Mondays 05:00 UTC) and
its name are recoverable from the `CronJob` Longhorn generates for it, but its
`task`, `retain`, `concurrency` and `groups` live in the `RecurringJob` CR, and
the `BackupTarget` config lives in a `BackupTarget` CR — neither is readable
without `get` on `longhorn.io` resources.

It is deliberately not transcribed on a guess: writing a wrong `retain` here and
applying it would change live backup retention. Codifying `backups` and the
`BackupTarget` closes #209; until then that half of the schedule can still drift.
