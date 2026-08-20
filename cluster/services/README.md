# README

Most of the services here are self-explanatory. BUT nextcloud is the most critical service I run, so it has an A/B deployment process for updates.

Everything you need is contained in the nextcloud-alpha.yaml file. There are persistent volumes and claims that I just leave standing in longhorn for mariadb and nextcloud configs; they are clones of the production db and config volumes which I only use for update purposes. I generally don't bother recreating them each time, so if something goes wrong that's probably the first thing to try. Burn the clones and recreate them, then try the upgrade again.

When you're done with the upgrade just kubectl delete the entire nextcloud-alpha.yaml file until next time.

## Storage placement

**Normative, all apps:**

- **Longhorn** — all application config and databases. One volume per app, holding the whole
  `/config`.
- **NFS (shoebox)** — bulk media and file storage only, plus the Longhorn backup target.
- An app with no durable state gets no volume at all.

The reason is correctness, not tidiness. SQLite in WAL mode does not work over a network
filesystem: the `-shm` file needs real shared memory, and NFS advisory locking is not reliable
enough for the rollback journal either. The failure mode is a corrupt database on concurrent
access or an unclean pod termination — not rare on a cluster that restarts pods for every
image bump.

Keeping a database and its WAL on one Longhorn volume also makes a snapshot atomic over both,
which is what lets the whole upgrade-rollback mechanism below work without app-specific code.
A secondary benefit: apps stop depending on shoebox to start. Today, if shoebox or its export
is down, every app in the table below fails to mount and will not boot.

Most apps already follow the pattern — `ombi` holds its whole `/config` on Longhorn,
`radarr`/`sonarr` mount `<app>-db` at `/db`, `plex` overlays `plex-live-db` on its
`Plug-in Support/Databases` path, and `mariadb` mounts Longhorn at `/config/databases`. Whole
`/config` on Longhorn, as `ombi` does, is the shape to copy: no overlay mount and no app-side
path configuration.

Outstanding exceptions, tracked in #241:

| App | State | Status |
|---|---|---|
| `jackett` | SQLite + indexer definitions, tracker credentials, API key | on NFS, migrate |
| `nzbget` | SQLite + `nzbget.conf`, Usenet credentials | on NFS, migrate |
| `delugevpn` | SQLite + `core.conf`, `state/`, generated `wg0.conf` | on NFS, migrate |
| `calibre` | Library `metadata.db` (SQLite) | on NFS, migrate |
| `calibre-web` | JSON config only, no database | reads calibre's library |
| `redis` | none — `--appendonly no --save ""`, pure LRU cache | vestigial NFS mount, drop |

`calibre` and `calibre-web` are separate StatefulSets that both mount `subPath: calibre`, so
two pods on two nodes currently read and write one SQLite file over NFS — the worst case in
the audit. They collapse into a single pod with two containers sharing one Longhorn RWO
volume.

Regenerating jackett's API key breaks sonarr and radarr, which store it.

## Upgrade backup and rollback

One mechanism covers every app: an ArgoCD `PreSync` hook scales the workload to 0, snapshots
its Longhorn volume, and lets the sync proceed; `PostSync` validates; `SyncFail` restores the
snapshot. Since the upgrade restarts the pod anyway, the added downtime is close to zero.

**There is no app-layer dump/restore step, and none is needed.** A Longhorn snapshot is
crash-consistent — equivalent to pulling the power cord — and SQLite, InnoDB and journaled
MongoDB are all explicitly built to survive exactly that. They replay or roll back their
journal on next open. Scaling to 0 before the snapshot goes further and makes it
clean-shutdown-consistent, and it does so with no app-specific code: no Servarr backup API, no
Plex internal backup trigger, no Ombi export.

What a snapshot does not give you is loud failure on a database that is already corrupt — a
block snapshot preserves corruption faithfully, where a logical dump would error out. A
`PRAGMA integrity_check` in the `PostSync` validation covers that far more cheaply than a dump
pipeline. Dumps also give portability across schema versions and storage backends, which
matters for migrations but not for upgrade rollback.

So apps split into two classes, not four tiers:

| Class | Apps | Why |
|---|---|---|
| **Single-volume** | everything except nextcloud | One Longhorn volume holds all state; one atomic snapshot is a complete restore point |
| **Cross-system** | `nextcloud` + `mariadb` | Files on NFS, database in mariadb — two storage systems, no atomic cross-snapshot |

Nextcloud is the only genuine exception, and it is why the manual A/B procedure above still
exists. `unifi-mongodb` is single-volume and journaled, so it needs no bespoke handling.

## Backup chain

Three links, each doing a different job:

1. **Longhorn snapshot** — fast local rollback, seconds to restore. Lives inside the volume's
   own replicas.
2. **Longhorn backup target on shoebox NFS** — survives loss of a node. Currently scheduled in
   the Longhorn UI; moving that schedule into code is tracked in #209.
3. **Duplicacy** — offsite and versioned. Its NFS mount is the root of shoebox's storage
   device, so it covers everything there including the Longhorn backup target and
   `/export/configs`. Only shoebox's own system config is outside it.

**A Longhorn snapshot is not a backup.** Snapshots sit on the same replicas as the volume, so
a dead node takes its snapshots with it. Only link 2 is a backup, and it inherits offsite
coverage from link 3 for free.

In a full rebuild the order is: restore shoebox from Duplicacy, bring up k3s and Longhorn,
point it at the backup target, restore volumes. Longhorn restore depends on shoebox being up.

## Renovate note (#20)

`songhub.yaml` is pinned to a temporary fork build
(`ghcr.io/ohthehugemanatee/songhub:claude-ultimate-guitar-search-encoding-40prc8`) pending an
upstream merge. Renovate must not automerge over that pin.
