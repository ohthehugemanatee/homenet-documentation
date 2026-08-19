# plex-mcp — MCP access to Plex, Radarr and Sonarr

[niavasha/plex-mcp-server](https://github.com/niavasha/plex-mcp-server) (MIT) at `v1.4.1`,
exposing the media stack to Claude clients: ~20 Plex tools (libraries, search, watch
history, sessions), 8 `sonarr_*` and 8 `radarr_*` (series/movie lists, queue, calendar,
quality profiles, add, trigger search). Trakt tools are listed but unconfigured.
[`cluster/services/plex-mcp.yaml`](cluster/services/plex-mcp.yaml) deploys it in
`default`, reaching `plex`, `sonarr` and `radarr` over Service DNS.

## Credentials — created out-of-band, never committed

```sh
kubectl create secret generic plex-mcp-credentials \
  --from-literal=plex-token=<CHANGEME_plex_token> \
  --from-literal=sonarr-api-key=<CHANGEME_sonarr_api_key> \
  --from-literal=radarr-api-key=<CHANGEME_radarr_api_key> \
  -n default
```

`plex-token`: Plex web UI → any item → ⋯ → Get Info → View XML, then read `X-Plex-Token`
from the URL. API keys: each app's Settings → General → API Key.

## Connecting a client

```sh
claude mcp add --transport http plex https://plex-mcp.germany.vertesi.com/mcp \
  --header "Authorization: Basic $(printf '<user>:<password>' | base64)"
```

In-cluster, unauthenticated, when the edge is not what you're testing:

```sh
kubectl -n default port-forward svc/plex-mcp 3000:3000
claude mcp add --transport http plex-local http://127.0.0.1:3000/mcp
```

`GET /health` proves only that the process is up: `PLEX_TOKEN` is read per *session*, not
at boot, so a wrong token passes every probe and fails every `initialize`. Verify by
listing tools.

## Basic auth is the whole gate

v1.4.1 authenticates nothing — `src/shared/transport.ts` has no token, origin or host
check — and `PLEX_ENABLE_MUTATIVE_OPS` (unset here) gates only the *Plex* write tools:
`radarr_add_movie`, `sonarr_add_series` and both `*_trigger_search` stay callable. So the
Traefik `basicAuth` middleware in front of the Ingress is the only thing between the
public hostname and a "queue any download" API. Pick the password accordingly. A
`rateLimit` middleware (60/min per source IP, burst 30) runs ahead of it as a
brute-force brake — it is a speed bump, not a second gate.

```sh
htpasswd -nbB <user> <CHANGEME_password> \
  | kubectl create secret generic plex-mcp-basicauth --from-file=users=/dev/stdin -n default
```

Removing the `router.middlewares` annotation, or renaming that Secret, silently removes
the gate — `test-cluster.yaml` asserts a `401` through Traefik for exactly that reason.

The claude.ai Connectors UI cannot send an `Authorization: Basic` header, so this
endpoint serves clients that can (Claude Code, scripts) — the same split as
`mcp2.germany.vertesi.com` in [nextcloud-mcp.md](nextcloud-mcp.md).

No DNS step: `*.germany.vertesi.com` already resolves to the home IP that
[`cluster/services/cloudflare-ddns.yaml`](cluster/services/cloudflare-ddns.yaml) keeps
current. cert-manager's HTTP-01 solver gets its own Ingress for the challenge path, so
the middleware does not block issuance.

## Bumping the version

Upstream publishes to npm only, so `.github/workflows/build-plex-mcp-image.yaml` (manual
dispatch) builds upstream's own Dockerfile and pushes
`ghcr.io/ohthehugemanatee/plex-mcp-server`. Bump the workflow default and the manifest's
image tag together; on the first push, set the GHCR package public.

