# cluster/helm/CLAUDE.md — values overrides for upstream charts

This directory holds **values overrides for upstream charts, NOT chart sources.** Three carve-outs:

- `argocd/` — ArgoCD GitOps controller. `bootstrap.sh` is a one-time install; after bootstrap ArgoCD manages itself and all other workloads.
- `collabora/` — hand-built chart (Collabora Online).
- `wip/` — experimental charts (`kube-plex`, `mariadb-galera`, `percona-xtradb`). Incomplete by definition. Do **NOT** promote to root `helm/` without a spec + green smoke.

CI installs the upstream chart and applies the local `values.yaml` / `override.yaml`.

## Helm-specific verification — in addition to `cluster/CLAUDE.md` K8s checks

```sh
helm template <chart> cluster/helm/<chart> -f cluster/helm/<chart>/values.yaml \
  | kubeconform -strict -ignore-missing-schemas -cache ~/.cache/kubeconform -
```

Run this for every touched chart override. For a real upgrade path, extend `.github/workflows/test-cluster.yaml`'s `helm upgrade --install --dry-run` invocation to cover the override.

A dry-run does not catch a values key the chart stopped reading — helm merges an unknown key and ignores it. `.github/scripts/check_helm_values_keys.py` does, and `test-cluster.yaml` runs it over `loki/`. Point it at another override when you bump that chart's pin:

```sh
helm show values <chart> --version <pin> > /tmp/chart-values.yaml
python3 .github/scripts/check_helm_values_keys.py \
  --chart-values /tmp/chart-values.yaml \
  --overrides cluster/helm/<chart>/values.yaml \
  --passthrough <block the chart copies into another program's config>
```
