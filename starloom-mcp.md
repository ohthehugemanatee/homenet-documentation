# starloom-mcp: MCP access to StarLoom for Claude Code and Hermes

StarLoom's MCP endpoint is reachable from outside the LAN at
`https://stars-mcp.vertesi.com/mcp`, through the `homenet-k8s-debug` Cloudflare Tunnel
that also fronts kubernetes-mcp-server ([remote-debugging.md](remote-debugging.md)). Two
layers gate it: Cloudflare Access checks a Service Token at the edge, then StarLoom checks
its own API key.

```
Claude Code cloud session / Hermes
  │  HTTPS: CF-Access-Client-Id, CF-Access-Client-Secret, Authorization: Bearer
  ▼
Cloudflare edge: Access (Service Auth) → Tunnel → in-cluster cloudflared
  ▼
http://starloom.default.svc:8080/mcp   (cluster/services/starloom.yaml)
```

Neither `cluster/services/cloudflared.yaml` nor the StarLoom manifest carries any of this.
The route and the Access policy live in the Cloudflare dashboard.

## Shape of the route

- Path `^/mcp` only. cloudflared answers 404 for the web UI and the Connect API (`/api`).
  The Connect API accepts writes from read-only API keys, so it stays off the tunnel.
- The hostname is first-level because Universal SSL covers `vertesi.com` and
  `*.vertesi.com`, not `*.berlin.vertesi.com`. `stars.berlin.vertesi.com` is the LAN
  Ingress (Pi-hole record pointing at Traefik) and is not routed through the tunnel.
- The Service Token is dedicated to this hostname. The kubernetes-mcp-server token also
  unlocks `k8s-mcp.vertesi.com`, which reads pod logs for every workload, so it is not
  handed to a client that runs outside the cluster.

## One-time Cloudflare setup (operator-run)

1. Zero Trust dashboard → Tunnels → `homenet-k8s-debug` → Public hostnames → add
   `stars-mcp.vertesi.com`, path `^/mcp`, service type HTTP, URL `starloom.default.svc:8080`.
   HTTP, not HTTPS: the pod has no TLS listener.
2. Access → Service Auth → Service Tokens → create `starloom-mcp`. The Client ID and
   Secret are shown once.
3. Access → Applications → self-hosted app with one destination: type Public hostname,
   `stars-mcp.vertesi.com`, path empty. A Private destination covers WARP clients only and
   leaves the public hostname without an Access app. Policy action Service Auth, allowing
   only the `starloom-mcp` token.
4. StarLoom UI → create an API key for each client.

## Client configuration

Each client sends the same three headers on every request to the URL above.

| Header | Value |
|---|---|
| `CF-Access-Client-Id` | Service Token Client ID |
| `CF-Access-Client-Secret` | Service Token Client Secret |
| `Authorization` | `Bearer <StarLoom API key>` |

Claude Code: set the cloud environment's Network access to Custom with the Allowed
domains from remote-debugging.md ("Configuring the Claude Code environment") plus
`stars-mcp.vertesi.com`. Environment variables there are not a secrets store, so a key
stored in them should be read-only unless Claude needs the write tools.

Hermes: the same URL and headers in its MCP server entry.

## Verify

Run from outside the LAN. `ID`, `SECRET` and `KEY` are the Service Token pair and the
StarLoom API key.

```sh
H=https://stars-mcp.vertesi.com
CF=(-H "CF-Access-Client-Id: $ID" -H "CF-Access-Client-Secret: $SECRET")
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'

curl -s -o /dev/null -w '%{http_code}\n' "$H/mcp"                 # 403, Access
curl -s -o /dev/null -w '%{http_code}\n' "${CF[@]}" "$H/mcp"      # 401, StarLoom
curl -s -o /dev/null -w '%{http_code}\n' "${CF[@]}" -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d "$INIT" "$H/mcp"                                             # 200
curl -s -o /dev/null -w '%{http_code}\n' "${CF[@]}" -H "Authorization: Bearer $KEY" "$H/"  # 404, cloudflared
```

## Revoking access

Delete the public hostname (the route is gone at once), revoke the `starloom-mcp` Service
Token, and delete the API key in the StarLoom UI.
