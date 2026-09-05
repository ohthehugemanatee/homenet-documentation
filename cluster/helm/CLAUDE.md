# cluster/helm/CLAUDE.md — values overrides for upstream charts

This directory holds **values overrides for upstream charts, NOT chart sources.** Two carve-outs:

- `argocd/` — ArgoCD GitOps controller. `bootstrap.sh` is a one-time install; after bootstrap ArgoCD manages itself and all other workloads.
- `collabora/` — hand-built chart (Collabora Online).

CI installs the upstream chart and applies the local `values.yaml`.

## Helm-specific verification — in addition to `cluster/CLAUDE.md` K8s checks

```sh
helm template <chart> cluster/helm/<chart> -f cluster/helm/<chart>/values.yaml \
  | kubeconform -strict -ignore-missing-schemas -cache ~/.cache/kubeconform -
```

Run this for every touched chart override. For a real upgrade path, extend `.github/workflows/test-cluster.yaml`'s `helm upgrade --install --dry-run` invocation to cover the override.

A dry-run renders green on a values key the chart stopped reading, since helm merges an unknown key and ignores it. `check_helm_values_keys.py` catches that; `test-cluster.yaml` runs it over `loki/`. Point it at another override when you bump that chart's pin:

```sh
helm show values <chart> --version <pin> > /tmp/chart-values.yaml
python3 .github/scripts/check_helm_values_keys.py \
  --chart-values /tmp/chart-values.yaml \
  --overrides cluster/helm/<chart>/values.yaml \
  --passthrough <block the chart copies into another program's config>
```
