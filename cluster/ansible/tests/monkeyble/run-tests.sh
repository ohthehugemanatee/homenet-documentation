#!/usr/bin/env bash
# Run all Monkeyble scenarios for rolling-upgrade.yaml.
# Requires: pip install monkeyble && ansible-galaxy collection install hpe.monkeyble
# Run from cluster/ansible/ or any directory (script auto-cds).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANSIBLE_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INVENTORY="${SCRIPT_DIR}/inventory.yml"
TEST_SECRETS="${SCRIPT_DIR}/test_secrets.yml"
STATE_DIR="/var/lib/ansible-upgrade"

cd "$ANSIBLE_DIR"

# Enable the hpe.monkeyble callback plugin (installed via ansible-galaxy collection)
export ANSIBLE_CALLBACKS_ENABLED=hpe.monkeyble.monkeyble_callback

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

  ansible-playbook \
    -i "$INVENTORY" \
    -e "@${vars_file}" \
    -e "monkeyble_scenario=${name}" \
    -e "vault_file=${TEST_SECRETS}" \
    "${extra[@]+"${extra[@]}"}" \
    rolling-upgrade.yaml

  echo "  PASSED: ${name}"
}

# ── Scenario 1: health check fails, rebuild succeeds → WARNING sent ──────────
rm -f "${STATE_DIR}/rolling-upgrade-failed"
run_scenario "agent_rescue_success" \
  "${SCRIPT_DIR}/test_agent_rescue_success.yml" \
  "--limit" "agents"

# ── Scenario 2: health check fails, rebuild also fails → CRITICAL sent ───────
rm -f "${STATE_DIR}/rolling-upgrade-failed"
run_scenario "agent_rescue_failure" \
  "${SCRIPT_DIR}/test_agent_rescue_failure.yml" \
  "--limit" "agents"

# ── Scenario 3: cross-play abort — agents failure flag stops multimasters ────
echo ""
echo "══════════════════════════════════════════════"
echo "  Scenario: cross_play_abort"
echo "══════════════════════════════════════════════"

touch "${STATE_DIR}/rolling-upgrade-failed"

# Disable monkeyble callback — this scenario tests Ansible logic, not task assertions.
if env -u ANSIBLE_CALLBACKS_ENABLED ansible-playbook \
    -i "$INVENTORY" \
    --limit multimasters \
    -e "strict_mode=true" \
    -e "vault_file=${TEST_SECRETS}" \
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
