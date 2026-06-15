# cluster/helm/CLAUDE.md — values overrides for upstream charts

This directory holds **values overrides for upstream charts, NOT chart sources.** Three carve-outs:

- `argocd/` — ArgoCD GitOps controller. `bootstrap.sh` is a one-time install; after bootstrap ArgoCD manages itself and all other workloads.
- `collabora/` — hand-built chart (Collabora Online).
- `wip/` — experimental charts (`kube-plex`, `longhorn`, `mariadb-galera`, `percona-xtradb`). Incomplete by definition. Do **NOT** promote to root `helm/` without a spec + green smoke.

CI installs the upstream chart and applies the local `values.yaml` / `override.yaml`.

## Helm-specific verification — in addition to `cluster/CLAUDE.md` K8s checks

```sh
helm template <chart> cluster/helm/<chart> -f cluster/helm/<chart>/values.yaml \
  | kubeconform -strict -ignore-missing-schemas -
```

Run this for every touched chart override. For a real upgrade path, extend `.github/workflows/test-cluster.yaml`'s `helm upgrade --install --dry-run` invocation to cover the override.
