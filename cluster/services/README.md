# README

Most of the services here are self-explanatory. BUT nextcloud is the most critical service I run, so it has an A/B deployment process for updates.

Everything you need is contained in the nextcloud-alpha.yaml file. There are persistent volumes and claims that I just leave standing in longhorn for mariadb and nextcloud configs; they are clones of the production db and config volumes which I only use for update purposes. I generally don't bother recreating them each time, so if something goes wrong that's probably the first thing to try. Burn the clones and recreate them, then try the upgrade again.

When you're done with the upgrade just kubectl delete the entire nextcloud-alpha.yaml file until next time.

## Storage placement

Longhorn holds application config and databases. NFS (`shoebox`) holds bulk media and file
storage, plus the Longhorn backup target. An app with no durable state gets no volume.

SQLite is the reason for the split: in WAL mode it does not work over a network filesystem,
because the `-shm` file needs real shared memory and NFS advisory locking is not reliable
enough for the rollback journal. Keeping a database and its WAL on one Longhorn volume also
means a single snapshot covers both.

`ombi`, `jackett`, `nzbget` and `delugevpn` carry the reference shape — whole `/config` on
a Longhorn `volumeClaimTemplate`, no overlay mount, no app-side path configuration.
`radarr`/`sonarr` (`/db`), `plex` (`Plug-in Support/Databases`) and `mariadb`
(`/config/databases`) instead overlay a Longhorn volume onto the database path only, with
the rest of `/config` still on NFS.

`calibre` is a third shape: one pod running both the `calibre` and `calibre-web` containers
on a single Longhorn volume, each container taking its own `subPath` for `/config` and
`calibre-web` mounting calibre's `subPath` again at `/calibre-library`. The subPaths sit
inside one volume, so a snapshot still covers the library and its WAL together. Two pods is
not an option: they would have to share the library over a network filesystem, which is the
hazard being removed, and a Longhorn RWO volume cannot be mounted twice.

`cluster/ansible/migrate-config-to-longhorn.yaml` stages the cutover for an app moving onto
Longhorn, in either shape. An app seeding several directories on one volume passes
`migrate_sources` and `migrate_scale_targets`; see that playbook's README for calibre's
invocation.

The #241 audit list is closed: no app keeps a SQLite database on `app-configs` any more.
What still mounts it holds configuration whose database already sits on Longhorn
(`radarr`/`sonarr`/`plex`/`mariadb`) or no database at all.

## Backups

Longhorn snapshot → Longhorn backup target on `shoebox` NFS → Duplicacy offsite. Duplicacy's
mount is the root of shoebox's storage device, so it covers the backup target and
`/export/configs` as well as media; only shoebox's own system config sits outside it.

A Longhorn snapshot is not a backup. Snapshots live on the volume's own replicas, so a dead
node takes its snapshots with it — only the backup-target copy is durable.

Longhorn's snapshot and backup schedule is configured in the Longhorn UI, not in git (#209).
