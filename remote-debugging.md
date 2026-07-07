# Remote debugging — read-only cluster access for Claude Code cloud sessions

Lets a Claude Code cloud session (an ephemeral container with no LAN presence) run
`kubectl get/describe/logs/events` against the live cluster without the operator
opening a laptop or connecting a VPN.

## Why not a VPN

Claude Code's cloud environment only allows outbound HTTPS through a
domain-allowlisted proxy (environment "Network access": None/Trusted/Full/Custom).
It cannot carry WireGuard, Tailscale, or any other non-HTTP(S) protocol, so the
existing OpenVPN setup, Tailscale, and a WireGuard pod are all ruled out as the
network layer — none of their client protocols can traverse that proxy. The only
way in is a public HTTPS hostname added to the environment's Custom allowlist.

## Architecture

```
Claude Code cloud session (Custom network access: allowlisted hostname only)
  │  local `cloudflared access` forwarder, started by a SessionStart hook
  ▼
Cloudflare edge — Access policy (Service Token check) — Cloudflare Tunnel
  ▼
in-cluster `cloudflared` Deployment (cluster/services/cloudflared.yaml)
  ▼
kubernetes.default.svc:443 — RBAC-limited by the `view` ClusterRole bound to
the `claude-remote-debug` ServiceAccount (cluster/services/claude-remote-debug-rbac.yaml)
```

`cloudflared` makes an outbound-only connection to Cloudflare's edge — no inbound
port is opened on the router. Cloudflare Access checks a Service Token at the edge
before any request reaches the tunnel, which matters because Claude Code environment
variables are not a real secrets store (see below).

## Read-only scope

`claude-remote-debug` is bound to the built-in `view` ClusterRole: `get`/`list`/`watch`
on most resources, no `secrets` access at all, and no `create` verb (so no `exec`,
no `attach`, no writes). There is no logging backend (Loki isn't deployed) — `kubectl
logs` reads directly from the API server, which is why this design exposes the API
server rather than Prometheus/Grafana.

**`view` also grants cluster-wide `get`/`list` on ConfigMaps** — don't use ConfigMaps
for secret-adjacent data, since anything in one is now readable from a Claude Code
session.

**Privacy note:** `view` grants `get pods/log` cluster-wide, and a session with a
valid token can read live logs from every workload — Plex, Nextcloud, Unifi,
delugevpn, etc. Those logs can contain personal viewing/download activity and
household network topology (Unifi). This is the actual personal-data exposure
surface of this design, distinct from "no Secrets access" — weigh it before
widening scope (e.g. handing the token to anything beyond this one use case).

## Configuring the Claude Code environment

1. **Network access:** set to `Custom`. Add to **Allowed domains**:
   - the tunnel hostname (e.g. `k8s-debug.vertesi.com`)
   - `*.cloudflareaccess.com` — confirmed empirically as the host the
     `cloudflared access tcp` forwarder's Access handshake needs.
     `*.argotunnel.com` was a candidate but wasn't hit in testing; add it if a
     future `cloudflared`/Access version needs it.
   - `github.com` and `objects.githubusercontent.com` — needed by the
     SessionStart hook below to download the `cloudflared` binary from GitHub
     Releases. Without these the hook logs a warning and skips the forwarder,
     it does not fail the session.
   - `dl.k8s.io` — needed by the same hook to download `kubectl`. Confirmed
     reachable through the default agent proxy without being added to Custom
     allowed domains in at least one tested environment; add it explicitly if
     your environment's policy is stricter.
2. **Environment variables:**
   - `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET` — from the Cloudflare Access
     Service Token (Issue setup below).
   - `K8S_BEARER_TOKEN` — minted by `mint-remote-debug-token.yaml` (below).
   - `K8S_API_HOSTNAME` — the tunnel hostname.

   **These environment variables are visible to anyone who can edit the Claude Code
   environment configuration — there is no dedicated secrets store.** Every credential
   here is deliberately read-only, has no Secrets access, and is short-lived. Do not
   widen this scope later without re-reading this paragraph.
3. **SessionStart hook:** `.claude/hooks/session-start.sh` (registered in
   `.claude/settings.json`). No-ops unless all four env vars above are set. Installs
   `cloudflared` and `kubectl` into `~/.local/bin` if missing, starts a local forwarder
   (`cloudflared access tcp --hostname $K8S_API_HOSTNAME --url 127.0.0.1:6443
   --service-token-id=$CF_ACCESS_CLIENT_ID --service-token-secret=$CF_ACCESS_CLIENT_SECRET`)
   unless one is already running from a prior resume/clear/compact, then writes a
   throwaway kubeconfig (`~/.kube/config-remote-debug`, `insecure-skip-tls-verify: true`
   per the loopback TLS SAN caveat below) with `token: $K8S_BEARER_TOKEN` and exports
   `KUBECONFIG` for the session. Every step that can fail because of network policy
   (binary download, forwarder connect) logs a warning and continues rather than
   aborting session start.

## One-time Cloudflare setup (out-of-band, operator-run)

Done once against the existing Cloudflare account (already used for DNS-01 wildcard
certs and DDNS — no new signup):

1. Zero Trust dashboard → Tunnels → create `homenet-k8s-debug`, hostname e.g.
   `k8s-debug.vertesi.com`. Cloudflare auto-issues Universal SSL for this hostname —
   no cert-manager/DNS-01 involvement, stays separate from the existing
   `berlin.vertesi.com` wildcard.
2. Ingress rule → origin `https://kubernetes.default.svc:443`.
3. Copy the tunnel token; create the real secret on the live cluster (never
   committed):
   ```sh
   kubectl create secret generic cloudflared-tunnel-credentials \
     --from-literal=token=<tunnel-token> -n default
   ```
4. Access → Applications → self-hosted app for the same hostname, policy =
   **Service Auth** (this is a machine client, not a browser login).
5. Access → Service Auth → Service Tokens → create one. The Client ID/Secret shown
   (once, non-retrievable after) become `CF_ACCESS_CLIENT_ID` / `CF_ACCESS_CLIENT_SECRET`.
6. Sync the `cloudflared` ArgoCD Application now that the real secret exists. Don't
   sync it before step 3 — `cloudflared` will `CrashLoopBackOff` without the token,
   and the Application's `on-out-of-sync` Pushover alert will page you for a state
   you caused on purpose. Same ordering caveat applies if this Application is ever
   re-synced from scratch (e.g. cluster rebuild).

**Verify:** `curl -o /dev/null -w "%{http_code}" https://k8s-debug.vertesi.com/api/v1/namespaces`
should return `403` (Access blocks unauthenticated requests), and the tunnel should
show **HEALTHY** in the dashboard.

## Minting and rotating the debug token

```sh
ansible-playbook -i cluster/ansible/inventory.yaml cluster/ansible/mint-remote-debug-token.yaml
# or, for a longer session:
ansible-playbook -i cluster/ansible/inventory.yaml \
  -e debug_token_duration=24h cluster/ansible/mint-remote-debug-token.yaml
```

Copy the printed token into `K8S_BEARER_TOKEN`. There is no automated rotation —
re-run this playbook (by hand, or via Semaphore from a phone) whenever starting a
session. This matches the risk already accepted for `SEMAPHORE_ACCESS_KEY_ENCRYPTION`
on the shoebox host: a short-lived, read-only, no-Secrets credential sitting in a
visible-to-editors env var is an acceptable exposure window.

**Break-glass revocation** — invalidates every previously minted token instantly
(there is no `kubectl revoke token`):

```sh
kubectl delete sa claude-remote-debug -n default
kubectl apply -f cluster/services/claude-remote-debug-rbac.yaml
```

## Out of scope (by design)

- Automated token rotation.
- A logging backend for remote debugging — Loki is not deployed; `kubectl logs`
  via the API server is the only log path.
- Prometheus/Grafana exposure — Grafana already has a public ingress with no
  additional gate; this design deliberately does not extend that pattern further.

## Open risks

- `kubectl` cannot send arbitrary custom headers, so the Cloudflare Access Service
  Token can't be attached directly by kubectl — hence the local `cloudflared access
  tcp` forwarder described above. Cloudflare Access's mTLS client-certificate policy
  is a simpler alternative worth evaluating (it maps directly onto kubeconfig's
  `client-certificate-data`/`client-key-data`, no local forwarder needed) before
  committing to the Service Token approach above.
- `kubectl logs -f` / `exec` (chunked/SPDY streaming) through the tunnel, and the
  loopback TLS SAN for `https://127.0.0.1:6443`, are unverified against this
  cluster's actual k3s `--tls-san` config — confirm with a live smoke test
  (`kubectl get/describe/logs/logs -f/get events` succeed; `get secrets`/`exec`
  are `Forbidden`) before relying on this day to day.
- `cluster/services/cloudflared.yaml`'s image tag is pinned and will drift. This
  pod fronts the API server, so a stale tag here is higher-priority to keep current
  than most other workloads in this cluster — check
  [cloudflared releases](https://github.com/cloudflare/cloudflared/releases)
  periodically and bump manually; there's no Renovate/Dependabot wired up for
  cluster manifests.
