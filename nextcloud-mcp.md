# nextcloud-mcp-server — MCP access to Nextcloud for Claude clients

`nextcloud-mcp-server` (upstream: [cbcoutinho/nextcloud-mcp-server](https://github.com/cbcoutinho/nextcloud-mcp-server))
exposes Nextcloud (notes, calendar, contacts, files, etc.) as MCP tools so Claude
clients can act on the live Nextcloud instance rather than just read docs about it.

Two releases of the same chart run side by side in `default`, differing only in how the
client authenticates:

| Endpoint | Release | `auth.mode` | For |
|---|---|---|---|
| `mcp.germany.vertesi.com` | `nextcloud-mcp` | `login-flow` | claude.ai Connectors — OAuth 2.1 + PKCE browser flow |
| `mcp2.germany.vertesi.com` | `nextcloud-mcp-basic` | `multi-user-basic` | headless/CLI clients that can set `Authorization: Basic` |

Both are per-user: neither serves every client as one shared account. Pick by what the
client can do, not by trust level.

## Architecture

```
Claude Code / claude.ai Connectors (web, mobile)
  │  outbound HTTPS, MCP client — OAuth 2.1 + PKCE
  ▼
Ingress mcp.germany.vertesi.com (Traefik, letsencrypt-prod)
  ▼
nextcloud-mcp Deployment (cluster/helm/nextcloud-mcp-server/values.yaml)
  │  auth: OIDC RP of Nextcloud's oidc app (static client in Secret nextcloud-mcp-oauth)
  │  data: per-user Nextcloud app password, from Login Flow v2
  ▼
germany.vertesi.com (cluster/services/nextcloud.yaml)


Headless MCP clients (CLI, scripts)
  │  outbound HTTPS, Authorization: Basic <user:app-password>
  ▼
Ingress mcp2.germany.vertesi.com (Traefik, letsencrypt-prod)
  ▼
nextcloud-mcp-basic Deployment (cluster/helm/nextcloud-mcp-basic/values.yaml)
  │  auth: pass-through — credentials forwarded verbatim to Nextcloud
  │  data: none (stateless)
  ▼
germany.vertesi.com (cluster/services/nextcloud.yaml)
```

Single replica on `nextcloud-mcp`: `login_flow` keeps provisioning sessions in memory. It
is **not** stateless — the token DB (`/app/data/tokens.db`, 1Gi Longhorn PVC) holds each
user's app password encrypted with `token_encryption_key`; rotating that key without
wiping the DB fails startup with `fernet.InvalidToken`.

## Configuration — `mcp` (login-flow)

Values override: [`cluster/helm/nextcloud-mcp-server/values.yaml`](cluster/helm/nextcloud-mcp-server/values.yaml).
`auth.mode: login-flow` — the chart derives `--oauth` and `MCP_DEPLOYMENT_MODE=login_flow`
from it. One Secret holds all three keys and must be named by **both**
`auth.loginFlow.existingSecret` and `auth.loginFlow.oidcExistingSecret`: the chart gates
the OIDC client env vars on the latter, so setting only the former silently drops them.

Created out-of-band, never committed:

```sh
kubectl create secret generic nextcloud-mcp-oauth \
  --from-literal=token_encryption_key=<CHANGEME_fernet_key> \
  --from-literal=client_id=<CHANGEME_oidc_client_id> \
  --from-literal=client_secret=<CHANGEME_oidc_client_secret> \
  -n default
```

Generate `token_encryption_key` with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`;
`client_id` / `client_secret` come from the OIDC client registered below.

Three settings the chart has no values for ride in `extraEnv`: `ALLOWED_MCP_CLIENTS`
(which MCP clients may use the OAuth flow — see below), `NEXTCLOUD_RESOURCE_URI` (token
audience; the server warns when it is left implicit) and `CORS_ALLOW_ORIGINS` (narrowed
from the default `*`, which would let any origin send credentialed requests).

## OAuth setup (one-time, operator-run)

1. Apps → enable the **OpenID Connect provider** (`oidc`) app — Nextcloud is its own
   IdP here, no external provider.
2. **Administration settings → OpenID Connect provider → Add client**: redirect URI
   `https://mcp.germany.vertesi.com/oauth/callback`, response type **code**, type
   **confidential**, resource identifier `https://mcp.germany.vertesi.com/mcp`, scopes
   empty. **Must be admin-registered, never Dynamic Client Registration** — the `oidc`
   app deletes DCR clients after `client_expire_time` (default 1h), permanently breaking
   the connector with an "Access forbidden" page that re-adding does not fix.
3. Create the Secret from the generated client ID/secret, per the recipe above.
4. Sync the `nextcloud-mcp-server` Application — but not before step 3, or the pod
   `CrashLoopBackOff`s and its `on-out-of-sync` Pushover alert pages you for a state you
   caused on purpose.
5. claude.ai → Settings → Connectors → remove and re-add the connector for
   `https://mcp.germany.vertesi.com/mcp`; an existing one caches the old failed
   discovery and won't retry. Enter **Client ID `claude-ai`** and leave the **client
   secret blank** — see below.

**Verify:** `curl -s -o /dev/null -w '%{http_code}' https://mcp.germany.vertesi.com/.well-known/oauth-authorization-server`
should return `200`. `404` means the OAuth facade isn't mounted; `5xx` means it is, but
OIDC discovery is failing — usually the `oidc` app isn't enabled.

### The two client IDs are not the same thing

Easy to conflate, and conflating them fails with `401 Unknown client_id`:

| | Identifies | Configured by |
|---|---|---|
| Nextcloud OIDC client | MCP server → Nextcloud | Secret `nextcloud-mcp-oauth`, registered in step 2 |
| MCP client (`claude-ai`) | claude.ai → MCP server | `ALLOWED_MCP_CLIENTS` in `values.yaml` |

The claude.ai UI asks for the **second** one. It is a name we choose, not a credential —
neither the Nextcloud client ID nor a Nextcloud username, and there is no secret to
enter, because MCP clients are public clients proven by PKCE. Nextcloud's `oidc` app
doesn't support Dynamic Client Registration, so `POST /oauth/register` returns 400 and
claude.ai falls back to asking; the allowlist is what makes that answer work.

Your Nextcloud app password is never entered anywhere — Login Flow v2 provisions one per
user through the browser redirect on first connector use.

## Configuration — `mcp2` (multi-user basic)

Values override: [`cluster/helm/nextcloud-mcp-basic/values.yaml`](cluster/helm/nextcloud-mcp-basic/values.yaml).
`auth.mode: multi-user-basic` — the chart derives `MCP_DEPLOYMENT_MODE=multi_user_basic`.
The client sends `Authorization: Basic` on every request; the server forwards those
credentials to Nextcloud and does nothing else with them.

Nothing to create out-of-band: `auth.multiUserBasic.enableOfflineAccess: false` keeps the
release stateless, so there is no token DB, no PVC, no `token_encryption_key`, and no
second OIDC client to register. Turning offline access on would pull in the entire
login-flow footprint above, key-rotation trap included.

**Use an app password per client, not your account password.** Nextcloud → Settings →
Security → Devices & Sessions → *Create new app password*. Same revocation surface as the
login-flow endpoint; the difference is that you provision it yourself instead of the
browser redirect doing it for you.

No OAuth facade is mounted in this mode. Pointing claude.ai's Connectors UI at `mcp2`
404s on `/.well-known/oauth-authorization-server` — expected, not a bug; that is what
`mcp` is for.

### `mcp2` does not challenge at the edge

Upstream's `BasicAuthMiddleware` *extracts* an `Authorization: Basic` header when one is
present and then continues the request chain unconditionally — it never returns `401` and
never sends `WWW-Authenticate`. Consequences, all of them by upstream design:

- An unauthenticated `GET /mcp` returns `406`, from content negotiation, not from auth.
- The MCP handshake is reachable anonymously: `initialize` and `tools/list` answer without
  credentials, so the **tool surface is publicly enumerable** on this host.
- Credentials are enforced **per operation**, when a tool builds its Nextcloud client. No
  Nextcloud data is reachable without them, and Nextcloud itself owns brute-force
  throttling since every credential is checked there.

So the exposure is tool-surface disclosure, not data. If that is not acceptable, the fix is
to drop `ingress.enabled` and reach the Service in-cluster, not to expect a `401`.

No DNS step: `*.germany.vertesi.com` already resolves to the home IP that
[`cluster/services/cloudflare-ddns.yaml`](cluster/services/cloudflare-ddns.yaml) keeps
current, and HTTP-01 reaches Traefik over the port-forward that already serves `mcp`.

The now-unused `nextcloud-claude-mcp` Secret (single shared account, `auth.mode: basic`)
is what `mcp2` supersedes — headless clients that used to share that account get their own
credentials here. Keep the Secret only as long as you want the old single-account rollback.

## GitOps

[`cluster/argocd/apps/nextcloud-mcp-server.yaml`](cluster/argocd/apps/nextcloud-mcp-server.yaml)
is a manual-sync Application (`helm.releaseName: nextcloud-mcp`) — this workload was
originally installed by hand (`helm install`) before being brought under GitOps, so
manual sync matches `kubernetes-mcp-server`'s tier: single-pod utility, not complex
stateful infra, but still worth watching the first sync of a version bump rather than
letting `automated`/`selfHeal` apply it unattended.

[`cluster/argocd/apps/nextcloud-mcp-basic.yaml`](cluster/argocd/apps/nextcloud-mcp-basic.yaml)
is auto-sync (`prune` + `selfHeal`, with the finalizer). The tier differs because the
release does: no PVC, no Secret, no provisioning state, so a bad sync costs a pod restart
rather than a token DB. Deleting the Application cascade-deletes its resources — which is
the intent for something rebuildable from `values.yaml` alone.

## Verify

```sh
curl -s -o /dev/null -w '%{http_code}' https://mcp.germany.vertesi.com/health/live   # 200
curl -s -o /dev/null -w '%{http_code}' https://mcp2.germany.vertesi.com/health/live  # 200
```

`mcp2`'s `/health/live` reports `{"status":"alive","mode":"basic"}`. That `basic` is the
auth *family*, not the deployment mode — `single_user_basic` and `multi_user_basic` both
report it, and it is not evidence of a fallback to the single shared account. The
deployment mode is the `MCP_DEPLOYMENT_MODE` env var, which CI asserts is
`multi_user_basic`:

```sh
kubectl -n default get deploy nextcloud-mcp-basic-nextcloud-mcp-server \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="MCP_DEPLOYMENT_MODE")].value}'
```

Do **not** verify `mcp2` by expecting a `401` from an unauthenticated request — per the
section above, it does not issue one. Verify it by calling a tool with
`-u '<user>:<app-password>'` and getting a real result back.

First connector use on `mcp` redirects to Nextcloud's login to grant an app password — per
user, and revocable from Nextcloud → Settings → Security → Devices & Sessions.
