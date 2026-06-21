# StorageClasses

Custom Longhorn StorageClasses for the cluster. The defaults that ship with the
Longhorn / k3s charts (`longhorn`, `longhorn-static`, `local-path`, `nfs-client`)
are not defined here but are listed below for the full picture.

## Repo-managed classes

| Class | Replicas | Locality | Disk | Reclaim | Data on scale-down/drain | Intended use |
| --- | --- | --- | --- | --- | --- | --- |
| `longhorn-ephemeral` | 1 | `strict-local` | any | `Delete` | **Preserved** | Regenerable-but-expensive scratch, co-located with the pod. Consumers: Loki chunks, Prometheus TSDB, Alertmanager state, Plex transcode. |
| `longhorn-ephemeral-fast` | 1 | `strict-local` | NVMe (`diskSelector`/`nodeSelector: nvme`) | `Retain` | **Preserved** | Same as `-ephemeral` but needs NVMe throughput. Consumer: `nextcloud-previews`. |
| `longhorn-performance` | 2 | `best-effort` | any | `Delete` | **Preserved** | Durable data wanting replication plus read locality. `WaitForFirstConsumer`. Currently unused. |

## Cluster defaults (not defined in this directory)

| Class | Replicas | Provisioner | Intended use |
| --- | --- | --- | --- |
| `longhorn` (default) | 3 | Longhorn | General durable data. Consumers: Grafana, unifi-db. |
| `longhorn-static` | 3 | Longhorn | Pre-provisioned durable volumes for stateful app data: `nextcloud-www`, Plex/Radarr/Sonarr/Duplicacy DBs. |
| `local-path` | — | k3s `local-path` | Node-local, unreplicated, fastest. MariaDB data dirs. |
| `nfs-client` | — | nfs-subdir-provisioner | Volumes backed by shoebox NFS. |

## "Ephemeral" is a misleading name — read this

The `longhorn-ephemeral*` classes are **fully persistent Longhorn volumes**, not
Kubernetes ephemeral storage. "Ephemeral" describes the *value* of the data
(regenerable scratch — previews, transcode, TSDB, log chunks, alertmanager
state), **not** its lifecycle.

What this means in practice, including across a node drain/reboot:

- Scaling a StatefulSet to 0 only **detaches** the volume. It never deletes the
  PVC — StatefulSets deliberately retain PVCs across scale-down, pod deletion,
  even StatefulSet deletion.
- The single replica's data stays on the node's disk. The PVC stays `Bound` to
  the same PV the whole time.
- When the workload scales back up, the same pod ordinal re-mounts the **same
  PVC → same Longhorn volume → same data**. With `strict-local` the pod
  reschedules onto the node where its replica lives and reattaches it.
- `reclaimPolicy` (`Delete`/`Retain`) is irrelevant to this flow — reclaim only
  fires when a **PVC is deleted**, which the maintenance flow never does.

Contrast with `emptyDir`, which is wiped whenever the pod leaves the node — i.e.
on exactly the reschedule a node drain causes. So these classes give you data
that survives node maintenance; `emptyDir` does not.

## Drain coupling — why single-replica `strict-local` blocks `kubectl drain`

A node hosting an **attached** single-replica `strict-local` volume cannot
satisfy Longhorn's per-node `instance-manager` PodDisruptionBudget
(`minAvailable: 1`) under `node-drain-policy: allow-if-replica-is-stopped`:
stopping the only replica would mean data loss, so the PDB keeps
`disruptionsAllowed: 0` and `kubectl drain` retries until timeout.

This is why the `cordon_drain` Ansible role scales the owning StatefulSets to 0
before draining and restores them afterwards — see
`cluster/ansible/CLAUDE.md` (“Longhorn single-replica drain guard”). Because the
data is preserved (above), this is a safe, transparent maintenance step rather
than a data-loss event.

For workloads whose scratch is genuinely worthless between runs (Plex transcode
is the clearest case), prefer a real `emptyDir` instead: it sidesteps the
single-replica drain block entirely and costs nothing to discard.
