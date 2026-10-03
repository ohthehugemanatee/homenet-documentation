# ADR-0009: App upgrades are bracketed by shared ArgoCD hooks

- **Status:** accepted
- **Date:** 2026-10-03

## Context

#206 makes app upgrades reversible without per-app backup code. Every app runs in
`default` under ArgoCD, and most keep their state on one Longhorn claim, so the
same three steps fit them all: refuse to upgrade an unhealthy app, take a restore
point, and drop that restore point once the upgrade is healthy.

## Decision

`cluster/argocd/hooks/upgrade/` is one kustomize base that an app instantiates
with `namePrefix: <app>-` and parameters only. It runs a PreSync gate, a PreSync
snapshot and a PostSync cleanup.

The snapshot step scales the workload to 0 and waits for the volume to detach
before snapshotting, so the restore point is clean-shutdown consistent without
app-specific quiescing. It costs the app its downtime for the length of the
snapshot.

An app's own data check runs through `kubectl exec` in the app's container,
which puts `pods/exec` in the hook Role. Trivy's KSV-0053 is accepted for that
one file.

## Consequences

The hook Role is namespaced to `default` but not to one app's objects:
kustomize's `namePrefix` does not rewrite `resourceNames`.

ArgoCD never reaches `PostSync` or `SyncFail` for a StatefulSet that crash-loops,
so a failed upgrade leaves its snapshot recorded in `<workload>-upgrade-state`
and recovery belongs to a watchdog in the sync phase (#428).
