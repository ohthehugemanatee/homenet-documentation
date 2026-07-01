# cluster/ansible/CLAUDE.md — node provisioning + rolling upgrades

Playbooks here provision the k3s nodes' OS (apt, sysctl, k3s service, NTP, iSCSI). They run from `shoebox/` via Semaphore — never in-cluster. See `@ansible-scheduler.md` for the runner architecture.

## Playbook contracts

- **`node-state.yaml`** — fully idempotent; converges packages, kernel modules, sysctl, NTP, iSCSI, swap, journald. Safe to re-run. On control-plane nodes it also hardens the low-RAM (4 GB Pi) masters: kubelet memory `system-reserved`/`kube-reserved`/`eviction-hard` (in the server `config.yaml`), a soft `MemoryHigh` systemd drop-in on `k3s.service`, an opt-in `zram` swap cushion (`node_state_zram_enabled`, adds kubelet `fail-swap-on=false` and skips the blanket `swapoff`), and USB offload (`node_state_usb_offload_enabled`, auto-derived from `cluster_role`) that symlinks `/var/lib/rancher/k3s`, `/var/lib/rancher/longhorn`, `/var/lib/kubelet`, and `/var/log/pods` onto `/mnt/usb`. The offload only manages symlink state when `/mnt/usb` is mounted and the path is absent/already a symlink — it never clobbers a populated dir, so the live data move (stop k3s, rsync) is still manual.
- **`rolling-upgrade.yaml`** — `apt dist-upgrade` + reboot + health check + uncordon; `serial: 1`; agents → multimasters → masters (first-master last); rescue path on health failure.
- **`rolling-release-upgrade.yaml`** — Ubuntu major-version `do-release-upgrade`; same serial/rescue pattern as `rolling-upgrade.yaml`.
- **`k3s-agent.yaml`** — legacy one-time bootstrap for a fresh node; **NOT idempotent**. Requires `--ask-become-pass --ask-vault-pass` and `k3s_token` / `usb_disk` / `cluster_role` vars. Mounts the USB disk, then delegates to `node_state` for OS convergence (including USB offload symlinks).
- **`rename-node.yaml`**, **`showfacts.yaml`** — utility, obvious from name.

## Roles (`roles/`)

`apt_upgrade`, `cordon_drain`, `k3s_health`, `node_state`, `release_upgrade`, `upgrade_checks_cp`, `upgrade_pre_state`, `upgrade_rescue_agent`, `upgrade_rescue_cp`. Roles compose into the rolling playbooks — **do not duplicate role logic inline** in a playbook.

### Longhorn single-replica drain guard

Single-replica Longhorn volumes block `kubectl drain`: the `longhorn-ephemeral` / `longhorn-ephemeral-fast` StorageClasses set `numberOfReplicas: "1"` (`strict-local`), so a node holding such an *attached* volume can never satisfy Longhorn's per-node `instance-manager` PodDisruptionBudget (cluster `node-drain-policy: allow-if-replica-is-stopped`) — the drain retries evictions until it times out.

`cordon_drain` handles this automatically: after cordon it scales to 0 any StatefulSet whose pod **on the target node** mounts a single-replica Longhorn PVC, recording the original replica count in `homenet.vertesi.com/pre-drain-{replicas,node}` annotations. `k3s_health` (happy path) and `upgrade_rescue_agent` (after a successful rebuild) call `cordon_drain`'s `restore` task to scale them back and clear the annotations. Discovery is dynamic (no hardcoded workload names) but **StatefulSet-only** — Deployments backed by single-replica volumes are out of scope. Toggle with `cordon_drain_scale_down_single_replica`. The cleaner long-term fix is moving pure-scratch volumes (e.g. plex transcode) off Longhorn to `emptyDir`.

## State, failure flag, alerts

- All upgrade plays read/write state under `/var/lib/ansible-upgrade/` on the shoebox host (not in repo).
- A persistent failure flag (`rolling-upgrade-failed`) **aborts subsequent plays** in the same run — agents-fail blocks multimasters-then-masters. Clearing the flag is the rescue path's job; never clear it silently.
- **Pushover alerts:** `WARNING` when an auto-rebuild succeeded; `CRITICAL` for unrecovered failures (CP failure, agent rebuild failed). New rescue paths follow this severity contract.
- **kubectl from playbooks:** `delegate_to: localhost` with `$KUBECONFIG` set to shoebox's kubeconfig. Never run kubectl on the target node.

## Tests (`tests/` + `molecule/`)

- `tests/monkeyble/` — `hpe.monkeyble` mocks of kubectl/apt/systemctl. Scenarios: `test_agent_rescue_success.yml`, `test_agent_rescue_failure.yml`, plus `cross_play_abort` orchestrated by `run-tests.sh` (which disables monkeyble for that scenario — tests Ansible flow, not assertions).
- `molecule/default/` — Docker (`ubuntu2204-ansible`) converge + idempotence + verify of `node_state`. Uses `--skip-tags molecule-notest` to skip x86 media + multipath removal.

**Test-first contract for Ansible changes:** any change touching a role MUST add or update either a monkeyble scenario (control flow / assertions) or a molecule verify step (converged state). Re-run both before commit.

## Verification — run before commit

```sh
ansible-lint cluster/ansible
bash cluster/ansible/tests/monkeyble/run-tests.sh
cd cluster/ansible && molecule test
```

If existing scenarios don't cover your change, add one — per the root "CI/test coverage may need expansion" rule. Collections (`requirements.yaml`) currently include `ansible.posix` + `hpe.monkeyble`; prefer Galaxy collections over hand-rolled `command:` / `shell:`.
