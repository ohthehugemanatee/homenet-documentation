# ADR-0004: Cloud sessions reach the cluster over MCP

- **Status:** accepted
- **Date:** 2026-08-22

## Context

Read-only cluster access from a Claude Code cloud session first ran raw `kubectl`
through a local `cloudflared access tcp` forwarder to `$K8S_API_HOSTNAME`, set up by a
SessionStart hook that also wrote a kubeconfig. That meant a local process to start,
fail and debug in every session, and it needed a bearer token (`K8S_BEARER_TOKEN`) held
in Claude Code environment variables, which are not a secrets store.

## Decision

Sessions talk to an in-cluster `kubernetes-mcp-server` over outbound HTTPS via its own
Cloudflare hostname, with Access checking a Service Token at the edge (#145).
Nothing runs locally in the sandbox and the session holds no bearer token. The
forwarder is no longer set up automatically; the tunnel and Access policy behind it
stay in place as a manual fallback for the rare case raw `kubectl` is needed.

## Consequences

- `K8S_BEARER_TOKEN` is not consumed by anything in this repo. An environment that
  still sets it is ignoring it.
- `K8S_API_HOSTNAME` is needed only to rebuild the manual forwarder.
- Session reach is bounded by what the MCP server exposes plus the `view` ClusterRole
  bound to `claude-remote-debug`, not by what a kubeconfig allows.
