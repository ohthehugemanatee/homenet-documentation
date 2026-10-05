# ADR-0008: Volume restore points use the CSI snapshot API, not Velero

- **Status:** accepted
- **Date:** 2026-09-30

## Context

#206 planned Velero as the backup/restore control plane for app upgrades, which
needs an S3 store for its `BackupStorageLocation`. MinIO's community edition was
archived in early 2026, OpenMediaVault's S3 plugin wraps MinIO, and Garage would
be a new stateful service on shoebox. The pipeline needs an on-demand restore
point with a status to poll and a declarative way back, and Longhorn's CSI
driver already provides all three through `VolumeSnapshot`.

## Decision

The cluster serves `snapshot.storage.k8s.io` from upstream external-snapshotter's
`snapshot-controller`, deployed by ArgoCD from `cluster/operators/snapshot-controller/`.
No Velero and no object store.

The controller runs the external-snapshotter release matching the `csi-snapshotter`
sidecar the pinned Longhorn chart ships, and moves only with a Longhorn chart bump.

## Consequences

A Longhorn bump that changes the sidecar must bump the controller in the same PR;
`check_snapshotter_pin.py` fails CI otherwise.

Scheduled snapshots and backups stay with Longhorn's `RecurringJob`s. Nothing prunes
a snapshot the upgrade pipeline creates, so the pipeline deletes its own (#220).

There is no cluster-object backup or recovery into a fresh cluster. Manifests live
in git, so none is needed today.
