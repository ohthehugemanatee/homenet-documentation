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
  │  auth leg: OIDC relying party of Nextcloud's OpenID Connect provider (oidc) app,
  │            using the static client in Secret nextcloud-mcp-oauth
  │  data leg: per-user Nextcloud app password, obtained via Login Flow v2
  ▼
germany.vertesi.com (cluster/services/nextcloud.yaml)
```

Two legs, deliberately separate: the MCP client authenticates to the MCP server with
OAuth against Nextcloud's own OIDC provider, and the MCP server then acts on Nextcloud
with an app password it provisioned for that specific user. Nobody's password is
stored, and each user's access is their own.

Single replica — `MCP_DEPLOYMENT_MODE=login_flow` keeps its provisioning sessions in
memory and assumes a single worker, so don't scale this up without a sticky-session
load balancer in front.

Unlike the previous BasicAuth deployment, this workload is **not** stateless: the
SQLite token DB (`/app/data/tokens.db`, on a 1Gi Longhorn PVC) holds every user's
Nextcloud app password, encrypted with `token_encryption_key`. Rotating that key
without wiping the DB makes the server raise `cryptography.fernet.InvalidToken` on
startup; wiping the DB forces every user to re-authorize.

## Configuration

Values override: [`cluster/helm/nextcloud-mcp-server/values.yaml`](cluster/helm/nextcloud-mcp-server/values.yaml).
Auth mode is Login Flow v2 (`auth.mode: login-flow`), from which the chart derives the
`--oauth` flag and `MCP_DEPLOYMENT_MODE=login_flow`. One Secret holds all three values,
named by **both** `auth.loginFlow.existingSecret` and `auth.loginFlow.oidcExistingSecret`
— the chart gates the OIDC client env vars on the latter, so setting only the former
silently drops them (see the comment in `values.yaml`).

The Secret itself is created out-of-band, never committed:

```sh
kubectl create secret generic nextcloud-mcp-oauth \
  --from-literal=token_encryption_key=<CHANGEME_fernet_key> \
  --from-literal=client_id=<CHANGEME_oidc_client_id> \
  --from-literal=client_secret=<CHANGEME_oidc_client_secret> \
  -n default
```

`token_encryption_key` is a Fernet key — generate one with:

```sh
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`client_id` / `client_secret` come from the Nextcloud OIDC client registered below.

## OAuth setup (one-time, operator-run)

Done once against the existing Nextcloud instance — no external IdP, Nextcloud is its
own identity provider here:

1. Apps → enable the **OpenID Connect provider** (`oidc`) app.
2. **Administration settings → OpenID Connect provider → Add client**:
   - **Redirect URI:** `https://mcp.germany.vertesi.com/oauth/callback`
   - **Flow / response type:** authorization **code**
   - **Type:** **confidential** — it must issue a client secret.
   - **Resource identifier:** `https://mcp.germany.vertesi.com/mcp`, so issued tokens
     carry the MCP server's audience.
   - **Scopes:** leave empty to allow all.
   This client **must be admin-registered (static), never left to Dynamic Client
   Registration** — the `oidc` app treats DCR clients as ephemeral and deletes them
   after `client_expire_time` (default 1h), which permanently breaks the connector
   with an "Access forbidden" page that re-adding the connector does not fix.
3. Copy the generated client ID and secret and create the real secret on the live
   cluster (never committed):
   ```sh
   kubectl create secret generic nextcloud-mcp-oauth \
     --from-literal=token_encryption_key=<fernet-key> \
     --from-literal=client_id=<client-id> \
     --from-literal=client_secret=<client-secret> \
     -n default
   ```
4. Sync the `nextcloud-mcp-server` ArgoCD Application now that the real secret exists.
   Don't sync it before step 3 — the pod will `CrashLoopBackOff` without the Secret,
   and the Application's `on-out-of-sync` Pushover alert will page you for a state you
   caused on purpose.
5. claude.ai → Settings → Connectors → remove and re-add the connector pointed at
   `https://mcp.germany.vertesi.com/mcp`. An existing connector caches the failed
   BasicAuth-era discovery result and will not retry on its own.

**Verify:** `curl -s -o /dev/null -w '%{http_code}' https://mcp.germany.vertesi.com/.well-known/oauth-authorization-server`
should return `200` — a `404` means the OAuth facade isn't mounted (still in BasicAuth
mode), a `5xx` means it is mounted but OIDC discovery against Nextcloud is failing,
usually because the `oidc` app isn't enabled.

The old `nextcloud-claude-mcp` Secret is unused once this is working, and can be
deleted out-of-band. Keep it until then — reverting `values.yaml` to `auth.mode: basic`
is the rollback path.

## GitOps

[`cluster/argocd/apps/nextcloud-mcp-server.yaml`](cluster/argocd/apps/nextcloud-mcp-server.yaml)
is a manual-sync Application (`helm.releaseName: nextcloud-mcp`) — this workload was
originally installed by hand (`helm install`) before being brought under GitOps, so
manual sync matches `kubernetes-mcp-server`'s tier: single-pod utility, not complex
stateful infra, but still worth watching the first sync of a version bump rather than
letting `automated`/`selfHeal` apply it unattended. Login Flow v2 gives it one piece of
real state — the token DB PVC — which raises the cost of an unattended sync rather than
lowering it, so manual stays right.

## Verify

```sh
curl -s -o /dev/null -w '%{http_code}' https://mcp.germany.vertesi.com/health/live
```

should return `200`.

First use of a connector redirects to Nextcloud's login page to grant the MCP server an
app password. That grant is per user and revocable from Nextcloud → Settings → Security
→ Devices & Sessions; revoking it makes the server's stored password 401 until the user
re-authorizes.
