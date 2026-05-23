# Ansible Scheduler — Architecture & Operations

Scheduled Ansible automation for the homenet k3s cluster, with alerting on failure.

---

## Architecture

```
shoebox (external, always-on NFS server)
├── Semaphore (Docker)          ← web UI, manual triggers, run history
├── ansible-node-state.timer   ← weekly node-state run; Pushover on failure
├── kubectl + kubeconfigs       ← for rolling-upgrade.yaml delegate_to tasks
├── /var/log/ansible/           ← playbook logs, logrotated weekly (12 weeks)
└── /var/lib/ansible-upgrade/  ← run state files (failure flag, maintenance flag)

In-cluster (Loki stack)
└── Alertmanager → Pushover    ← k8s node health, pod crashloops, OOMKills
```

### Why shoebox, not in-cluster

`rolling-upgrade.yaml` uses `delegate_to: localhost` for all kubectl calls. An
in-cluster pod would need kubectl + kubeconfig + RBAC replicated inside the
container. More critically, Semaphore cannot safely orchestrate its own cluster's
upgrades: the API server goes offline during the first-master play, Semaphore dies,
and the drained node can never be uncordoned. Shoebox is always on, external to
the cluster, and immune to this observer paradox.

### Alerting layers

| What | How | Survives cluster down? |
|---|---|---|
| Ansible playbook failure | Shell wrapper / rescue block → Pushover | Yes (runs on shoebox) |
| k8s node health, pod events | Alertmanager → Pushover | No — dies with cluster |

A total cluster blackout is naturally observable (Nextcloud, Plex go offline). An
external watchdog (RPi Zero script) can be added later without changing this design.

---

## Scheduled jobs

### node-state.yaml — weekly systemd timer

Enforces idempotent node state (packages, kernel config, sysctl, NTP, iSCSI, k3s
service health). No kubectl. Targets `all:!ubuntu`.

Timer: `ansible-node-state.timer` fires Sunday 02:00, with 10-minute random jitter.
If shoebox was off, runs within 1 hour of next boot (`Persistent=true`).

Failure → Pushover WARNING via `/usr/local/bin/run-node-state.sh`.
Log: `/var/log/ansible/node-state-YYYYMMDD-HHMMSS.log`

### rolling-upgrade.yaml — manual via Semaphore

Run order: agents → multimasters → masters. Always pass `-e strict_mode=true` for
scheduled or Semaphore runs. Semaphore command:

```
ansible-playbook -i inventory.yaml \
  --vault-password-file /etc/ansible/vault-password \
  -e vault_file=group_vars/vault.yaml \
  -e strict_mode=true \
  rolling-upgrade.yaml 2>&1 | tee /var/log/ansible/rolling-upgrade-$(date +%Y%m%d).log
```

---

## Pre-flight checklist (BEFORE every rolling-upgrade run)

Strict-local StatefulSets block drain — scale them down first:

```bash
kubectl scale statefulset plex --replicas=0
kubectl scale statefulset nextcloud --replicas=0
```

Scale back up after each node is verified Ready:

```bash
kubectl scale statefulset plex --replicas=1
kubectl scale statefulset nextcloud --replicas=1
```

**Verify cluster health before starting:**

```bash
kubectl get nodes           # all Ready
kubectl get pods -A | grep -v Running | grep -v Completed   # no stuck pods
```

---

## kubeconfig setup

Two kubeconfigs are required on shoebox:

| Path | Endpoint | Used by |
|---|---|---|
| `/home/ansible/.kube/config` | `https://10.10.10.10:6443` | agents + multimasters plays |
| `/etc/ansible/kubeconfig-cluster3` | `https://<cluster3-IP>:6443` | masters play |

The masters play sets `environment: KUBECONFIG: /etc/ansible/kubeconfig-cluster3`
at play level. When cluster1 is drained and rebooting, kubectl reaches the cluster
via cluster3's API server instead. The primary kubeconfig is never mutated.

Both files must be group-readable by gid 1001 (Semaphore container):

```bash
chown ansible:1001 /home/ansible/.kube/config /etc/ansible/kubeconfig-cluster3
chmod 640 /home/ansible/.kube/config /etc/ansible/kubeconfig-cluster3
```

---

## State files on shoebox

| Path | Purpose | Lifecycle |
|---|---|---|
| `/var/lib/ansible-upgrade/maintenance-in-progress` | Set at play start; read by external monitors | Cleared by cleanup play (or Semaphore service restart) |
| `/var/lib/ansible-upgrade/rolling-upgrade-failed` | Set on any node failure | Cleared at next run's start (agents pre_task), or manually |

Both paths are bind-mounted into the Semaphore container so `delegate_to: localhost`
tasks inside the container write to the host filesystem.

---

## Failure handling

### Pre-upgrade package snapshot

Before each node upgrade, `rolling-upgrade.yaml` records installed package versions
to `/var/lib/ansible-upgrade/pre-upgrade.txt` **on the node**. This file is forensic
only — it tells you what changed after a failure, but no automated rollback reads it.
Package-level apt downgrade is not the recovery path (see agent rescue below).

### Agent nodes

On any task failure after drain, the rescue block:
1. Sets `/var/lib/ansible-upgrade/rolling-upgrade-failed`
2. Uninstalls k3s agent and reinstalls from scratch
3. Waits for the node to rejoin the cluster
4. Uncordons automatically and clears the failure flag
5. Sends Pushover **WARNING** — rebuilt successfully

If rebuild also fails:
- Sends Pushover **CRITICAL** (priority 2, repeat every 5 min for 1 hour)
- Node stays drained
- Failure flag stays set — multimasters play aborts

### Control-plane nodes (multimasters + masters)

No auto-rebuild. Etcd state makes master reinstall non-trivial. On failure:
- Sends Pushover **CRITICAL**
- Node stays drained
- Failure flag set — subsequent plays abort

Manual recovery required.

---

## Recovery after failure

```bash
# 1. Investigate the drained node
ssh <node>
journalctl -u k3s[-agent] -n 100
systemctl status k3s[-agent]

# 2. Fix the underlying issue manually

# 3. Uncordon (only after verifying node health)
kubectl uncordon <node>

# 4. Clear the failure flag on shoebox (not inside Semaphore container)
rm /var/lib/ansible-upgrade/rolling-upgrade-failed

# 5. Scale StatefulSets back up if needed
kubectl scale statefulset plex --replicas=1
kubectl scale statefulset nextcloud --replicas=1

# 6. Re-run from Semaphore targeting the remaining nodes
#    (e.g. --limit multimasters if agents completed successfully)
```

---

## Playbook variables

### node-state.yaml

| Variable | Required | Default | Description |
|---|---|---|---|
| `target` | No | `all:!ubuntu` | Host pattern override (`-e target=masters`) |
| `ntp_servers` | No | `[ntp.ubuntu.com, 0.pool.ntp.org, 1.pool.ntp.org]` | NTP server list |
| `cluster_role` | No | `agent` | `agent` or `server` — controls which k3s service unit is checked |

`node-state.yaml` loads no vault variables and requires no `vault_file`.

### rolling-upgrade.yaml

| Variable | Required | Default | Description |
|---|---|---|---|
| `vault_file` | **Yes** | — | Path to vault secrets file, e.g. `group_vars/vault.yaml` |
| `strict_mode` | No | `false` | `true` stops the run on the first node failure; use for all scheduled/Semaphore runs |
| `target` | No | play-specific | Overrides the hosts pattern for all three plays simultaneously |
| `state_dir` | No | `/var/lib/ansible-upgrade` | Controller-side directory for run-state files; override to a temp dir for local test runs |

Vault secrets consumed from `vault_file`: `k3s_token`, `k3s_api_server_url`, `pushover_app_token`, `pushover_user_key`.

### shoebox/shoebox-ansible-setup.yaml

One-time bootstrap, run from the operator's workstation.

| Variable | Required | Source | Description |
|---|---|---|---|
| `vault_password` | **Yes** | Prompted at run time | The Ansible vault password itself — written to `/etc/ansible/vault-password` on shoebox. Cannot live in the vault (chicken-and-egg). The playbook prompts for it via `vars_prompt` |
| `pushover_app_token` | **Yes** | vault | Pushover application token |
| `pushover_user_key` | **Yes** | vault | Pushover user key |
| `semaphore_admin_password` | **Yes** | vault | Semaphore admin login password |
| `semaphore_access_key_encryption` | **Yes** | vault | 32-character random string for Semaphore secret-at-rest encryption |

All five must be set up before running the playbook. Add the four vault entries to `cluster/ansible/group_vars/vault.yaml` (encrypt with `ansible-vault encrypt`); the `vault_password` is supplied interactively each run.

---

## Testing

### Lint (automated, every push)

`.github/workflows/lint.yaml` runs `ansible-lint` + `--syntax-check`
on all playbooks on every push to `cluster/ansible/` or `shoebox/`.

### Integration test protocol

Before merging any change to `rolling-upgrade.yaml`:

```bash
ansible-playbook -i cluster/ansible/inventory.yaml \
  --vault-password-file /etc/ansible/vault-password \
  -e vault_file=cluster/ansible/group_vars/vault.yaml \
  --limit nuc2 \
  -e strict_mode=true \
  cluster/ansible/rolling-upgrade.yaml
```

nuc2 is the canary node: amd64 agent, standard `ansible_user`, no pinned workloads.

**Verify:**
- Node is cordoned before drain appears in Semaphore output
- Pre-upgrade package snapshot at `/var/lib/ansible-upgrade/pre-upgrade.txt` on nuc2
- Node uncordoned and Ready after upgrade
- Restart loop check passes (NRestarts ≤ 3)
- Cleanup play clears `/var/lib/ansible-upgrade/maintenance-in-progress`

**Test rescue path** (break the health check intentionally):

```bash
# Temporarily lower the NRestarts threshold to force failure:
# In rolling-upgrade.yaml, change `failed_when: post_restarts.stdout | int > 3`
# to `failed_when: post_restarts.stdout | int >= 0`
# Then run --limit nuc2 and verify:
# - Rescue block fires, k3s reinstalls, node rejoins
# - Pushover WARNING received
# - Failure flag cleared
# - Revert the threshold change
```

---

## Semaphore setup

After `shoebox/shoebox-ansible-setup.yaml` runs:

1. SSH-tunnel to shoebox: `ssh -L 3000:localhost:3000 shoebox`
2. Open `http://localhost:3000`
3. **Key Store**: add Ansible Vault password as "LoginPassword" key named `vault`
4. **Repository**: point to `/repo` (bind-mounted from `/home/user/homenet-documentation`)
5. **Inventory**: `/repo/cluster/ansible/inventory.yaml`
6. **Environment**: set `KUBECONFIG=/home/semaphore/.kube/config`
7. **Task templates**:
   - node-state: `ansible-playbook -i inventory.yaml --vault-password-file /etc/ansible/vault-password node-state.yaml`
   - rolling-upgrade: `ansible-playbook -i inventory.yaml --vault-password-file /etc/ansible/vault-password -e vault_file=group_vars/vault.yaml -e strict_mode=true rolling-upgrade.yaml`

---

## Alertmanager → Pushover

Configured in `cluster/helm/loki/values.yaml` under `prometheus.alertmanagerFiles`.

**Replace placeholder credentials** before applying:

```bash
# Decrypt values.yaml, replace CHANGEME_ tokens, re-encrypt or template with vault
# Then apply:
helm upgrade -n loki loki grafana/loki-stack -f cluster/helm/loki/values.yaml
```

Covers: NodeNotReady, pod OOMKill, CrashLoopBackOff, PVC near full, and any future
PrometheusRule alerts.

Note: Alertmanager lives in-cluster and cannot alert if the entire cluster is down.
