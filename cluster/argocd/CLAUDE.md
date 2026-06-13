# cluster/argocd/CLAUDE.md — ArgoCD Application manifests

One Application manifest per managed workload in `apps/`. File names match the Application `metadata.name`: `<app-name>.yaml`.

## Conventions

- Every Application sets `metadata.namespace: argocd` explicitly.
- `spec.destination.namespace` matches the workload's actual namespace.
- **Auto-sync** (prune + self-heal): stable media and utility apps.
- **Manual sync** (no prune, no self-heal): infrastructure and complex stateful apps (nextcloud, collabora).
- All manual-sync apps get `notifications.argoproj.io/subscribe.on-out-of-sync.pushover: ""` annotation.
- All auto-sync apps get `on-sync-failed` and `on-health-degraded` notification annotations.
- Helm-sourced Applications use multi-source when the values file lives in this git repo.

## Verification

```sh
yamllint cluster/argocd/
kubeconform -strict -ignore-missing-schemas cluster/argocd/
```

ArgoCD CRD schemas are needed for kubeconform; CI installs them in the k3d test cluster.
