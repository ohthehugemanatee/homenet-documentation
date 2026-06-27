#!/usr/bin/env bash
# Unit tests for shoebox/scripts/check-control-plane.sh.
#
# Drives the watchdog with injected HTTP codes (WATCHDOG_PROBE_HTTP_CODE) and a
# stub notifier (WATCHDOG_NOTIFY_CMD) so no real network or Pushover call is
# made. Verifies the consecutive-failure threshold, single-fire-per-episode
# latch, recovery notification, and that "responding" codes count as up.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WATCHDOG="${SCRIPT_DIR}/../scripts/check-control-plane.sh"

failures=0
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

STATE_FILE="${workdir}/state"
LOG_FILE="${workdir}/log"
NOTIFY_LOG="${workdir}/notifications"

# Stub notifier: records "<status>|<title>" for each notification, one per line.
NOTIFY_STUB="${workdir}/notify-stub.sh"
cat >"$NOTIFY_STUB" <<'STUB'
#!/usr/bin/env bash
# args: $1=status (down|up)  $2=title  $3=message
printf '%s|%s\n' "$1" "$2" >>"$NOTIFY_LOG"
STUB
chmod +x "$NOTIFY_STUB"

# Run the watchdog once with an injected probe result.
# $1 = http code to inject
run_probe() {
  WATCHDOG_PROBE_HTTP_CODE="$1" \
  WATCHDOG_STATE_FILE="$STATE_FILE" \
  WATCHDOG_LOG_FILE="$LOG_FILE" \
  WATCHDOG_NOTIFY_CMD="$NOTIFY_STUB" \
  WATCHDOG_FAIL_THRESHOLD="3" \
  NOTIFY_LOG="$NOTIFY_LOG" \
    bash "$WATCHDOG" >/dev/null 2>&1
}

notify_count() {
  if [ -f "$NOTIFY_LOG" ]; then
    wc -l <"$NOTIFY_LOG" | tr -d ' '
  else
    echo 0
  fi
}

last_notify() {
  if [ -f "$NOTIFY_LOG" ]; then
    tail -n1 "$NOTIFY_LOG"
  else
    echo ""
  fi
}

assert_eq() {
  local desc=$1 expected=$2 actual=$3
  if [ "$expected" = "$actual" ]; then
    echo "  OK   $desc"
  else
    echo "  FAIL $desc (expected '$expected', got '$actual')"
    failures=$((failures + 1))
  fi
}

reset_state() {
  rm -f "$STATE_FILE" "$LOG_FILE" "$NOTIFY_LOG"
}

echo "Running check-control-plane tests..."

# ── Healthy: no notification ────────────────────────────────────────────────
reset_state
run_probe 200
assert_eq "200 healthy → no notification" "0" "$(notify_count)"

# ── 401/403 count as up (apiserver responding) ──────────────────────────────
reset_state
run_probe 401
assert_eq "401 (responding) → no notification" "0" "$(notify_count)"
run_probe 403
assert_eq "403 (responding) → still no notification" "0" "$(notify_count)"

# ── Below threshold: no alert yet ───────────────────────────────────────────
reset_state
run_probe 000
assert_eq "down 1/3 → no alert" "0" "$(notify_count)"
run_probe 000
assert_eq "down 2/3 → no alert" "0" "$(notify_count)"

# ── Reaching threshold: exactly one down alert ──────────────────────────────
run_probe 000
assert_eq "down 3/3 → one alert" "1" "$(notify_count)"
assert_eq "alert is a 'down' alert" "down" "$(last_notify | cut -d'|' -f1)"

# ── Still down past threshold: no repeat alert (single-fire latch) ──────────
run_probe 000
assert_eq "down 4 → still one alert (latched)" "1" "$(notify_count)"
run_probe 503
assert_eq "down via 503 → still one alert" "1" "$(notify_count)"

# ── Recovery: one 'up' notification ─────────────────────────────────────────
run_probe 200
assert_eq "recovery → second notification" "2" "$(notify_count)"
assert_eq "recovery is an 'up' alert" "up" "$(last_notify | cut -d'|' -f1)"

# ── After recovery, staying up sends nothing further ────────────────────────
run_probe 200
assert_eq "stable up after recovery → no new notification" "2" "$(notify_count)"

# ── A fresh down-episode alerts again ───────────────────────────────────────
run_probe 000
run_probe 000
run_probe 000
assert_eq "new down-episode → third notification" "3" "$(notify_count)"
assert_eq "new episode is a 'down' alert" "down" "$(last_notify | cut -d'|' -f1)"

# ── Timeout sentinel (000) without injection path also treated as down ──────
reset_state
run_probe 000
run_probe 000
run_probe 000
assert_eq "000 sentinel reaches threshold → alert" "1" "$(notify_count)"

echo ""
if [ "$failures" -eq 0 ]; then
  echo "All check-control-plane tests passed."
else
  echo "$failures test(s) failed."
  exit 1
fi
