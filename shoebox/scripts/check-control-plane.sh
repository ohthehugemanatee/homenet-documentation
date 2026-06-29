#!/usr/bin/env bash
# External control-plane watchdog for the homenet k3s cluster.
#
# Runs ON THE SHOEBOX HOST (outside the cluster) so it can alert even when the
# cluster — and therefore the in-cluster Prometheus/Alertmanager pipeline — is
# down. Probes the kube-apiserver VIP over HTTPS and pushes a Pushover alert
# after N consecutive failures, with a single alert per down-episode and a
# recovery notification when the API returns.
#
# Intended to be driven by a systemd timer (see shoebox-ansible-setup.yaml).
#
# Health endpoints /livez, /readyz, /healthz are anonymously accessible on the
# kube-apiserver, so this is a plain reachability probe — NOT kubectl (honours
# the shoebox "no kubectl in scripts" rule).
#
# Config (env vars, all optional — defaults target the homenet VIP):
#   WATCHDOG_PROBE_URL        default https://10.10.10.9:6443/livez
#   WATCHDOG_TIMEOUT          curl max time, seconds          (default 5)
#   WATCHDOG_FAIL_THRESHOLD   consecutive failures before alert (default 3)
#   WATCHDOG_STATE_FILE       default /var/lib/ansible-upgrade/control-plane-watchdog.state
#   WATCHDOG_LOG_FILE         default /var/log/ansible/control-plane-watchdog.log
#   WATCHDOG_PUSHOVER_ENV     default /etc/ansible/pushover.env (PUSHOVER_TOKEN/PUSHOVER_USER)
#
# Test/override hooks:
#   WATCHDOG_PROBE_HTTP_CODE  if set, skip curl and use this code (unit tests)
#   WATCHDOG_NOTIFY_CMD       if set, invoked as: <cmd> <status> <title> <message>
#                             instead of the built-in Pushover POST (unit tests)
set -euo pipefail

# State/log live under the shoebox host dirs provisioned by the bootstrap
# playbook: /var/lib/ansible-upgrade (state) and /var/log/ansible (logs).
PROBE_URL="${WATCHDOG_PROBE_URL:-https://10.10.10.9:6443/livez}"
TIMEOUT="${WATCHDOG_TIMEOUT:-5}"
FAIL_THRESHOLD="${WATCHDOG_FAIL_THRESHOLD:-3}"
STATE_FILE="${WATCHDOG_STATE_FILE:-/var/lib/ansible-upgrade/control-plane-watchdog.state}"
LOG_FILE="${WATCHDOG_LOG_FILE:-/var/log/ansible/control-plane-watchdog.log}"
PUSHOVER_ENV="${WATCHDOG_PUSHOVER_ENV:-/etc/ansible/pushover.env}"

mkdir -p "$(dirname "$STATE_FILE")" "$(dirname "$LOG_FILE")" 2>/dev/null || true

log() {
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >>"$LOG_FILE" 2>/dev/null || true
}

# Probe the API. Echoes an HTTP status code; "000" means no connection at all
# (refused/timeout/TLS failure) — the unambiguous "control plane down" signal.
probe() {
  if [ -n "${WATCHDOG_PROBE_HTTP_CODE:-}" ]; then
    printf '%s' "$WATCHDOG_PROBE_HTTP_CODE"
    return 0
  fi
  curl -k -s -o /dev/null \
    --connect-timeout "$TIMEOUT" --max-time "$TIMEOUT" \
    -w '%{http_code}' "$PROBE_URL" 2>/dev/null || printf '000'
}

# Up if the apiserver responds at all: 200 = healthy; 401/403 = process alive
# but anonymous auth disabled (still "up" for availability purposes).
is_up() {
  case "$1" in
    200 | 401 | 403) return 0 ;;
    *) return 1 ;;
  esac
}

# Deliver a notification. status=down|up. Uses WATCHDOG_NOTIFY_CMD if set
# (tests), else POSTs to Pushover with the host-provided credentials.
notify() {
  local status=$1 title=$2 message=$3
  if [ -n "${WATCHDOG_NOTIFY_CMD:-}" ]; then
    "$WATCHDOG_NOTIFY_CMD" "$status" "$title" "$message"
    return 0
  fi
  if [ ! -f "$PUSHOVER_ENV" ]; then
    log "ERROR cannot notify: $PUSHOVER_ENV missing"
    return 1
  fi
  # shellcheck source=/dev/null
  . "$PUSHOVER_ENV"
  local priority=0
  [ "$status" = "down" ] && priority=1
  curl -s --max-time 15 \
    --form-string "token=${PUSHOVER_TOKEN:-}" \
    --form-string "user=${PUSHOVER_USER:-}" \
    --form-string "title=${title}" \
    --form-string "message=${message}" \
    --form-string "priority=${priority}" \
    https://api.pushover.net/1/messages.json >/dev/null 2>&1 \
    || log "ERROR Pushover POST failed"
}

# ── Load prior state ────────────────────────────────────────────────────────
fail_count=0
alerted=0
if [ -f "$STATE_FILE" ]; then
  # shellcheck source=/dev/null
  . "$STATE_FILE"
fi
# Sanitise to integers in case the state file is corrupt.
case "$fail_count" in '' | *[!0-9]*) fail_count=0 ;; esac
case "$alerted" in '' | *[!0-9]*) alerted=0 ;; esac

# ── Probe and decide ────────────────────────────────────────────────────────
code="$(probe)"

if is_up "$code"; then
  if [ "$alerted" -eq 1 ]; then
    log "RECOVERED apiserver responding (HTTP $code)"
    notify up "k3s control plane RECOVERED" \
      "kube-apiserver at ${PROBE_URL} is responding again (HTTP ${code})."
  else
    log "OK apiserver healthy (HTTP $code)"
  fi
  fail_count=0
  alerted=0
else
  fail_count=$((fail_count + 1))
  log "FAIL apiserver unreachable (HTTP $code) — ${fail_count}/${FAIL_THRESHOLD}"
  if [ "$fail_count" -ge "$FAIL_THRESHOLD" ] && [ "$alerted" -eq 0 ]; then
    notify down "k3s control plane DOWN" \
      "kube-apiserver at ${PROBE_URL} failed ${fail_count} consecutive probes (last HTTP ${code})."
    alerted=1
    log "ALERTED control plane down"
  fi
fi

# ── Persist state ───────────────────────────────────────────────────────────
printf 'fail_count=%s\nalerted=%s\n' "$fail_count" "$alerted" >"$STATE_FILE"

exit 0
