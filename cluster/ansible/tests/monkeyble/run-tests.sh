#!/usr/bin/env bash
# Run all Monkeyble scenarios for rolling-upgrade.yaml.
# Requires: pip install monkeyble && ansible-galaxy collection install hpe.monkeyble
# Run from cluster/ansible/ or any directory (script auto-cds).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANSIBLE_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INVENTORY="${SCRIPT_DIR}/inventory.yml"
TEST_SECRETS="${SCRIPT_DIR}/test_secrets.yml"
STATE_DIR="$(mktemp -d)"
trap 'rm -rf "$STATE_DIR"' EXIT

cd "$ANSIBLE_DIR"

# Enable the hpe.monkeyble callback plugin (installed via ansible-galaxy collection)
export ANSIBLE_CALLBACKS_ENABLED=hpe.monkeyble.monkeyble_callback

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
    -e "state_dir=${STATE_DIR}" \
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

# --limit multimasters is intentional and required: the agents play pre_tasks
# unconditionally clear rolling-upgrade-failed at the start of every run.
# If agents ran first, the flag we just set would be wiped before multimasters
# could check it, defeating the test. Skipping agents entirely preserves the
# flag so the multimasters pre_task abort logic can be exercised.
#
# Disable monkeyble callback — this scenario tests Ansible logic, not task assertions.
scenario3_output=$(env -u ANSIBLE_CALLBACKS_ENABLED ansible-playbook \
    -i "$INVENTORY" \
    --limit multimasters \
    -e "strict_mode=true" \
    -e "vault_file=${TEST_SECRETS}" \
    -e "state_dir=${STATE_DIR}" \
    rolling-upgrade.yaml 2>&1) && {
  echo "  ERROR: expected playbook to abort but it succeeded"
  exit 1
}

if ! echo "$scenario3_output" | grep -q "previous play left nodes in a failed state"; then
  echo "  ERROR: playbook failed but not with the expected cross-play abort message"
  echo "$scenario3_output"
  exit 1
fi

if [[ ! -f "${STATE_DIR}/rolling-upgrade-failed" ]]; then
  echo "  ERROR: failure flag was cleared but should persist"
  exit 1
fi

echo "  PASSED: cross_play_abort (play aborted with expected message, failure flag persists)"

# ── Scenario 4: mint-remote-debug-token.yaml mints and prints a token ────────
# Monkeyble replaces the TokenRequest task's module+args entirely with its own
# mock, so the rendered kubectl command line is never observable here — what
# IS observable, and worth asserting, is that the mocked stdout actually flows
# through `register` into the final debug print.
echo ""
echo "══════════════════════════════════════════════"
echo "  Scenario: mint_remote_debug_token"
echo "══════════════════════════════════════════════"

mint_output=$(ansible-playbook \
    -i "$INVENTORY" \
    -e "@${SCRIPT_DIR}/test_mint_remote_debug_token.yml" \
    -e "monkeyble_scenario=mint_remote_debug_token" \
    mint-remote-debug-token.yaml 2>&1) || {
  echo "  ERROR: mint-remote-debug-token.yaml failed"
  echo "$mint_output"
  exit 1
}

echo "$mint_output"

if ! echo "$mint_output" | grep -q '"msg": "fake.debug.token"'; then
  echo "  ERROR: expected the minted token to be printed via the final debug task"
  exit 1
fi

echo "  PASSED: mint_remote_debug_token"

echo ""
echo "All Monkeyble scenarios passed."
