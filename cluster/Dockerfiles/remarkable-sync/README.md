# remarkable-sync

Sidecar image for `cluster/services/songhub.yaml`: converts SongHub's saved
`*.ultimatetab.json` tabs to PDF and pushes them to reMarkable Cloud via
`rmapi`. See `sync.py` for the loop and `songhub.yaml` for how it's wired in.

## First-time setup (manual, not automatable)

1. **rmapi pairing.** Visit my.remarkable.com/connect/remarkable for a
   one-time code, then run `rmapi` once interactively (any machine) to mint
   its config file. Create the secret from it:
   ```
   kubectl create secret generic remarkable-rmapi-token \
     --from-file=rmapi.conf=<path-to-minted-config> \
     -n default
   ```
   (Full command also documented as a comment on the Secret volume in
   `songhub.yaml`.)

2. **GHCR package visibility.** The first push of
   `ghcr.io/ohthehugemanatee/remarkable-sync` via
   `.github/workflows/build-remarkable-sync-image.yaml` defaults to a
   private package. Set it public in GitHub package settings, or add an
   `imagePullSecret` to the `remarkable-sync` container in `songhub.yaml` -
   otherwise the pod sits in `ImagePullBackOff`.

## Operating notes

- **Resetting a permanently-failed tab.** A tab whose JSON parses but is
  missing the expected `tab.htmlTab` field gets a `.failed` marker in
  `.remarkable-sync-state/` (on the shared `songhub-saved-tabs` volume) and
  is never retried. If a tab was misclassified, or SongHub's export format
  changes and old failures should be re-attempted after a fix, clear the
  markers from inside the pod:
  ```
  kubectl exec -n default songhub-0 -c remarkable-sync -- \
    rm -f /app/saved-tabs/.remarkable-sync-state/*.failed
  ```
- Invalid JSON (as opposed to valid-but-wrong-shaped JSON) is treated as
  transient - no `.failed` marker, keeps retrying - since it can happen if
  the sidecar reads a file mid-write by SongHub.
- **A green pod does not mean uploads are succeeding.** The readiness/
  liveness probes only check that the sync loop is alive (heartbeat file
  freshness), not that `rmapi put` is actually succeeding. A persistent
  auth failure (e.g. `rmapi.conf` expired) or reMarkable API outage will
  not fail the probes - the loop keeps iterating and touching the
  heartbeat even while every upload fails. Check `kubectl logs -n default
  songhub-0 -c remarkable-sync` to confirm tabs are actually landing on
  the tablet, don't rely on pod status alone.
