# ADR-0011: A failed upgrade stops the app

- **Status:** accepted
- **Date:** 2026-11-09

## Context

ADR-0009's hooks take a restore point before an upgrade but cannot act on a
failed one: a crash-looping StatefulSet never leaves `Progressing`, so ArgoCD
never runs `PostSync` or `SyncFail`. Restoring data while git still names the
new image would rerun the image's migrations against the restored data.

## Decision

A Sync-phase watchdog in the shared hook base waits for the rollout and reruns
the gate's checks. On failure it pauses the Application with the
`argocd.argoproj.io/skip-reconcile` annotation, scales the workload to 0,
restores the claim from the sync's snapshot and fails, which pages through
`KubeJobFailed`. A person reverts the version in git and lifts the pause.

The hooks' ServiceAccount can therefore patch Applications. A
ValidatingAdmissionPolicy limits `<app>-upgrade-hooks` to that annotation on
Application `<app>`.

## Consequences

A failed upgrade costs the app its uptime until someone recovers it.

While paused, an Application sends no ArgoCD notifications, so the watchdog's
failed Job is the only page.

An app's hook `namePrefix` must equal its Application name, or the policy
refuses the pause.
