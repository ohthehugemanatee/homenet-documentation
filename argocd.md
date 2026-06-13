# ArgoCD — GitOps for the k3s cluster

ArgoCD continuously reconciles the cluster against this git repo. Every workload has an ArgoCD Application manifest in `cluster/argocd/apps/`.

## Architecture

**App-of-apps pattern:** A root Application (`cluster/argocd/apps/root.yaml`) watches `cluster/argocd/apps/` and auto-syncs child Applications. Adding a new Application YAML to that directory registers it automatically.

**Sync policies:**

| Category | Sync | Self-heal | Prune | Apps |
|---|---|---|---|---|
| Media | auto | yes | yes | plex, radarr, sonarr, ombi, jackett, nzbget, delugevpn, calibre |
| Utilities | auto | yes | yes | duplicacy, cloudflare-ddns, mariadb, redis, unifi, ingress-only, jobs |
| Stateful | manual | no | no | nextcloud, collabora |
| Infrastructure | manual | no | no | metallb-config, storageclasses, cluster-base, default-limits, traefik-config, external-dns, nodelocaldns, storage, configmaps |
| Monitoring (Helm) | manual | no | no | kube-prometheus-stack, loki, alloy, nfs-provisioner |

Auto-sync apps self-heal when someone `kubectl edit`s a managed resource. Manual-sync apps alert on drift but wait for operator approval in the ArgoCD UI.

## Access

- **LAN:** `argocd.vert` or `argocd.cluster.vert` (Traefik ingress, no TLS — internal only)
- **Mobile:** same URLs; ArgoCD's UI is responsive

## Drift alerts

ArgoCD's notification controller sends directly to Pushover (not through Alertmanager):

- **OutOfSync** — normal priority, fires for manual-sync apps when cluster state diverges from git
- **Sync failed** — high priority, fires when an auto-sync or manual sync errors
- **Health degraded** — high priority, fires when a managed app becomes unhealthy

Credentials live in the `argocd-notifications-secret` Secret (created by `bootstrap.sh`, never committed).

## Bootstrap

One-time setup on a fresh cluster (or first install):

```sh
cd cluster/helm/argocd
./bootstrap.sh
# Creates namespace, Pushover secret, installs ArgoCD Helm chart
# Prints initial admin password

# Apply the root app-of-apps
kubectl apply -f ../../argocd/apps/root.yaml
```

After bootstrap, ArgoCD discovers all child Applications and begins reconciling.

## Adding a new workload

1. Create the workload manifest in `cluster/services/<name>.yaml` (or appropriate directory).
2. Create `cluster/argocd/apps/<name>.yaml` — see existing Applications for templates.
3. Choose sync policy: `automated` (prune + selfHeal) for stable apps, omit `syncPolicy.automated` for manual.
4. Add notification annotations per `cluster/argocd/CLAUDE.md` conventions.
5. Commit and push; the root app-of-apps picks it up automatically.

## Helm-sourced Applications

Monitoring stack and NFS provisioner use ArgoCD multi-source: the chart comes from an upstream registry, values come from this git repo via `$values` ref. Pin chart versions in `spec.sources[].targetRevision`.

## Relationship to install.sh scripts

The `install.sh` / `install-*.sh` scripts in `cluster/helm/` and `cluster/longhorn/` predate ArgoCD. Their secret-creation portions remain necessary for bootstrap. The `helm upgrade` / `kubectl apply` portions are superseded by ArgoCD — do not use them for ongoing management.
