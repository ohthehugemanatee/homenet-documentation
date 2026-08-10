# nextcloud-mcp-server — MCP access to Nextcloud for Claude clients

`nextcloud-mcp-server` (upstream: [cbcoutinho/nextcloud-mcp-server](https://github.com/cbcoutinho/nextcloud-mcp-server))
exposes Nextcloud (notes, calendar, contacts, files, etc.) as MCP tools so Claude
clients can act on the live Nextcloud instance rather than just read docs about it.

## Architecture

```
Claude Code (local or cloud session)
  │  outbound HTTPS, MCP client (static BasicAuth headers)
  ▼
Ingress mcp.germany.vertesi.com (Traefik, letsencrypt-prod)
  ▼
nextcloud-mcp Deployment (cluster/helm/nextcloud-mcp-server/values.yaml) — talks to
germany.vertesi.com (cluster/services/nextcloud.yaml) using the credentials in
Secret nextcloud-claude-mcp
```

Single replica, SQLite token DB on `emptyDir` — no persistent user data of its own,
so this workload is stateless and low-risk to redeploy or roll back.

## Configuration

Values override: [`cluster/helm/nextcloud-mcp-server/values.yaml`](cluster/helm/nextcloud-mcp-server/values.yaml).
Auth mode is single-user BasicAuth (`auth.mode: basic`), pointed at the existing
Secret `nextcloud-claude-mcp` via `auth.basic.existingSecret` — the chart's own
default key names (`username`/`password`) don't match this Secret, so
`auth.basic.usernameKey`/`passwordKey` are overridden to `claude-user`/`claude-pass`
to match it.

The Secret itself is created out-of-band, never committed:

```sh
kubectl create secret generic nextcloud-claude-mcp \
  --from-literal=claude-user=<CHANGEME_nextcloud_username> \
  --from-literal=claude-pass=<CHANGEME_nextcloud_app_password> \
  -n default
```

Use a Nextcloud [app password](https://docs.nextcloud.com/server/latest/user_manual/en/session_management.html#managing-devices),
not the account's real login password.

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

claude.ai's web/mobile Connectors do **not** work against this deployment yet — the
Connectors UI always attempts MCP OAuth discovery/authorize, which 404s against this
BasicAuth-only server (no OAuth routes registered). Only Claude Code / other
static-header MCP clients work today; multi-user OAuth (Login Flow v2) is tracked in
a follow-up issue.
