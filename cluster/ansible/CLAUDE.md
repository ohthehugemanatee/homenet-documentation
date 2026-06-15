# cluster/ansible/CLAUDE.md — node provisioning + rolling upgrades

Playbooks here provision the k3s nodes' OS (apt, sysctl, k3s service, NTP, iSCSI). They run from `shoebox/` via Semaphore — never in-cluster. See `@ansible-scheduler.md` for the runner architecture.

## Playbook contracts

- **`node-state.yaml`** — fully idempotent; converges packages, kernel modules, sysctl, NTP, iSCSI, swap, journald. Safe to re-run.
- **`rolling-upgrade.yaml`** — `apt dist-upgrade` + reboot + health check + uncordon; `serial: 1`; agents → multimasters → masters (first-master last); rescue path on health failure.
- **`rolling-release-upgrade.yaml`** — Ubuntu major-version `do-release-upgrade`; same serial/rescue pattern as `rolling-upgrade.yaml`.
- **`k3s-agent.yaml`** — legacy one-time bootstrap for a fresh node; **NOT idempotent**. Requires `--ask-become-pass --ask-vault-pass` and `new_hostname` / `k3s_token` / `usb_disk` / `cluster_role` vars.
- **`rename-node.yaml`**, **`showfacts.yaml`** — utility, obvious from name.

## Roles (`roles/`)

`apt_upgrade`, `cordon_drain`, `k3s_health`, `node_state`, `release_upgrade`, `upgrade_checks_cp`, `upgrade_pre_state`, `upgrade_rescue_agent`, `upgrade_rescue_cp`. Roles compose into the rolling playbooks — **do not duplicate role logic inline** in a playbook.

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
