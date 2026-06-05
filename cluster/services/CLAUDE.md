# cluster/services/CLAUDE.md — application workloads

Raw Kubernetes YAML (not Helm). Foundation (namespace, resource requests, storage refs, K8s linters + verification) lives in `cluster/CLAUDE.md` and is not restated here.

## Conventions

- Multi-resource files are normal.
- Naming: lowercase kebab-case.
- `Service.spec.selector` must match `Deployment.spec.template.metadata.labels`. Mismatches silently break routing.
- Per-service subdirectory when a service has >2 resources (see `octoprint/`, `unifi/`); flat single file otherwise.

## Health probes — REQUIRED on every container

**YOU MUST** declare `readinessProbe` AND `livenessProbe` on every container of every `Deployment` / `StatefulSet` / `DaemonSet`. Add `startupProbe` when boot can exceed 10s.

- HTTP services → `httpGet` against a **real** health endpoint, not `/`. Use `/healthz`, `/ready`, `/api/health`, or whatever the upstream image actually exposes.
- TCP-only services → `tcpSocket` on the real listening port.
- Non-network workloads → meaningful `exec` (e.g., `pgrep -f <daemon>`, `test -f /run/<lockfile>`).
- **No-op probes are NOT acceptable**: never `exec: ["true"]`, never a script that always returns 0, never a probe that hits a static asset.

Tune `initialDelaySeconds`, `periodSeconds`, `failureThreshold` to the actual workload — copy-pasted defaults are not tuning. Add a one-line comment explaining any non-obvious choice (e.g., `# slow JVM startup, 90s grace`).

## When a probe genuinely can't be added

Document why in the spec (e.g., closed-source binary with no health surface). Get explicit operator sign-off in the PR before merging. Do not work around it by adding a no-op probe — declare its absence explicitly with a comment in the manifest.
