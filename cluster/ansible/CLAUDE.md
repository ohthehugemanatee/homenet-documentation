# cluster/ansible/CLAUDE.md — node provisioning + rolling upgrades

Playbooks here provision the k3s nodes' OS (apt, sysctl, k3s service, NTP, iSCSI). They run from `shoebox/` via Semaphore — never in-cluster. See `monitoring-and-compliance.md` for the runner architecture.

## Playbook contracts

- **`node-state.yaml`** — fully idempotent; converges packages, kernel modules, sysctl, NTP, iSCSI, swap and journald, and hardens the low-RAM (4 GB Pi) control-plane nodes with kubelet memory reservations and a soft `MemoryHigh` drop-in on `k3s.service`. Safe to re-run. Two opt-in flags change what it does: `node_state_zram_enabled` (zram swap cushion; also skips the blanket `swapoff`) and `node_state_usb_offload_enabled` (auto-derived from `cluster_role`), which symlinks the k3s, Longhorn, kubelet and pod-log directories onto `/mnt/usb`. The offload only manages symlink state when `/mnt/usb` is mounted and the path is absent or already a symlink — it never clobbers a populated dir, so the live data move (stop k3s, rsync) stays manual.
- **`rolling-upgrade.yaml`** — two-phase: a first play runs `upgrade_check` against every targeted node in parallel (default forks, no `serial`) and sets `upgrade_check_needed` as a fact; the three rollout plays (unchanged targeting, still `serial: 1`) reuse that fact — set once per host, it persists across plays for the same run — to skip a node's cordon/drain/apt-upgrade/node_state/k3s_health block without recomputing the check. Rollout is `apt dist-upgrade` + reboot + health check + uncordon; agents → multimasters → masters (first-master last); rescue path on health failure. The agent rebuild only fires once `k3s_health` has started, so a failure before it alerts and leaves k3s running rather than reinstalling a node that was never broken. The parallel check play runs ahead of `upgrade_checks_cp`'s abort-on-prior-failure guard, so a stale failure flag under `strict_mode` still lets the (non-destructive) check run against every node before the rollout plays abort.
- **`rolling-release-upgrade.yaml`** — same two-phase shape as `rolling-upgrade.yaml`, Ubuntu major-version `do-release-upgrade`. Its check play sets `upgrade_check_release: true` so `upgrade_check` also runs `do-release-upgrade -c`; a node with no pending packages, no pending reboot, and no new release available is skipped the same way.
- **`k3s-agent.yaml`** — legacy one-time bootstrap for a fresh node; **NOT idempotent**. Requires `--ask-become-pass --ask-vault-pass` and `k3s_token` / `usb_disk` / `cluster_role` vars. Mounts the USB disk, then delegates to `node_state` for OS convergence (including USB offload symlinks).
- **`migrate-config-to-longhorn.yaml`** — moves one app's `/config` from the `app-configs` NFS PVC onto a Longhorn volume (#241). Operates on cluster workloads, not node OS (ADR-0005); requires a phase tag (`-t stage` before the manifest PR merges, `-t resume` after, `-t rollback` after a revert) and `-e app=<name>`. An app whose pod seeds several directories on one volume passes `migrate_sources` and `migrate_scale_targets` (README has calibre's invocation); the default is one source and one Deployment. Preflight derives the target PVC name from the app's `volumeClaimTemplate` in `cluster/services/<app>.yaml` and refuses to run against an unconverted manifest, so it must run from a checkout of the converting branch.
- **`rename-node.yaml`**, **`showfacts.yaml`** — utility, obvious from name.

## Roles (`roles/`)

Roles compose into the rolling playbooks — **do not duplicate role logic inline** in a playbook. `ls roles/` for the current set.

### Longhorn rebuild gate

A node holding the last healthy replica of an attached volume sticks on PodDisruptionBudget too, and in a `serial: 1` rollout that's normal state after the previous node rebooted.

`cordon_drain` waits before it cordons. It lists the Longhorn `Replica` CRs whose `spec.nodeID` is the target node, then polls those volumes until none is both `attached` and not `healthy`, bounded by `cordon_drain_longhorn_wait` (900s, re-checked every `cordon_drain_longhorn_poll`). Past the bound it fails with the volume names, ahead of the cordon so the node stays schedulable. A node with no Longhorn replicas skips the wait. Toggle with `cordon_drain_wait_for_longhorn`.

`cordon_drain` sets `cordon_drain_cordoned` once the cordon lands, and `upgrade_rescue_agent`'s CRITICAL alert reads it to report whether the node needs uncordoning.

### Longhorn snapshot attachment gate

Longhorn snapshot work can keep a volume attached after its workload stops. A
`snapshot-controller-*` ticket assigned to the target node keeps the volume
engine running, so Longhorn retains the instance-manager PodDisruptionBudget.

Before cordoning, `cordon_drain` lists Longhorn `VolumeAttachment` and `Snapshot`
CRs. It removes a snapshot-controller ticket only when the referenced Snapshot
CR no longer exists, then waits for every ticket assigned to the target node to
clear. The wait is bounded by `cordon_drain_snapshot_wait` (300s, re-checked
every `cordon_drain_snapshot_poll`). A timeout fails before the cordon and names
the volume and ticket. Toggle with `cordon_drain_wait_for_snapshot_tickets`.

### Longhorn single-replica drain guard

Single-replica Longhorn volumes block `kubectl drain`: the `longhorn-ephemeral` / `longhorn-ephemeral-fast` StorageClasses set `numberOfReplicas: "1"` (`strict-local`), so a node holding such an *attached* volume times out trying to meet PodDisruptionBudget (cluster `node-drain-policy: allow-if-replica-is-stopped`).

`cordon_drain` handles this: it scales to 0 any StatefulSet whose pod **on the target node** mounts a single-replica Longhorn PVC, recording original replica count in `homenet.vertesi.com/pre-drain-{replicas,node}` annotations. When the StatefulSet has a controlling owner (e.g. kube-prometheus-stack alertmanager) the count read/write address that owner instead (but annotations stay on the StatefulSet either way). This means using `kubernetes.core.k8s` rather than `k8s_scale`, whose strategic-merge patch of the scale subresource fails with a 415 error on custom resources. `k3s_health` (happy path) and `upgrade_rescue_agent` (after a successful rebuild) call `cordon_drain`'s `restore` task to scale them back and clear the annotations. Discovery is dynamic (no hardcoded workload names) but **StatefulSet-only**. Toggle with `cordon_drain_scale_down_single_replica`. The long-term fix is moving pure-scratch volumes off Longhorn to `emptyDir` like plex transcode did in #277.

## State, failure flag, alerts

- All upgrade plays read/write state under `/var/lib/ansible-upgrade/` on the shoebox host (not in repo).
- A persistent failure flag (`rolling-upgrade-failed`) **aborts subsequent plays** in the same run — agents-fail blocks multimasters-then-masters. Clearing the flag is the rescue path's job; never clear it silently.
- **Pushover alerts:** `WARNING` when an auto-rebuild succeeded; `CRITICAL` for unrecovered failures (CP failure, agent rebuild failed, agent failure before `k3s_health` ran). New rescue paths follow this severity contract.
- **kubectl from playbooks:** `delegate_to: localhost` with `$KUBECONFIG` set to shoebox's kubeconfig. Never run kubectl on the target node.

## Tests (`tests/` + `molecule/`)

- `tests/monkeyble/` — `hpe.monkeyble` mocks of kubectl/apt/systemctl. `run-tests.sh` is the scenario registry; a new scenario is registered there. It runs `cross_play_abort` with the monkeyble callback disabled, because that scenario tests Ansible flow rather than task assertions.
- `molecule/default/` — Docker (`ubuntu2204-ansible`) converge + idempotence + verify of `node_state`. Uses `--skip-tags molecule-notest` to skip x86 media + multipath removal.
- `tests/test-collections-requirements.sh` — asserts the Galaxy pins CI and Semaphore install from stay in agreement.

**Test-first contract for Ansible changes:** any change touching a role MUST add or update either a monkeyble scenario (control flow / assertions) or a molecule verify step (converged state). Re-run both before commit.

## Verification — run before commit

```sh
ansible-lint cluster/ansible
bash cluster/ansible/tests/test-collections-requirements.sh
bash cluster/ansible/tests/monkeyble/run-tests.sh
cd cluster/ansible && molecule test
```

If existing scenarios don't cover your change, add one — per the root rule on extending the test frameworks. Prefer a Galaxy collection from `requirements.yaml` over hand-rolled `command:` / `shell:`.

## Galaxy collections

`requirements.yaml` is the single source of truth for collection pins. `collections/requirements.yml` is a symlink to it on the path Semaphore searches (`<playbook_dir>/collections/requirements.yml`), so the scheduled runs install the same pins CI does rather than the collections bundled in the Semaphore image. Deleting the symlink silently falls back to those bundled versions.
