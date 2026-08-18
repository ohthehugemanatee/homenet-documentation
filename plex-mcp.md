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
kubectl -n default port-forward svc/plex-mcp 3000:3000
claude mcp add --transport http plex http://127.0.0.1:3000/mcp
```

`GET /health` proves only that the process is up: `PLEX_TOKEN` is read per *session*, not
at boot, so a wrong token passes every probe and fails every `initialize`. Verify by
listing tools.

## No Ingress, on purpose

v1.4.1 authenticates nothing — `src/shared/transport.ts` has no token, origin or host
check — and `PLEX_ENABLE_MUTATIVE_OPS` (unset here) gates only the *Plex* write tools:
`radarr_add_movie`, `sonarr_add_series` and both `*_trigger_search` are callable
regardless. A public hostname would be an anonymous "queue any download" API, so this is
ClusterIP-only until an auth layer lands.

## Bumping the version

Upstream publishes to npm only, so `.github/workflows/build-plex-mcp-image.yaml` (manual
dispatch) builds upstream's own Dockerfile and pushes
`ghcr.io/ohthehugemanatee/plex-mcp-server`. Bump the workflow default and the manifest's
image tag together; on the first push, set the GHCR package public.

