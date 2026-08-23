# cluster/longhorn/CLAUDE.md — Longhorn install + recurring jobs

Longhorn itself is installed by `install.sh` against a pinned upstream commit,
not by a chart in this repo. This directory holds that installer and the
`RecurringJob` CRs. StorageClasses are in `cluster/StorageClass/`; the schedule
table and the audit behind it are in `README.md` here — keep the two in sync.

## Names and groups are load-bearing

`metadata.name` must match the live `RecurringJob` in `longhorn-system`. Longhorn
keys a schedule by name, so a rename does not edit a job — it creates a second
one and leaves the original running. `daily-snapshots2` keeps its unlovely name
for exactly this reason.

`groups: [default]` is Longhorn's catch-all for volumes carrying no recurring-job
label, which is how every volume is covered without per-volume labelling.
Narrowing a job to an explicit group silently drops every unlabelled volume.

## Do not transcribe a job you cannot read

Guessing a `retain` for a `backup` task and applying it changes live backup
retention. Read the `RecurringJob` CR or the UI first, or leave the job out and
record it as a gap in `README.md` — as `backups` is today.

## Verification

Foundation (namespace rules, kubeconform, kube-score, polaris) is in
`cluster/CLAUDE.md`. Longhorn CRDs have no schema in the kubeconform store, so
`--ignore-missing-schemas` skips these CRs — their structural checks come from
`.github/scripts/check_recurring_jobs.py` instead.

```sh
yamllint cluster/longhorn/
shellcheck cluster/longhorn/install.sh
python3 .github/scripts/check_recurring_jobs.py
```
