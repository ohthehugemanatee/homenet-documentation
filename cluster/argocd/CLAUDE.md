# cluster/argocd/CLAUDE.md — ArgoCD Application manifests

One Application manifest per managed workload in `apps/`. File names match the Application `metadata.name`: `<app-name>.yaml`.

## Conventions

- Every Application sets `metadata.namespace: argocd` explicitly.
- `spec.destination.namespace` matches the workload's actual namespace.
- **Auto-sync** (prune + self-heal): stable media and utility apps. These get `metadata.finalizers: [resources-finalizer.argocd.argoproj.io]` so removing the Application YAML cascade-deletes the resources.
- **Manual sync** (no prune, no self-heal): infrastructure and complex stateful apps (nextcloud, collabora). No finalizer — accidental Application deletion must not cascade-delete infrastructure.
- All manual-sync apps get `notifications.argoproj.io/subscribe.on-out-of-sync.pushover: ""` annotation.
- All auto-sync apps get `on-sync-failed` and `on-health-degraded` notification annotations.
- Helm-sourced Applications use multi-source when the values file lives in this git repo.

## Sync hooks (`hooks/`)

One directory per app under `hooks/<app>/`, built by kustomize. `hooks/longhorn/` is the first; #220 generalises the pattern into parameterized templates.

- **Every resource the hook Job needs is itself a hook.** ArgoCD applies plain resources in the main sync, which runs *after* `PreSync` — a ServiceAccount or ConfigMap left unannotated does not exist when the Job starts, and the first sync on a fresh cluster fails. Annotate prerequisites `hook: PreSync` at `sync-wave: "-2"` and the Job at `"-1"`.
- **`hook-delete-policy: BeforeHookCreation`**, not `HookSucceeded`: deleting on success throws away the log of the run that let an upgrade through.
- **`backoffLimit: 0`.** A gate that retries takes minutes to say no. A hook that reads cluster state fetches it with `kubectl` in an initContainer, so a throttled API server retries inside `kubectl` before the readiness check ever runs; the main container still fails once, on the first real blocker.
- **The fetch initContainer's image needs a shell.** `registry.k8s.io/kubectl` is distroless and cannot run `sh -c`; a Job built on it fails at container init before `kubectl` ever runs, with `backoffLimit: 0` turning that single start failure into a failed `PreSync` hook. Use an Alpine-based kubectl image (`alpine/kubectl`) instead.
- A script longer than a line goes on disk and reaches the Job through a `configMapGenerator`, so the file the unit tests import is the file the Job runs. `disableNameSuffixHash: true` because the Job names the ConfigMap.
- Hooks attach to an Application's manifests. For a Helm-sourced app, add the hook directory as another entry in `spec.sources`.

## Verification

```sh
yamllint cluster/argocd/
kubeconform -strict -ignore-missing-schemas cluster/argocd/
```

ArgoCD CRD schemas are needed for kubeconform; CI installs them in the k3d test cluster.
