# Ansible playbooks for my k3s cluster

## Playbooks

| Playbook | Purpose | Re-runnable? |
|---|---|---|
| `k3s-agent.yaml` | Initial node provisioning — hostname, k3s install | No (imperative) |
| `node-state.yaml` | Idempotent state enforcement — packages, config, services | Yes |
| `rolling-upgrade.yaml` | Rolling OS dist-upgrade with drain/uncordon | Yes |
| `migrate-config-to-longhorn.yaml` | Move one app's `/config` from the `app-configs` NFS PVC onto Longhorn | Yes (per phase) |

Note that to keep CI happy, the encrypted vault file is not loaded by default.
`k3s-agent.yaml` and `rolling-upgrade.yaml` load it via
`vars_files: ["{{ vault_file }}"]`, so real-world runs need
`-e vault_file=group_vars/vault.yaml` (path passed as a variable, not
appended with `@`). The path is resolved relative to the **playbook's directory**
(`cluster/ansible/`), not the working directory — so `group_vars/vault.yaml`
works regardless of where you invoke `ansible-playbook` from.
`node-state.yaml` consumes no vault variables and doesn't need this flag.

---

## `k3s-agent.yaml` — Initial setup

Sets hostname, installs dependencies, runs the k3s installer. Run once per new node.

```sh
# New ubuntu node → agent called cluster2, USB disk attached
ansible-playbook -i inventory.yaml -e usb_disk='/dev/sda1' --ask-vault-pass --ask-become-pass k3s-agent.yaml --limit cluster2,ubuntu

# Specify all vars explicitly
ansible-playbook -i inventory.yaml \
  -e new_hostname=cluster2 -e ansible_user=ubuntu \
  -e k3s_token="${K3S_TOKEN}" -e usb_disk='/dev/sda1' \
  -e cluster_role="agent" \
  --ask-become-pass --ask-vault-pass k3s-agent.yaml
```

**Notes:**
- Target both the OOTB hostname (`ubuntu`) and the final hostname. The playbook renames and reboots before applying config.
- `--ask-become-pass` is required for sudo access.

---

## `node-state.yaml` — Idempotent state management

Converges each node to declared state: packages, `/etc/hosts`, sysctl, NTP, unattended-upgrades, swap-off, journald, multipath. Safe to re-run at any time.

```sh
# Validate/repair cluster1 (first use case)
ansible-playbook -i inventory.yaml --ask-vault-pass --limit cluster1 node-state.yaml

# Dry-run with diff — see what would change
ansible-playbook -i inventory.yaml --ask-vault-pass --check --diff node-state.yaml

# All nodes
ansible-playbook -i inventory.yaml --ask-vault-pass node-state.yaml

# Override NTP servers
ansible-playbook -i inventory.yaml --ask-vault-pass \
  -e '{"ntp_servers": ["192.168.1.1", "ntp.ubuntu.com"]}' node-state.yaml
```

### What it enforces

| Item | File/Unit |
|---|---|
| Base packages | apt |
| x86 media drivers | apt |
| Hostname | `ansible.builtin.hostname` |
| `/etc/hosts` | `templates/hosts.j2` |
| Kernel modules | `/etc/modules-load.d/k3s.conf` (`br_netfilter`, `overlay`) |
| Kernel parameters | `/etc/sysctl.d/99-k3s.conf` |
| ARM cgroup cmdline | `/boot/firmware/cmdline.txt` |
| NTP | `/etc/systemd/timesyncd.conf` |
| Security updates | `/etc/apt/apt.conf.d/50unattended-upgrades` |
| Swap disabled | `fstab` + `swapoff` |
| Journald volatile | `/etc/systemd/journald.conf` |
| Multipath blacklist | `/etc/multipath.conf` |
| k3s service running | `systemd` |

---

## `rolling-upgrade.yaml` — Rolling OS upgrade

Upgrades one node at a time: drain → `apt dist-upgrade` → reboot → wait → uncordon → verify Ready. Skips reboot if no packages changed and `/var/run/reboot-required` is absent.

Play order: **agents → multimasters → masters** (first-master last, when cluster is most stable).

**Prerequisites:** `kubectl` configured on localhost pointing at the cluster.

```sh
# Upgrade all nodes (rolling, safe order)
ansible-playbook -i inventory.yaml --ask-vault-pass rolling-upgrade.yaml

# Upgrade cluster1 only
ansible-playbook -i inventory.yaml --ask-vault-pass --limit cluster1 rolling-upgrade.yaml

# Agents only
ansible-playbook -i inventory.yaml --ask-vault-pass --limit agents rolling-upgrade.yaml
```

**Notes:**
- `serial: 1` ensures only one node is drained at a time.
- `any_errors_fatal: false` means a failure on one node does not abort the rest — check output carefully.
- For the first-master upgrade, ensure `kubectl` can reach the cluster via a VIP or another server in case the API server on cluster1 is briefly unavailable after reboot.

---

## Variables

| Name | Function | Default |
|---|---|---|
| `new_hostname` | Hostname to set | _(inventory key)_ |
| `ansible_user` | SSH username | `ubuntu` |
| `k3s_token` | k3s join token | _(vault)_ |
| `usb_disk` | USB block device path for storage | _(unset)_ |
| `cluster_role` | `agent`, `multi-master`, or `first-master` | _(inventory group var)_ |
| `ntp_servers` | List of NTP servers | `[ntp.ubuntu.com, 0.pool.ntp.org, 1.pool.ntp.org]` |
| `target` | Override default host pattern | _(playbook default)_ |

---

## Templates

| Template | Destination |
|---|---|
| `templates/hosts.j2` | `/etc/hosts` |
| `templates/sysctl-k3s.conf.j2` | `/etc/sysctl.d/99-k3s.conf` |
| `templates/timesyncd.conf.j2` | `/etc/systemd/timesyncd.conf` |
| `templates/50unattended-upgrades.j2` | `/etc/apt/apt.conf.d/50unattended-upgrades` |

---

## `migrate-config-to-longhorn.yaml` — NFS → Longhorn config cutover

Stages one app's `/config` onto its own Longhorn volume (#241). Runs against the
cluster from the shoebox controller, so it needs a working `KUBECONFIG`, not SSH to a
node. Requires a phase tag — a bare run only does preflight.

```sh
# before merging the manifest PR that converts the app to a StatefulSet
ansible-playbook migrate-config-to-longhorn.yaml -e app=jackett -t stage
```

`stage` saves the app's ArgoCD sync policy under `state_dir`, suspends auto-sync,
scales the Deployment to 0, creates the Longhorn PVC, and copies `/config` into it with
a helper pod. The copy is verified by a sorted `sha256sum` diff over source and
destination inside that pod, so a truncated copy and leftovers from an earlier partial
run both fail the play. The helper pod is deleted either way.

**Run it from a checkout of the branch that converts the app.** Preflight reads
`cluster/services/<app>.yaml` and derives the PVC name from its `volumeClaimTemplate`:
a StatefulSet adopts `<template>-<statefulset>-0` and silently provisions an empty
volume for any other name. Against an unconverted manifest the playbook refuses to run.

Afterwards, merge the manifest PR and restore auto-sync — ArgoCD applies the
StatefulSet, which adopts the staged PVC:

```sh
argocd app set jackett --sync-policy automated --auto-prune --self-heal
```

The NFS directory is left untouched, so reverting the manifest PR is the rollback.
