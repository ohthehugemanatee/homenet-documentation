# cluster/longhorn/CLAUDE.md — Longhorn install + recurring jobs

`install.sh` installs Longhorn from a pinned upstream commit, not from a chart in
this repo. This directory holds that installer and the `RecurringJob` CRs.
StorageClasses are in `cluster/StorageClass/`. `README.md` here carries the
schedule table and the audit behind it; keep the two in sync.

## Never rename a job

`metadata.name` must match the live `RecurringJob` in `longhorn-system`. Longhorn
keys a schedule by name, so a rename creates a second job and leaves the original
running. That is why `daily-snapshots2` keeps its name.

`groups: [default]` is Longhorn's catch-all for volumes with no recurring-job
label, which is how every volume is covered without per-volume labelling.
Narrowing a job to an explicit group drops every unlabelled volume from it.

## Do not transcribe a job you cannot read

Guessing a `retain` for a `backup` task and applying it changes live backup
retention. Read the `RecurringJob` CR or the UI first, or record the job as a gap
in `README.md`, as `backups` is today.

## Verification

Namespace rules, kubeconform, kube-score and polaris are in `cluster/CLAUDE.md`.
Longhorn CRDs have no schema in the kubeconform store, so `--ignore-missing-schemas`
skips these CRs; `check_recurring_jobs.py` covers them instead. The k3d dry-run
excludes `recurring-jobs.yaml` for the same missing-CRD reason, as it does
`elasticsearch.yaml` and `probe-alerts.yaml`.

```sh
yamllint cluster/longhorn/
shellcheck cluster/longhorn/install.sh
python3 .github/scripts/check_recurring_jobs.py
```
