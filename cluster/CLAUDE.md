# cluster/CLAUDE.md — shared Kubernetes foundation

Loaded for every directory under `cluster/`. The root `CLAUDE.md` covers cross-cutting workflow + secrets + universal lint; this file adds Kubernetes-specific foundation that `services/`, `helm/`, `storage/`, and the thin K8s-resource dirs (`ConfigMaps/`, `jobs/`, `ingress-only/`, etc.) all rely on. `cluster/ansible/` inherits it as well; its content is largely K8s-irrelevant for OS-provisioning, which is the cost of not hoisting `cluster/ansible/` to root `/ansible/` in this PR.

## Manifest foundation

- **`metadata.namespace` is ALWAYS explicit** on every resource. Never rely on the default namespace.
- **Default resource requests** inherit from `cluster/default-limits-requests.yaml`; never omit `resources.requests`.
- **Priority classes** live in `cluster/priorityClasses/`.
- **Storage references** use the `pv-<workload>` / `pvc-<workload>` names from `cluster/storage/`; no inline `hostPath` except in `cluster/debugging/` where the existing pattern already uses it.

## K8s-specific linters

- `kubeconform` — gating; schema validation.
- `kube-score` — advisory; policy scoring. Read the output.
- `polaris` — advisory; best-practices audit. Read the output.
- `hadolint` (config `.hadolint.yaml`) — for any Dockerfile under `cluster/Dockerfiles/`.

New advisory findings need either a justified entry in `.github/agentic-review-exceptions.yaml` or a fix — not silent acceptance.

## K8s verification — run before commit when any manifest under `cluster/` changes

```sh
kubeconform -summary -strict -ignore-missing-schemas cluster/
kube-score score cluster/**/*.yaml
polaris audit --audit-path cluster/
hadolint $(git ls-files 'cluster/Dockerfiles/**')   # if any Dockerfile changed
```

**For a new workload**, extend `.github/workflows/test-cluster.yaml` with an apply + `kubectl wait --for=condition=Ready` step (test-first), then reproduce locally:

```sh
k3d cluster create homenet-test --config .github/k3d-config.yaml
# then re-run the workflow's apply/install steps; watch the wait pass
```
