# nextcloud-mcp-server — MCP access to Nextcloud for Claude clients

`nextcloud-mcp-server` (upstream: [cbcoutinho/nextcloud-mcp-server](https://github.com/cbcoutinho/nextcloud-mcp-server))
exposes Nextcloud (notes, calendar, contacts, files, etc.) as MCP tools so Claude
clients can act on the live Nextcloud instance rather than just read docs about it.

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
```

Single replica: `login_flow` keeps provisioning sessions in memory. Unlike the BasicAuth
deployment this replaced it is **not** stateless — the token DB (`/app/data/tokens.db`,
1Gi Longhorn PVC) holds each user's app password encrypted with `token_encryption_key`;
rotating that key without wiping the DB fails startup with `fernet.InvalidToken`.

## Configuration

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

Rollback is `values.yaml` back to `auth.mode: basic`, so keep the now-unused
`nextcloud-claude-mcp` Secret until this is confirmed working.

## GitOps

[`cluster/argocd/apps/nextcloud-mcp-server.yaml`](cluster/argocd/apps/nextcloud-mcp-server.yaml)
is a manual-sync Application (`helm.releaseName: nextcloud-mcp`) — this workload was
originally installed by hand (`helm install`) before being brought under GitOps, so
manual sync matches `kubernetes-mcp-server`'s tier: single-pod utility, not complex
stateful infra, but still worth watching the first sync of a version bump rather than
letting `automated`/`selfHeal` apply it unattended.

## Verify

```sh
curl -s -o /dev/null -w '%{http_code}' https://mcp.germany.vertesi.com/health/live
```

should return `200`.

First connector use redirects to Nextcloud's login to grant an app password — per user,
and revocable from Nextcloud → Settings → Security → Devices & Sessions.
