# reMarkable sync

How I sync my reMarkable 2 to NextCloud (and eventually OneDrive, OneNote) on this cluster, using my own self-hosted cloud replacement.

This is **my deployment**, not the upstream contract. For the normative spec, the install guide, ADRs, and anything-portable, see [ohthehugemanatee/remarkable-onenote](https://github.com/ohthehugemanatee/remarkable-onenote).

## What runs where

Two services run together in the cluster:

- **rmfakecloud** — the reMarkable cloud replacement (https://github.com/ddvk/rmfakecloud). Talks the tablet protocol, stores documents on disk.
- **rmsync** — my integration layer above rmfakecloud (this is the repo at `remarkable-onenote`). Watches rmfakecloud's filesystem store, ships documents to NextCloud and (later) OneDrive/OneNote.

Both services share a domain behind Traefik with cert-manager / Let's Encrypt. Paths route as:
- `/api/*`, `/storage/*`, `/sync/*` → rmfakecloud
- `/ui/*`, `/healthz`, `/auth/*` → rmsync
- `/` → rmfakecloud's web UI (pairing flow)

## Cluster details specific to my setup

- **Domain**: a subdomain of a domain I own, resolved publicly so the tablet can reach it from cellular as well as LAN. Cert-manager issues a Let's Encrypt cert via DNS-01 (existing wildcard pattern; see `cluster/services/cert-manager.yaml` for the issuer).
- **Ingress**: Traefik IngressRoute, same pattern as my other public services (`cluster/services/`-flat directory).
- **State storage**: Longhorn 1Gi PVC for `state.db` (latency-sensitive, single-replica acceptable because it's rebuildable).
- **Archive cache + rmfakecloud user store**: NFS from `warehouse`, ~50Gi for both combined. NFS is fine here — the watcher does its own atomicity guards regardless of FS semantics.
- **Secrets**: backend credentials in a Sealed Secret per backend; pulled into the rmsync pod via env files.

## What I'm syncing

A starter `rules.yaml`:

```yaml
rules:
  - id: work
    match: { folder: "/Work" }
    backends:
      - name: nextcloud
        direction: sync
  - id: archive-everything
    match: { type: notebook }
    backends:
      - name: nextcloud
        direction: archive
        target_folder: "/rM-Archive"
on_rule_exit: archive
rule_overlap: union
```

Everything I write on the tablet gets archived to NextCloud's `/rM-Archive` (one folder per notebook with `strokes.rm` + `document.pdf` + `strokes.svg` + `manifest.json`). Anything under `/Work` two-way syncs.

P3 will add OCR; until then full-text search on the PDFs is whatever NextCloud's tesseract extractor finds — which is nothing useful on raw handwriting, but works fine on imported PDFs that already have a text layer.

## Tablet setup

One-time:

1. Pair the tablet against rmfakecloud's web UI at the chosen domain.
2. Rewrite `xochitl.conf` to point at the same domain (the standard rmfakecloud procedure; see https://ddvk.github.io/rmfakecloud/install/).
3. No CA install needed — the cert is Let's Encrypt, the tablet trusts it out of the box.

If a future firmware breaks `xochitl.conf` rewriting, fallback options are documented at rmfakecloud upstream. Not my problem to solve in this repo.

## Backup

- **mirror_pull_tombstones** table: backed up daily via a CronJob that runs `sqlite3 state.db ".dump mirror_pull_tombstones"` into the warehouse NFS archive directory. Cannot be reconstructed from anywhere else (ADR-0002).
- **rmfakecloud user store**: backed up nightly via `restic` snapshot of the NFS path.
- **state.db** (everything except tombstones): not backed up. Rebuildable.
- **Archive cache**: not backed up. Rebuildable from state.db + rmfakecloud's store.

## Troubleshooting

- **Tablet sync stalled**: rmfakecloud is the layer doing the sync. Check its logs in the cluster. rmsync only watches the filesystem afterwards.
- **Documents not appearing on NextCloud**: check rmsync's `/ui/events` page. If routing decision is empty, the rules.yaml didn't match.
- **Conflict folder filling up on NextCloud**: my default is `rm_wins` (ADR-0004) which means NextCloud-side edits diverge into `/Conflicts/`. Either change to `branch` policy per-rule, or stop editing on NextCloud.

## Manifests

(Will be added under `cluster/services/` after P2 ships: `rmfakecloud.yaml` and `rmsync.yaml`.)
