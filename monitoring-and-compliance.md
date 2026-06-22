# Monitoring and Compliance - Architecture & Operations

Loki/Prometheus/Grafana monitoring and scheduled Ansible automation for the homenet k3s cluster, with pushover alerting on failure.

---

## Architecture

```
shoebox (external, always-on NFS server)
├── Semaphore (Docker)          ← schedules + runs both playbooks; alerts on failure
├── kubectl + kubeconfigs       ← for rolling-upgrade.yaml delegate_to tasks
├── /var/log/ansible/           ← playbook logs, logrotated weekly (12 weeks)
└── /var/lib/ansible-upgrade/  ← run state files (failure flag, maintenance flag)

In-cluster (observability + GitOps)
├── ArgoCD            ← GitOps: reconciles cluster state against git repo
│                        drift alerts → Pushover (independent of Alertmanager)
│                        UI at argocd.vert (mobile-friendly)
├── Prometheus        ← scrapes metrics from nodes + pods (15d retention)
├── Alertmanager      ← fires on PrometheusRules → Pushover
├── Grafana           ← dashboards for metrics (Prometheus) + logs (Loki)
├── Loki              ← log aggregation (monolithic, 7d retention)
├── Alloy (DaemonSet) ← collects pod stdout/stderr → Loki
├── Promtail sidecars ← collects file-based logs from specific pods → Loki
└── event-exporter   ← ships k8s Events → Loki (powers workload-debug dashboard)
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

### node-state.yaml — Semaphore weekly schedule

Enforces idempotent node state (packages, kernel config, sysctl, NTP, iSCSI, k3s
service health). No kubectl. Targets `all:!ubuntu`.

Scheduled as a Semaphore task template with a cron expression (e.g. weekly
`0 2 * * 0` for Sunday 02:00). Semaphore handles execution, run history, and
log retention; configure project notifications (email/Slack/webhook) to surface
failures, or point the notification email at a Pushover email-to-app address.

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

One kubeconfig is required on shoebox:

| Path | Endpoint | Used by |
|---|---|---|
| `/home/ansible/.kube/config` | `https://10.10.10.9:6443` (kube-vip VIP) | all plays |

All plays reach the cluster through the kube-vip control-plane VIP, which floats
across the masters — so kubectl stays reachable even while the master being
upgraded (cluster1 included) is drained and rebooting. The kubeconfig is never
mutated.

The file must be group-readable by gid 1001 (Semaphore container):

```bash
chown ansible:1001 /home/ansible/.kube/config
chmod 640 /home/ansible/.kube/config
```

The Semaphore container runs as `uid=1001 gid=0` by default. Docker-compose adds
gid 1001 as a supplementary group via `group_add: ["1001"]` so the process can
read this file. gid 1001 has no name on shoebox — that's fine, the numeric gid
is what matters.

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

**Data loss surface**: `k3s-agent-uninstall.sh` removes `/var/lib/rancher/k3s/` on the node,
which includes the local-path-provisioner storage root (`/var/lib/rancher/k3s/storage/`).
Any PVCs backed by the node's local-path storage class are destroyed. After a CRITICAL
alert, enumerate what was lost on the affected node:
```bash
kubectl get pv -o wide | grep <node>            # local-path PVs that were on the node
kubectl get pods -A --field-selector spec.nodeName=<node>  # pods that ran there
```

**Labels and taints**: the reinstalled node joins with default k3s labels only. Any custom
labels or taints (e.g. `node-role=storage`, topology labels, Longhorn tags) must be
re-applied manually before scaling workloads back onto the node. Run
`kubectl get node <node> --show-labels` on a healthy peer node to see which custom
labels are expected, then `kubectl label node <node> <key>=<value>` for each.

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
# NOTE: if the CRITICAL alert says "rebuild failed", k3s-agent-uninstall.sh already ran —
# the k3s service is gone, so journalctl shows nothing useful. The node is now a bare
# OS with no k3s; re-run cluster/ansible/k3s-agent.yaml against it after fixing the
# underlying issue. Check for diagnosis:
#   /var/log/apt/history.log   (what the dist-upgrade changed)
#   /var/lib/ansible-upgrade/pre-upgrade.txt   (package snapshot before upgrade)

# 2. Fix the underlying issue manually

# 3. Uncordon (only after verifying node health)
kubectl uncordon <node>

# 4. Clear state flags (from shoebox host shell or via docker exec into Semaphore —
#    /var/lib/ansible-upgrade is bind-mounted so both paths write the same files;
#    see shoebox/semaphore/docker-compose.yaml for the bind mount)
#    Note: only needed when re-running with --limit (skipping the agents play).
#    A full re-run clears rolling-upgrade-failed automatically in agents pre_tasks.
#    Verify the bind mount is working: docker exec semaphore ls /var/lib/ansible-upgrade/
#    should list the same files as: ls /var/lib/ansible-upgrade/ on the host.
rm /var/lib/ansible-upgrade/rolling-upgrade-failed
# Also clear if maintenance-in-progress is stale (e.g. Semaphore was killed mid-run):
rm -f /var/lib/ansible-upgrade/maintenance-in-progress

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

Vault secrets consumed from `vault_file`: `k3s_token`, `pushover_app_token`, `pushover_user_key`. (`k3s_api_server_url` is a non-secret default in `group_vars/all.yaml`, not a vault secret.)

### shoebox/shoebox-ansible-setup.yaml

One-time bootstrap, run from the operator's workstation.

| Variable | Required | Source | Description |
|---|---|---|---|
| `vault_password` | **Yes** | vault | The Ansible vault password itself, written to `/etc/ansible/vault-password` on shoebox (mode 0400, owner ansible). |
| `pushover_app_token` | **Yes** | vault | Pushover application token |
| `pushover_user_key` | **Yes** | vault | Pushover user key |
| `semaphore_admin_password` | **Yes** | vault | Semaphore admin login password |
| `semaphore_access_key_encryption` | **Yes** | vault | Standard base64 AES key for Semaphore secret-at-rest encryption. Generate with: `openssl rand -base64 32 \| tr -d '\n'`. Must be standard base64 (not URL-safe — `-` and `_` cause "illegal base64 data at input byte N" when adding keys). The bootstrap playbook validates the format via `shoebox/scripts/validate-semaphore-key.sh` and fails fast if malformed; the same validator runs in CI against good and bad inputs. |

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

1. Fill in shoebox's static LAN IP in `cluster/ingress-only/semaphore.yaml` (replace `192.168.1.SHOEBOX_IP`)
2. Apply the ingress manifest: `kubectl apply -f cluster/ingress-only/semaphore.yaml`
3. Open `http://semaphore.vert`
4. **Key Store**: add Ansible Vault password as "LoginPassword" key named `vault`
5. **Repository**: URL `https://github.com/ohthehugemanatee/homenet-documentation` — public repo, HTTPS, no auth needed. Semaphore clones it for each run; no bind-mount required.
6. **Inventory**: `cluster/ansible/inventory.yaml` (relative to repo root)
7. **Environment**: set `KUBECONFIG=/home/semaphore/.kube/config`
8. **Task templates** (playbook path relative to repo root; vault_file relative to playbook dir):
   - node-state: `ansible-playbook -i cluster/ansible/inventory.yaml --vault-password-file /etc/ansible/vault-password cluster/ansible/node-state.yaml`
   - rolling-upgrade: `ansible-playbook -i cluster/ansible/inventory.yaml --vault-password-file /etc/ansible/vault-password -e vault_file=group_vars/vault.yaml -e strict_mode=true cluster/ansible/rolling-upgrade.yaml`

> All required bind mounts (vault-password, kubeconfigs, kubectl binary, SSH keys, state dirs) are configured in `shoebox/semaphore/docker-compose.yaml` and set up by the bootstrap playbook.

---

## Monitoring and Alertmanager/Pushover

Grafana/Prometheus configured together in `cluster/helm/kube-prometheus-stack/values.yaml` with alertmanager under `alertmanager.config`. Loki is added from `cluster/helm/loki/values.yaml`. Alloy (log collector DaemonSet) is configured in `cluster/helm/alloy/values.yaml`. Kubernetes Events are shipped to Loki by event-exporter (`cluster/helm/kubernetes-event-exporter/values.yaml`). Each chart directory has an install script.

Pushover credentials are stored in a pre-created K8s Secret (not in the values file).

Easy deployment:

```bash
cd cluster/helm/kube-prometheus-stack && ./install.sh
cd ../loki && ./install-loki.sh
cd ../alloy && ./install-alloy.sh
```

Manual deployment:

```bash
# Create the secret once (before first deploy):
kubectl create secret generic alertmanager-pushover \
  -n monitoring \
  --from-literal=token=<PUSHOVER_APP_TOKEN> \
  --from-literal=user_key=<PUSHOVER_USER_KEY>

# Deploy kube-prometheus-stack:
helm upgrade --install kube-prometheus-stack \
  oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack \
  -n monitoring --create-namespace \
  -f cluster/helm/kube-prometheus-stack/values.yaml

# Deploy community Loki chart:
helm upgrade --install loki \
  oci://ghcr.io/grafana-community/helm-charts/loki \
  -n loki --create-namespace \
  -f cluster/helm/loki/values.yaml

# Deploy Alloy log collector:
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update grafana
helm upgrade --install alloy grafana/alloy \
  -n monitoring --create-namespace \
  -f cluster/helm/alloy/values.yaml

# Deploy event-exporter (Kubernetes Events → Loki):
helm repo add resmoio https://resmoio.github.io/kubernetes-event-exporter
helm repo update resmoio
helm upgrade --install kubernetes-event-exporter \
  resmoio/kubernetes-event-exporter --version 0.4.2 \
  -n monitoring --create-namespace \
  -f cluster/helm/kubernetes-event-exporter/values.yaml
```

Covers: NodeNotReady, pod OOMKill, CrashLoopBackOff, PVC near full, and any future
PrometheusRule alerts.

Note: Alertmanager lives in-cluster and cannot alert if the entire cluster is down.

---

## Alert deep links → workload-debug dashboard

Pushover notifications carry a **Debug in Grafana** button. Alertmanager builds the
URL from the alert's labels in the `pushover_configs` receiver
(`cluster/helm/kube-prometheus-stack/values.yaml`):

```
https://grafana.berlin.vertesi.com/d/workload-debug?var-namespace={{ .CommonLabels.namespace }}&var-pod={{ .CommonLabels.pod }}
```

Because the link is built in the receiver (not per-rule), it covers every alert that
carries `namespace`/`pod` labels — both the `homelab.pod_health` rules
(`cluster/services/probe-alerts.yaml`) and upstream kube-prometheus-stack alerts.
`route.group_by` includes `namespace` so `.CommonLabels.namespace` resolves per group;
`.CommonLabels.pod` is empty when a group spans multiple pods, in which case the
dashboard's `pod` variable defaults to all pods in the namespace.

The **workload-debug** dashboard (`cluster/services/grafana-workload-debug.yaml`, uid
`workload-debug` — the alert URL depends on this uid) is a single parameterized view
scoped by the `namespace`/`pod` template variables:

| Panel | Source | Shows |
|---|---|---|
| Firing Alerts | Prometheus `ALERTS` | what's firing in the namespace |
| Kubernetes Events | Loki (event-exporter) | recent cluster events |
| Pod Logs | Loki (Alloy) | pod stdout/stderr |
| CPU / Memory / Disk / Network | Prometheus (cAdvisor) | resource load |
| ArgoCD App Status | Prometheus `argocd_app_info` | sync/health + link to ArgoCD UI |

The Events panel needs **event-exporter** (`cluster/helm/kubernetes-event-exporter/`)
and the ArgoCD panel needs the chart's ServiceMonitor
(`controller.metrics.serviceMonitor.enabled` in `cluster/helm/argocd/values.yaml`).

---

## Log pipeline

Two collection paths feed logs into Loki:

| Path | What it collects | Mechanism |
|---|---|---|
| Alloy DaemonSet | stdout/stderr from all pods | `discovery.kubernetes` pod role, runs on every node (including control-plane) |
| Promtail sidecars | File-based logs from specific pods | Shared volume mount, reads `*.log` from application log directories |

**Alloy** (`cluster/helm/alloy/values.yaml`) runs as a DaemonSet in the `monitoring`
namespace. It discovers all pods via the Kubernetes API, relabels with namespace/pod/
container/node metadata, and pushes to `http://loki.loki.svc.cluster.local:3100`.
This covers every workload that logs to stdout/stderr (the standard Kubernetes pattern).

**Promtail sidecars** (`cluster/ConfigMaps/sidecar-promtail.yaml`) are deployed as
additional containers inside pods that write logs to files rather than stdout. Currently
used by: plex, nextcloud, duplicacy. Each sidecar mounts a shared volume with the
application container, tails `*.log` files, and pushes to the same Loki endpoint.
The sidecar image is `grafana/promtail:2.1.0`.

Both paths are complementary: Alloy handles cluster-wide stdout collection; promtail
sidecars handle the file-logging exceptions.

---

## Known workaround: skipTlsVerify

The k3s CA certificate lacks the Authority Key Identifier (AKI) extension. Python 3.13+
(used in Grafana sidecar images) rejects certificates without AKI. As a workaround,
`skipTlsVerify: true` is set in both `kube-prometheus-stack/values.yaml` and
`loki/values.yaml` for the sidecar configuration. This affects only the sidecar's
communication with the Kubernetes API for dashboard/datasource discovery — not
Prometheus scraping or Loki ingestion.

Tracked: regenerate the k3s CA with AKI/SKI extensions to remove this workaround.

---

## Troubleshooting the observability stack

### Logs not appearing in Grafana

```bash
# Check Alloy pods are running on all nodes
kubectl get pods -n monitoring -l app.kubernetes.io/name=alloy -o wide

# Check Alloy logs for push errors
kubectl logs -n monitoring daemonset/alloy --tail=50

# Check Loki is accepting writes
kubectl logs -n loki -l app.kubernetes.io/name=loki --tail=50 | grep -i error

# Verify Loki is reachable from inside the cluster
kubectl run -n monitoring --rm -it --image=busybox test-loki -- \
  wget -qO- http://loki.loki.svc.cluster.local:3100/ready
```

### Promtail sidecar not collecting

```bash
# Check the sidecar container logs inside the affected pod
kubectl logs <pod> -c plex-promtail    # or nextcloud-promtail, promtail-sidecar
# Verify the shared volume has log files
kubectl exec <pod> -c <app-container> -- ls /sidecar-logs/
```

### Alerts not firing

```bash
# Check Alertmanager is running
kubectl get pods -n monitoring -l app.kubernetes.io/name=alertmanager

# Verify the pushover secret exists and has both keys
kubectl get secret -n monitoring alertmanager-pushover -o jsonpath='{.data}' | \
  python3 -c "import sys,json,base64; d=json.load(sys.stdin); print({k:len(base64.b64decode(v)) for k,v in d.items()})"

# Check Alertmanager logs for send failures
kubectl logs -n monitoring -l app.kubernetes.io/name=alertmanager --tail=50 | grep -i pushover

# View currently firing alerts
kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager 9093:9093 &
curl -s localhost:9093/api/v2/alerts | python3 -m json.tool
```

### Prometheus not scraping

```bash
# Check targets page (port-forward first)
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &
# Open localhost:9090/targets in a browser

# Check Prometheus logs
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus --tail=50
```
