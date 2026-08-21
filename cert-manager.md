# cert-manager — TLS issuance for the cluster

cert-manager issues and renews every TLS certificate the cluster serves, via
Let's Encrypt. It runs from the upstream chart
([charts.jetstack.io](https://charts.jetstack.io)) under ArgoCD, with our values in
[`cluster/helm/cert-manager/values.yaml`](cluster/helm/cert-manager/values.yaml).

## Architecture

```
Ingress with cert-manager.io/cluster-issuer: letsencrypt-prod
  │  ingress-shim reads the annotation, creates a Certificate
  ▼
Certificate → CertificateRequest → Order → Challenge
  │  solver chosen by ClusterIssuer selector
  ▼
DNS-01 via Cloudflare API (token in Secret cloudflare-ddns)
  │  writes _acme-challenge TXT under the zone
  ▼
Let's Encrypt validates, cert lands in the Ingress's TLS Secret
  ▼
Traefik serves it
```

The `letsencrypt-prod` ClusterIssuer
([`cluster/services/letsencrypt-issuer-prod.yaml`](cluster/services/letsencrypt-issuer-prod.yaml))
declares two solvers: an HTTP-01 catch-all and a Cloudflare DNS-01 solver selected
on `dnsZones: [vertesi.com]`. cert-manager picks the most specific match, so in
practice **every `vertesi.com` name goes through DNS-01** — the HTTP-01 solver only
covers hosts outside that zone. The ACME account key lives in the `letsencrypt-prod`
Secret in the `cert-manager` namespace.

The ClusterIssuer is applied by hand and is **not** managed by ArgoCD. It has to be
re-applied after anything that deletes the CRDs.

## Sync tier

Manual-sync, no finalizer, no prune, no self-heal —
[Tier C in #206](https://github.com/ohthehugemanatee/homenet-documentation/issues/206):
low change frequency, high blast radius, not worth pipeline investment. Drift raises
an `on-out-of-sync` Pushover alert and waits for an operator.

Once Renovate lands (#226) it will open PRs against the `targetRevision` pin in
[`cluster/argocd/apps/cert-manager.yaml`](cluster/argocd/apps/cert-manager.yaml).
Tier C is PR-only forever — never auto-merged — and merging still only changes git.
A bump reaches the cluster only after a manual ArgoCD Sync.

The chart owns the CRDs (`crds.enabled: true`) with `crds.keep: true`, so removing
the release cannot take the CRDs — and every Certificate, Order, Challenge and
ClusterIssuer with them — out of the cluster.

## Upgrade policy

**cert-manager does not support skipping minor versions in place.** Each bump must
land one minor at a time, on the latest patch of that minor, reading the release
notes for each. Renovate will happily offer a jump across several minors; do not
take it.

If the installation has drifted far enough that sequential hops are impractical,
the supported escape hatch is a full teardown and reinstall — see below. That is
how this installation got to v1.20.0 from v1.7.2.

## Verify

```sh
kubectl -n cert-manager get pods
kubectl get clusterissuer letsencrypt-prod \
  -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'   # True
kubectl get certificate -A          # every entry READY=True
kubectl get challenge -A            # empty in steady state
```

A Challenge that lingers for more than a few minutes is the thing to look at. Read
its `status.reason` — it carries the solver's own error verbatim.

## Teardown and reinstall

Needed only for a multi-major jump. Roughly 15 minutes; **serving traffic is not
interrupted** — Traefik keeps serving the TLS Secrets already on disk. Only issuance
and renewal pause.

What survives, and why this is safe:

- **Issued TLS Secrets.** cert-manager sets no owner references on them unless
  `--enable-certificate-owner-ref` is passed, which this cluster does not use.
  Deleting Certificates does not delete their Secrets.
- **The ACME account key**, as long as the `cert-manager` namespace itself is left
  in place. Losing it is recoverable — a new account registers automatically — but
  it discards the existing account and its rate-limit standing.

What does not survive: every `Certificate`, `CertificateRequest`, `Order`,
`Challenge` and `ClusterIssuer`, because deleting a CRD deletes its objects.
ingress-shim rebuilds the Certificates from Ingress annotations; the ClusterIssuer
is re-applied by hand.

```sh
# 1. Back up the ACME account key and the issued certs, in case of surprises.
kubectl -n cert-manager get secret letsencrypt-prod -o yaml > /tmp/acme-account.yaml
kubectl get secret -A -o yaml \
  --field-selector type=kubernetes.io/tls > /tmp/tls-secrets.yaml

# 2. Confirm the assumption this procedure rests on — expect no output.
kubectl -n cert-manager get deploy cert-manager \
  -o jsonpath='{.spec.template.spec.containers[0].args}' \
  | tr ',' '\n' | grep enable-certificate-owner-ref

# 3. Tear down the old install. Namespace is deliberately NOT deleted (step 1's
#    account key lives in it). Leaves the TLS Secrets untouched.
kubectl -n cert-manager delete deploy,svc,sa cert-manager cert-manager-webhook cert-manager-cainjector
kubectl delete crd \
  certificates.cert-manager.io \
  certificaterequests.cert-manager.io \
  issuers.cert-manager.io \
  clusterissuers.cert-manager.io \
  orders.acme.cert-manager.io \
  challenges.acme.cert-manager.io
kubectl delete mutatingwebhookconfiguration cert-manager-webhook
kubectl delete validatingwebhookconfiguration cert-manager-webhook

# 4. Install the chart. The root app-of-apps registers the Application from git;
#    it is manual-sync, so trigger the first sync explicitly.
argocd app sync cert-manager
kubectl -n cert-manager rollout status deploy/cert-manager-webhook --timeout=180s

# 5. Re-apply the ClusterIssuer — it went with the CRDs and nothing in GitOps
#    recreates it.
kubectl apply -f cluster/services/letsencrypt-issuer-prod.yaml

# 6. Watch ingress-shim rebuild the Certificates.
kubectl get certificate -A -w
```

Expect re-issuance for any name whose Secret was lost or has expired. Let's Encrypt
allows 50 certificates per registered domain per week, so a full rebuild of this
cluster's handful of certs is not close to the limit.

**Rollback:** re-apply the previous version's manifests and restore
`/tmp/acme-account.yaml`. Because the TLS Secrets are never touched, a failed
reinstall costs issuance downtime — not a TLS outage — for as long as the existing
certs remain valid.

## History

Until August 2026 cert-manager was a vendored upstream manifest at
`cluster/services/cert-manager.yaml`, pinned to v1.1.0 and — because nothing ever
applied it — four years out of step with the v1.7.2 the cluster actually ran
(installed by hand in March 2022).

v1.7.2's Cloudflare solver built its stale-record cleanup URL from a per-record
`zone_id` field that Cloudflare's API stopped returning, emitting
`DELETE /zones//dns_records/<id>` and failing with
`7003: Could not route to /client/v4/zones/dns_records/...`. Renewals for any name
with a leftover `_acme-challenge` TXT record — that is, any name issued before —
stuck permanently, retrying on cert-manager's 30-minute backoff cap forever.
Brand-new names were unaffected, having no stale record to delete, which is why the
breakage stayed invisible until `mcp.germany.vertesi.com` expired on 13 August 2026.
