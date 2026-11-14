# ADR-0012: Builds we publish run from a mutable `devel` tag

- **Status:** accepted
- **Date:** 2026-11-14

## Context

`songhub` (built from ohthehugemanatee/SongHub) and `remarkable-sync` (built from
this repo) change faster than a manifest PR can follow. Their pinned tags never moved
when a build landed, and with no `imagePullPolicy` a node kept its cached copy, so a
merged change reached the cluster only through a manifest edit.

## Decision

A merge to the default branch that triggers a build we publish pushes a mutable
`:devel` tag and an immutable `:sha-<commit>` to GHCR. Manifests run `:devel` with
`imagePullPolicy: Always`, and a deploy is deleting the pod. Every such build uses
the name `devel`, so a fork's default branch name never appears in a manifest. A
rollback pins a `sha-` tag in the manifest. Images we do not build are unaffected.

## Consequences

ArgoCD shows Synced while the image changes, because the manifest does not name
the build.

A deploy by deleting the pod is not a sync, so ADR-0009's hooks do not run. An app
that adopts them is deployed by a manifest change instead.

Any pod start, including a node drain or a k3s upgrade, pulls what `:devel` points
at. A start during a GHCR or WAN outage ends in `ErrImagePull`, because `Always` has
no cache fallback.

`git revert` does not undo a build. A rollback is a manifest PR that pins a `sha-`
tag.
