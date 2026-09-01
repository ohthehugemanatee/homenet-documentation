# cluster/longhorn/CLAUDE.md — Longhorn install + recurring jobs

ArgoCD deploys Longhorn from `cluster/argocd/apps/longhorn.yaml`, a Helm
Application pinned to chart 1.9.2. This directory holds the `RecurringJob` CRs
and the `BackupTarget`. Both are applied by hand and adopted by name; ArgoCD
manages neither. StorageClasses are in `cluster/StorageClass/`. The chart
values and the live capture behind them are in `cluster/helm/longhorn/`.
`README.md` carries the schedule table, the settings drift table and the audit
behind them; keep it in sync with all three.

## Never rename, never guess

`metadata.name` must match the live CR in `longhorn-system`. Longhorn keys a
schedule by name, so a rename creates a second job and leaves the original
running. That is why `daily-snapshots2` keeps its name; likewise
`BackupTarget/default`.

`groups: [default]` covers every volume because Longhorn stamps
`recurring-job-group.longhorn.io/default: enabled` at volume creation. Narrowing
a job to an explicit group drops every volume lacking that group's label.

Guessing a `retain` for a `backup` task and applying it changes live retention.
Read the CR or the UI first, or record the job as a gap in `README.md`.

## Verification

Namespace rules, kubeconform, kube-score and polaris are in `cluster/CLAUDE.md`.
Longhorn CRDs have no kubeconform schema, so `--ignore-missing-schemas` skips
these CRs and `check_recurring_jobs.py` covers them instead. The k3d dry-run
excludes both manifests for the same reason, as it does `elasticsearch.yaml` and
`probe-alerts.yaml`.

```sh
yamllint cluster/longhorn/
python3 .github/scripts/check_recurring_jobs.py
```
