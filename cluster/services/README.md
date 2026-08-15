# README

Most of the services here are self-explanatory. BUT nextcloud is the most critical service I run, so it has an A/B deployment process for updates.

Everything you need is contained in the nextcloud-alpha.yaml file. There are persistent volumes and claims that I just leave standing in longhorn for mariadb and nextcloud configs; they are clones of the production db and config volumes which I only use for update purposes. I generally don't bother recreating them each time, so if something goes wrong that's probably the first thing to try. Burn the clones and recreate them, then try the upgrade again.

When you're done with the upgrade just kubectl delete the entire nextcloud-alpha.yaml file until next time.

## Upgrade risk tiers

Every workload sits in one of four upgrade-risk tiers (full model in #206). The tier decides
whether an image bump needs a backup/validate/rollback pipeline, and whether Renovate may
automerge it. This section records the audit behind the media-app classification (#208).

| App | State it holds | Where that state lives | Tier |
|---|---|---|---|
| `jackett` | Indexer definitions, tracker credentials, API key | NFS `app-configs`, `subPath: jackett` | A — pending SQLite check |
| `nzbget` | `nzbget.conf`, Usenet credentials; queue is transient | NFS `app-configs`, `subPath: nzbget` | A — pending SQLite check |
| `delugevpn` | `core.conf`, `state/` torrent list + resume data, generated `wg0.conf` | NFS `app-configs`, `subPath: delugevpn` | A — pending SQLite check |
| `calibre` / `calibre-web` | Library `metadata.db`; calibre-web `app.db` (users, shelves, read progress) | NFS `app-configs`, `subPath: calibre` / `calibre-web` | **not A** — SQLite, not regenerable |
| `its-mytabs` | Curated tab library + YouTube timing sync points | Longhorn, 2Gi at `/app/data` | B, snapshot-only |
| `songhub` | Saved `*.ultimatetab.json`, `.synced` / `.remarkable-sync-state` markers | Longhorn, 5Gi at `/app/saved-tabs` | B, snapshot-only |

Regenerating jackett's API key breaks sonarr and radarr, which store it. Deluge and nzbget
recover by re-adding downloads. Losing songhub's `.synced` markers re-uploads every tab to
reMarkable — annoying, not costly. `its-mytabs` and `songhub` have no native backup or export
facility, so Tier B is by #206's rule; both are single-writer, so a whole-volume Velero
snapshot is enough and no bespoke dump hook is needed. That makes them the cheapest pilots
for the Tier B plumbing.

### Absence of a Longhorn PVC does not mean stateless

#206 originally read "no Longhorn PVC" as "no state worth protecting". It isn't. All four
Tier A candidates mount `/config` from the `app-configs` PVC — a static NFS PV with no CSI
driver (`../storage/pv-shoebox-config.yaml` → `shoebox:/export/configs/config`, empty
`storageClassName`, `Retain`) — under a per-app `subPath`. None uses `emptyDir` or `hostPath`,
so config does survive a pod replace. It is simply on NFS instead of Longhorn.

`calibre` is where that distinction stops holding. `calibre-web` sets
`CALIBRE_PATH=/calibre-library/Calibre Library` against `subPath: calibre` — the same
directory calibre itself mounts at `/config` — so the library `metadata.db` sits with the
config, not with the book files under `/books`. That is the SQLite-database class that pulled
`plex/sonarr/radarr/ombi` out of Tier A in the earlier pass, reached the same way.

### SQLite on NFS

SQLite in WAL mode does not work over a network filesystem: the `-shm` file needs real shared
memory, and NFS advisory locking is not reliable enough for the rollback journal either. The
failure mode is a corrupt database on concurrent access or an unclean pod termination — not
rare on a cluster that restarts pods for every image bump. This is a live correctness hazard,
independent of the upgrade-tier question.

Ten manifests mount `app-configs`: `jackett, nzbget, delugevpn, calibre, plex, radarr, sonarr,
mariadb, nextcloud, redis`. Most already carve their database out onto Longhorn:

| App | Longhorn carve-out |
|---|---|
| `ombi` | whole `/config` on Longhorn; no NFS config at all |
| `radarr`, `sonarr` | `<app>-db` 3Gi at `/db`, config stays on NFS |
| `plex` | `plex-live-db` 20Gi overlaid on the `Plug-in Support/Databases` path |
| `mariadb` | Longhorn at `/config/databases`, config on NFS |
| `redis` | none needed — `--appendonly no --save ""`, pure LRU cache, writes nothing |

That leaves `jackett, nzbget, delugevpn, calibre, calibre-web` as the only apps with
potentially SQLite-backed state and no Longhorn carve-out. `ombi` is the pattern to copy —
whole `/config` on a Longhorn PVC is simpler than an overlay and needs no app-side path
config. Moving them also closes a gap in #206's own design: Tier A2 fixes rollback as a Velero
Longhorn-snapshot `Restore` CR, which structurally cannot reach a static NFS PV with no CSI
driver. Once the databases are on Longhorn, one snapshot mechanism covers every tier.

`calibre` is the exception. `calibre` and `calibre-web` are separate StatefulSets sharing one
directory, which a Longhorn RWO volume cannot serve. Longhorn RWX would, but it fronts the
volume with a share-manager NFS export — reintroducing the hazard being removed. Collapsing
the two into one pod with two containers is the likely answer, and needs its own spec.

### Pending operator confirmation

Classification above was derived from the manifests; the cluster was not reachable when it was
written. Two claims are still inferred:

- Which apps actually hold SQLite, and which are in WAL mode. On shoebox:
  `find /export/configs/config -maxdepth 3 \( -name '*.db' -o -name '*-wal' -o -name '*-shm' \) -ls`.
  `metadata.db` and `app.db` are visible in the calibre manifests; jackett's config reads as
  JSON, nzbget's as plain text, deluge's as a pickled `state/`. Any app the `find` confirms
  holds SQLite moves out of Tier A alongside calibre.
- Whether `/export/configs` is inside any Duplicacy backup set. The in-cluster Duplicacy pod
  mounts only `shoebox-storage` (`/export/storage`), and its schedule and sources live in its
  web UI, not in git. If the config export is unbacked, so is every app in the table above.

### Renovate note (#20)

`songhub.yaml` is pinned to a temporary fork build
(`ghcr.io/ohthehugemanatee/songhub:claude-ultimate-guitar-search-encoding-40prc8`) pending an
upstream merge. Renovate must not automerge over that pin.
