#!/usr/bin/env bash
# Run all Monkeyble scenarios for rolling-upgrade.yaml.
# Requires: pip install monkeyble
# Run from cluster/ansible/ or any directory (script auto-cds).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANSIBLE_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INVENTORY="${SCRIPT_DIR}/inventory.yml"
STATE_DIR="/var/lib/ansible-upgrade"

cd "$ANSIBLE_DIR"

# Locate monkeyble callback_plugins directory
MONKEYBLE_CB_DIR="$(python3 - <<'EOF'
import os, monkeyble
pkg = os.path.dirname(os.path.abspath(monkeyble.__file__))
cb = os.path.join(pkg, "callback_plugins")
if os.path.isdir(cb):
    print(cb)
else:
    # Some installs put it under monkeyble/plugins/callback
    alt = os.path.join(pkg, "plugins", "callback")
    print(alt if os.path.isdir(alt) else cb)
EOF
)"

mkdir -p "$STATE_DIR"

run_scenario() {
  local name=$1
  local vars_file=$2
  shift 2
  local extra=("$@")

  echo ""
  echo "══════════════════════════════════════════════"
  echo "  Scenario: ${name}"
  echo "══════════════════════════════════════════════"

  ANSIBLE_CALLBACKS_ENABLED=monkeyble_callback \
  ANSIBLE_CALLBACK_PLUGINS="$MONKEYBLE_CB_DIR" \
    ansible-playbook \
      -i "$INVENTORY" \
      -e "@${vars_file}" \
      -e "monkeyble_scenario=${name}" \
      -e "k3s_token=ci-test-token" \
      -e "pushover_app_token=ci-fake-token" \
      -e "pushover_user_key=ci-fake-user" \
      "${extra[@]+"${extra[@]}"}" \
      rolling-upgrade.yaml

  echo "  PASSED: ${name}"
}

# ── Scenario 1: health check fails, rebuild succeeds → WARNING sent ──────────
rm -f "${STATE_DIR}/rolling-upgrade-failed"
run_scenario "agent_rescue_success" \
  "${SCRIPT_DIR}/test_agent_rescue_success.yml"

# ── Scenario 2: health check fails, rebuild also fails → CRITICAL sent ───────
rm -f "${STATE_DIR}/rolling-upgrade-failed"
run_scenario "agent_rescue_failure" \
  "${SCRIPT_DIR}/test_agent_rescue_failure.yml"

# ── Scenario 3: cross-play abort — agents failure flag stops multimasters ────
echo ""
echo "══════════════════════════════════════════════"
echo "  Scenario: cross_play_abort"
echo "══════════════════════════════════════════════"

touch "${STATE_DIR}/rolling-upgrade-failed"

if ansible-playbook \
    -i "$INVENTORY" \
    --limit multimasters \
    -e "strict_mode=true" \
    -e "k3s_token=ci-test-token" \
    -e "pushover_app_token=ci-fake-token" \
    -e "pushover_user_key=ci-fake-user" \
    rolling-upgrade.yaml 2>&1; then
  echo "  ERROR: expected playbook to abort but it succeeded"
  exit 1
fi

if [[ ! -f "${STATE_DIR}/rolling-upgrade-failed" ]]; then
  echo "  ERROR: failure flag was cleared but should persist"
  exit 1
fi

echo "  PASSED: cross_play_abort (play aborted, failure flag persists)"

# ── Cleanup ───────────────────────────────────────────────────────────────────
rm -f "${STATE_DIR}/rolling-upgrade-failed" \
      "${STATE_DIR}/maintenance-in-progress"

echo ""
echo "All Monkeyble scenarios passed."
