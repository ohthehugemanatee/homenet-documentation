# Remote debugging — read-only cluster access for Claude Code cloud sessions

Lets a Claude Code cloud session (an ephemeral container with no LAN presence) run
read-only queries (list/describe/logs/events, kubectl-equivalent) against the live
cluster via MCP tools, without the operator opening a laptop or connecting a VPN.

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
  │  outbound HTTPS, MCP client (.mcp.json — kubernetes-mcp-server)
  ▼
Cloudflare edge — Access policy (Service Token check) — Cloudflare Tunnel
  ▼
in-cluster `cloudflared` Deployment (cluster/services/cloudflared.yaml)
  ▼
in-cluster `kubernetes-mcp-server` (cluster/helm/kubernetes-mcp-server/) — talks to
kubernetes.default.svc:443 itself, RBAC-limited by the `view` ClusterRole bound to
the `claude-remote-debug` ServiceAccount (cluster/services/claude-remote-debug-rbac.yaml)
```

No local process runs in the sandbox — the session's own MCP client connects
directly to the public hostname over outbound HTTPS, no forwarder needed. Cloudflare
Access checks a Service Token (headers set via `.mcp.json`'s env-var interpolation)
at the edge before any request reaches the tunnel, which matters because Claude Code
environment variables are not a real secrets store (see below).

The original forwarder-based path to `$K8S_API_HOSTNAME` (raw `kubectl` against
`kubernetes.default.svc:443` through a local `cloudflared access tcp` forwarder)
still exists as infrastructure — same tunnel, same Access mechanism, untouched by
this change — but is no longer automated. It's a manual fallback only, for the rare
case raw `kubectl` is needed beyond what MCP tools cover: see "One-time Cloudflare
setup" below for how that path was configured; reconstructing the forwarder and a
kubeconfig by hand runs the same commands the old SessionStart hook used to run
automatically.

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

1. **Network access:** set to `Custom`. Add to **Allowed domains**: the
   kubernetes-mcp-server hostname (e.g. `k8s-mcp.vertesi.com` — this is what the
   MCP client actually connects to by default now); `*.cloudflareaccess.com`
   (confirmed needed by the Access handshake); the original tunnel hostname
   (e.g. `k8s-debug.vertesi.com` — only needed if you reconstruct the manual
   forwarder fallback described in Architecture above).
2. **Environment variables:**
   - `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET` — from the Cloudflare Access
     Service Token (Issue setup below); sent as `CF-Access-Client-Id`/
     `CF-Access-Client-Secret` headers on the `kubernetes-mcp-server` MCP
     connection (`.mcp.json`).
   - `K8S_MCP_HOSTNAME` — the kubernetes-mcp-server hostname, used directly in
     `.mcp.json`'s `url`.
   - `K8S_BEARER_TOKEN` — minted by `mint-remote-debug-token.yaml` (below). No
     longer consumed by the client — `kubernetes-mcp-server` authenticates to
     the k8s API with its own in-cluster ServiceAccount token instead. Retained
     until #145 removes the mint-token flow entirely.
   - `K8S_API_HOSTNAME` — the original tunnel hostname. No longer used by
     default; only needed for the manual forwarder fallback.

   **These environment variables are visible to anyone who can edit the Claude Code
   environment configuration — there is no dedicated secrets store.** Every credential
   here is deliberately read-only, has no Secrets access, and is short-lived. Do not
   widen this scope later without re-reading this paragraph.
3. **MCP server registration:** declared in [`.mcp.json`](./.mcp.json) at the
   repo root, loaded automatically in every session (cloud or local — see
   [Claude Code's MCP docs](https://code.claude.com/docs/en/mcp)). No
   SessionStart hook, no bootstrap script, no local process: `type: "http"`,
   and the `url`/`headers` fields use `${VAR:-}`-style interpolation against
   the env vars above, so the file always parses even when they're unset — the
   server just won't authenticate until they are. Claude Code's own MCP client
   handles the streamable-HTTP session handshake.

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

### Exposing kubernetes-mcp-server (#143, same tunnel)

Adds a second public hostname to the *existing* `homenet-k8s-debug` tunnel — no new
tunnel, no new `TUNNEL_TOKEN` secret, `cluster/services/cloudflared.yaml` is
unchanged (routing lives entirely in the dashboard, same as the API hostname above).

1. Zero Trust dashboard → Tunnels → `homenet-k8s-debug` → add a second public
   hostname, e.g. `k8s-mcp.vertesi.com` → origin
   `http://kubernetes-mcp-server.default.svc:8080`. **Plain `http://`, not
   `https://`** — unlike the API server origin, the MCP server has no TLS listener.
2. Access → Applications → self-hosted app for the new hostname, policy =
   **Service Auth**.
3. Access → Service Auth → Service Tokens → either select the existing token
   from step 5 above as an allowed credential on this new Application (reuse —
   fewer secrets, the default here; no new env vars needed beyond
   `K8S_MCP_HOSTNAME` above), or create a dedicated token if you want separate
   credential blast-radius between the two hostnames (#144 will define how a
   second token's Client ID/Secret get supplied to the client, if you go this
   route).

**Verify:** `curl -o /dev/null -w "%{http_code}" https://k8s-mcp.vertesi.com/healthz`
should return `403` without Service Token headers; with them, a `200` (or a valid
MCP response from `/mcp`).

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

- Project-scoped `.mcp.json` servers normally require interactive approval on
  first use, and Claude Code's own docs note a freshly cloned repo may not be
  able to self-approve in an untrusted folder. Whether a fresh Claude Code
  cloud session counts as trusted enough to connect `kubernetes-mcp-server`
  without getting stuck at "Pending approval" was unresolved as of this
  writing — confirm empirically before relying on this day to day (check
  `/mcp` or equivalent in a genuinely new session).
- Long-lived/streaming calls (e.g. `kubectl logs -f`-equivalent via
  `kubernetes-mcp-server`'s log tool) are unverified against this cluster's
  actual behavior through the tunnel — confirm log/describe/list-style tools
  succeed and no destructive tool is exposed (see #142's CI check for the
  exec-suppression half of this) before relying on this day to day.
- `cluster/services/cloudflared.yaml`'s image tag is pinned and will drift. This
  pod fronts both the API server and kubernetes-mcp-server, so a stale tag here
  is higher-priority to keep current than most other workloads in this cluster —
  check [cloudflared releases](https://github.com/cloudflare/cloudflared/releases)
  periodically and bump manually; there's no Renovate/Dependabot wired up for
  cluster manifests.
