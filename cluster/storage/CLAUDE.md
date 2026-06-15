# cluster/storage/CLAUDE.md — PV and PVC manifests

K8s verification (kubeconform etc.) lives in `cluster/CLAUDE.md`.

## Conventions

- File names match resource names: `pv-<workload>.yaml`, `pvc-<workload>.yaml`. One workload per file.
- `StorageClass` choice:
  - **Longhorn** (variants in `cluster/StorageClass/`) for cluster-internal replicated storage.
  - **`nfs-subdir-external-provisioner`** for shared host-mounted volumes (warehouse, shoebox).
- `persistentVolumeReclaimPolicy: Retain` for data PVs by default. `Delete` only for ephemeral/throwaway.
- PVCs reference their PV by name, not by selector, to keep binding deterministic.
