# Collabora Online

CODE, deployed by ArgoCD from the upstream `collabora-online` chart. The chart pin and the
sources live in `cluster/argocd/apps/collabora.yaml`; `values.yaml` here is the override.
Manual sync, no prune, no self-heal.

The supporting objects are raw manifests in `cluster/services/collabora/`, applied by the same
Application as a second source: redis, the traefik IngressRoute and Middleware, and the
Certificate.

## Session stickiness

Users editing the same file have to reach the same backend. Three pieces do that:

- A traefik plugin that hashes an arbitrary request param into a cookie, defined in
  `cluster/traefik.yaml` and also dropped on the k3s master in
  `/var/lib/rancher/k3s/server/manifests`.
- An IngressRoute rather than an Ingress, because the plugin is wired through a Middleware
  and traefik is moving features away from Ingress annotations.
- redis as the shared store the plugin hashes into.

The IngressRoute uses the cookie that middleware sets as its stickiness key.

The Certificate is declared by hand because cert-manager does not watch IngressRoutes and so
issues nothing for them on its own.

## Admin credentials

The chart falls back to `admin` / `examplepass` when `collabora.existingSecret` is off, so this
deployment points it at a Secret created outside git:

```sh
kubectl create secret generic collabora-online-admin \
  --namespace collabora \
  --from-literal=username=admin \
  --from-literal=password=CHANGEME_COLLABORA_ADMIN_PASSWORD
```

The admin console is served at `/browser/dist/admin/admin.html` on
`collabora.germany.vertesi.com`, which the IngressRoute publishes to the internet. The password
is the only control in front of it.

## WOPI proof key

Every replica has to serve the same proof key, or discovery fetched from one pod fails
validation against a request served by another. The chart can generate one, but that path calls
`genPrivateKey` on each render and ArgoCD renders with `helm template`, so it would hand out a
new key on every sync. `collabora.proofKeysSecretRef` points at a Secret created out of band
instead:

```sh
openssl genrsa -out proof_key 4096
openssl rsa -in proof_key -pubout -out proof_key.pub
kubectl create secret generic collabora-online-wopi-proof \
  --namespace collabora \
  --from-file=proof_key --from-file=proof_key.pub
```

Both files are required. The Deployment mounts `proof_key.pub` by subPath whenever chart-side
generation is off, and a subPath naming a missing key leaves the pod unable to start.

## Nextcloud side

Nextcloud Office (`richdocuments`) holds its own config in the Nextcloud database, not in this
repo. Run inside the nextcloud pod, where occ is at `/www/nextcloud/occ`:

```sh
occ config:app:set richdocuments wopi_url --value="https://collabora.germany.vertesi.com"
occ config:app:set richdocuments public_wopi_url --value="https://collabora.germany.vertesi.com"
occ config:app:set richdocuments wopi_allowlist --value="10.42.0.0/16"
occ richdocuments:activate-config
```

`wopi_allowlist` names the hosts allowed to make WOPI calls back into Nextcloud, so it carries
the pod CIDR, not the Collabora hostname. `collabora.aliasgroups` in `values.yaml` is the
mirror image: the Nextcloud origin this server accepts documents from.
