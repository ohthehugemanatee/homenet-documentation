# ADR-0005: Cluster-workload operations are Ansible playbooks

- **Status:** accepted
- **Date:** 2026-08-22

## Context

Moving SQLite app config off NFS onto Longhorn (#241) is a live data migration that
runs once per app: suspend ArgoCD auto-sync, stop the workload, stage a Longhorn PVC
under the exact name the new StatefulSet will adopt, copy and verify, restore sync.
Four apps will go through it. Run by hand, the steps that get skipped are the ones
with no visible consequence until later — a mis-derived PVC name silently provisions
an empty volume, and jackett then mints an API key that sonarr and radarr do not have.

`cluster/ansible/` held only node-OS provisioning (ADR-0002). Nothing in the repo
automated an operation *against* the cluster.

## Decision

Cluster-workload operations are Ansible playbooks in `cluster/ansible/`, using
`kubernetes.core` modules with `k8s_kubeconfig`, the same contract the rolling-upgrade
playbooks already use for kubectl work. `migrate-config-to-longhorn.yaml` is the first.
Anything a playbook derives from a manifest is read out of that manifest at run time
rather than passed in as a variable.

## Consequences

- `cluster/ansible/` is no longer only node provisioning. ADR-0002's reasoning for
  leaving it under `cluster/` is unchanged; its description of the contents is now
  narrower than the directory.
- These playbooks get monkeyble scenarios like any other, so the control flow is tested
  without a cluster. They are not idempotent state convergence, so molecule does not fit.
- Operations that read a manifest must run from a checkout of the branch carrying it,
  which couples the run to git state. That is deliberate: it is what stops the operator
  and the manifest from disagreeing.
- A bash script would have been shorter. It would also have needed its own argument
  parsing, kubectl error handling and test harness, all of which already exist here.
