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

- **New tabs sync immediately**, via a `watchdog` filesystem watch on
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
- **Forcing a re-sync after a rendering change.** A tab that already
  uploaded successfully gets a `.synced` marker and is never re-converted or
  re-uploaded, even if `sync.py`'s PDF rendering later changes (e.g. the
  raw_tabs-vs-htmlTab / portrait fix). To regenerate specific tabs already
  on the tablet, clear their markers the same way as `.failed` ones:
  ```
  kubectl exec -n default songhub-0 -c remarkable-sync -- \
    rm -f "/app/saved-tabs/.remarkable-sync-state/<filename>.ultimatetab.json.synced"
  ```
  or `rm -f /app/saved-tabs/.remarkable-sync-state/*.synced` to force
  everything to re-upload (creates duplicate documents on reMarkable Cloud
  next to the old ones - delete the stale copies there manually).
- **A green pod does not mean uploads are succeeding, by design.** The
  probes check that the sync loop is alive (heartbeat file freshness), not
  that `rmapi put` is succeeding. That is the contract: the container is
  healthy when it can process its queue, whether or not the items in the
  queue succeed. A persistent auth failure (`rmapi.conf` expired) or a
  reMarkable API outage keeps the loop iterating and the heartbeat fresh,
  and the pod stays 2/2 Running throughout.
- **`RemarkableSyncUploadsFailing` is what surfaces a failing upload.** A
  Loki ruler alert (`cluster/services/loki-rules-remarkable-sync.yaml`)
  fires to Pushover when the sidecar has logged upload failures and no
  successes for six hours. Alloy already ships this container's stdout to
  Loki, so the alert reads log lines the sync loop already writes - there
  is no exporter or scrape target involved.
- **The log wording is an interface.** That alert matches the literal
  strings `rmapi put` / `failed (exit` and `synced `. Rewording either log
  line without updating the rule disables the alert silently, leaving
  nothing to catch a stalled sync. `tests/test_upload_failure.py`
  asserts both strings so a reword fails CI instead.
- **A failing upload is always retried.** Unlike a malformed tab, an upload
  error writes no marker, so the tab is picked up again on the next cycle
  and a backlog drains by itself once the cause is fixed.
