# ADR-0003: ArgoCD owns ongoing state; `install.sh` is bootstrap only

- **Status:** accepted
- **Date:** 2026-08-22

## Context

The `install.sh` / `install-*.sh` scripts in `cluster/helm/` and `cluster/longhorn/`
were the original deployment path: each did secret creation plus a `helm upgrade` or
`kubectl apply`. Adopting ArgoCD gave those workloads a declarative owner, leaving two
mechanisms able to write the same resources.

## Decision

ArgoCD owns the deployed state of everything with an Application manifest. The
scripts' secret-creation portions stay — secrets are not in git, so something has to
create them before the first sync — and their `helm upgrade` / `kubectl apply`
portions are not used for ongoing management. The scripts are kept rather than split
because bootstrap is the only time they run.

## Consequences

- Running an `install.sh` against a live cluster fights ArgoCD's self-heal. The
  scripts are a bootstrap tool, and `argocd.md` says so in present tense.
- A workload brought under ArgoCD after being installed by hand does not need its
  history recorded; its sync policy is chosen by the tier rules in
  `cluster/argocd/CLAUDE.md`, not by how it was first installed.
