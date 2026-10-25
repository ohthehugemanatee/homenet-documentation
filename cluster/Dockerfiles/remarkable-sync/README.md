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

- **New and re-saved tabs sync immediately**, via a `watchdog` filesystem watch on
  `TAB_DIR` (debounced by `WATCH_DEBOUNCE_SECONDS`, default 2s, to coalesce
  bursts and let SongHub finish writing). `SYNC_INTERVAL_SECONDS` (default
  1800) is now just a fallback poll in case an event is missed - relevant
  if `TAB_DIR` ever moves off a local/Longhorn volume onto NFS/CIFS, where
  inotify events aren't always reliable.
- **Resetting a permanently-failed tab.** A tab whose JSON parses but is
  missing the expected `tab.raw_tabs` field gets a `.failed` marker in
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
- **Re-saved tabs.** The `.synced` marker holds a sha256 of the text the
  PDF renders: `tab.raw_tabs_transposed` when SongHub saved a transposition,
  else `tab.raw_tabs`. A save that changes that text (new transposition,
  edited chords) re-uploads with
  `rmapi put --content-only`, which replaces the PDF of the existing
  document in place and keeps its annotations. Saves that leave it
  unchanged (A/F marks, a re-save with no edits) upload nothing. An empty
  marker from an older image is treated as synced unless the tab file is
  newer than the marker.
- **Forcing a re-sync after a rendering change.** Changes to `sync.py`'s
  PDF rendering do not change the digest, so tabs already on the tablet
  are not regenerated. Clear their markers the same way as `.failed` ones:
  ```
  kubectl exec -n default songhub-0 -c remarkable-sync -- \
    rm -f "/app/saved-tabs/.remarkable-sync-state/<filename>.ultimatetab.json.synced"
  ```
  or `rm -f /app/saved-tabs/.remarkable-sync-state/*.synced` to force
  everything to re-upload. Existing documents get their PDF replaced in
  place.
- **A green pod does not mean uploads are succeeding.** The readiness/
  liveness probes only check that the sync loop is alive (heartbeat file
  freshness), not that `rmapi put` is actually succeeding. A persistent
  auth failure (e.g. `rmapi.conf` expired) or reMarkable API outage will
  not fail the probes - the loop keeps iterating and touching the
  heartbeat even while every upload fails. Check `kubectl logs -n default
  songhub-0 -c remarkable-sync` to confirm tabs are actually landing on
  the tablet, don't rely on pod status alone.
