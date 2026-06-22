# cluster/StorageClass/CLAUDE.md — Longhorn StorageClasses

Custom Longhorn StorageClasses. Foundation (namespace, linters, verification)
lives in `cluster/CLAUDE.md`. Human-facing table of every class + intended use is
in `README.md` here — keep the two in sync.

## Classes defined here

- `longhorn-ephemeral` — 1 replica, `strict-local`, reclaim `Delete`.
- `longhorn-ephemeral-fast` — as above + NVMe `diskSelector`/`nodeSelector`, reclaim `Retain`.
- `longhorn-performance` — 2 replicas, `best-effort`, `WaitForFirstConsumer`.

## "Ephemeral" does NOT mean ephemeral storage

The `longhorn-ephemeral*` classes are **persistent** Longhorn volumes; the name
describes data value (regenerable scratch), not lifecycle. Data survives pod
deletion, scale-to-0, node drain, and reboot:

- Scaling a StatefulSet to 0 only detaches the volume — it never deletes the PVC.
- On scale-up the same pod ordinal re-mounts the same PVC → same volume → same
  data. `reclaimPolicy` only matters on PVC deletion, which never happens here.
- This is fundamentally different from `emptyDir` (wiped on reschedule).

Do not "fix" the misleading name to imply data loss, and do not assume these
volumes can be treated as throwaway in playbooks or workload manifests.

## Drain coupling — single-replica `strict-local` blocks `kubectl drain`

An attached single-replica `strict-local` volume cannot satisfy Longhorn's
`instance-manager` PDB during drain, so the `cordon_drain` role scales owning
StatefulSets to 0 pre-drain and restores them after. See
`cluster/ansible/CLAUDE.md` (“Longhorn single-replica drain guard”). If you add a
new `numberOfReplicas: "1"` + `strict-local` class, the drain guard discovers it
automatically (it keys off the replica count, not the class name) — but verify it
in `cluster/ansible/tests/monkeyble`.

Genuinely worthless scratch (e.g. Plex transcode) should use `emptyDir`, not
these classes, to avoid the drain block at no cost.
