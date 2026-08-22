#!/usr/bin/env bash
# Run all Monkeyble scenarios for rolling-upgrade.yaml and
# migrate-config-to-longhorn.yaml.
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

# _play <name> <playbook> <vars_file> [extra ansible-playbook args...]
# Echoes combined output; returns the playbook's exit status.
_play() {
  local name=$1 playbook=$2 vars_file=$3
  shift 3
  ansible-playbook \
    -i "$INVENTORY" \
    -e "@${vars_file}" \
    -e "monkeyble_scenario=${name}" \
    -e "vault_file=${TEST_SECRETS}" \
    -e "state_dir=${STATE_DIR}" \
    "$@" \
    "$playbook" 2>&1
}

banner() {
  echo ""
  echo "══════════════════════════════════════════════"
  echo "  Scenario: $1"
  echo "══════════════════════════════════════════════"
}

# run_scenario <name> <playbook> <vars_file> [extra args...]
run_scenario() {
  banner "$1"
  local output
  output=$(_play "$@") || {
    echo "$output"
    echo "  ERROR: expected $1 to pass"
    exit 1
  }
  echo "$output"
  echo "  PASSED: $1"
}

# Runs a scenario that must pass, and proves it did the thing under test rather
# than merely exiting 0. Needed for two cases: a scenario whose subject is a task
# marked `should_fail` (monkeyble treats the expected failure as a pass, so the
# playbook still exits 0), and any scenario whose assertions would pass vacuously
# if the tasks never ran at all.
# run_scenario_expecting <name> <playbook> <vars_file> <expected regex> [extra args...]
run_scenario_expecting() {
  local name=$1 playbook=$2 vars_file=$3 expected=$4
  shift 4
  banner "$name"
  local output
  output=$(_play "$name" "$playbook" "$vars_file" "$@") || {
    echo "$output"
    echo "  ERROR: expected ${name} to pass"
    exit 1
  }
  echo "$output"
  if ! grep -Eq "$expected" <<<"$output"; then
    echo "  ERROR: ${name} passed, but the expected evidence is missing: ${expected}"
    exit 1
  fi
  echo "  PASSED: ${name}"
}

# Same, but the playbook must fail AND its output must match the regex. A bare
# non-zero exit would also be produced by a typo in the scenario file, so the
# message is what distinguishes "refused for the right reason".
# run_failing_scenario <name> <playbook> <vars_file> <expected regex> [extra args...]
run_failing_scenario() {
  local name=$1 playbook=$2 vars_file=$3 expected=$4
  shift 4
  banner "${name} (expected to fail)"
  local output
  output=$(_play "$name" "$playbook" "$vars_file" "$@") && {
    echo "$output"
    echo "  ERROR: expected ${name} to fail but it succeeded"
    exit 1
  }
  if ! grep -Eq "$expected" <<<"$output"; then
    echo "$output"
    echo "  ERROR: ${name} failed, but not with the expected message: ${expected}"
    exit 1
  fi
  echo "  PASSED: ${name}"
}

# ── Scenario 1: health check fails, rebuild succeeds → WARNING sent ──────────
rm -f "${STATE_DIR}/rolling-upgrade-failed"
run_scenario "agent_rescue_success" \
  rolling-upgrade.yaml \
  "${SCRIPT_DIR}/test_agent_rescue_success.yml" \
  "--limit" "agents"

# ── Scenario 2: health check fails, rebuild also fails → CRITICAL sent ───────
rm -f "${STATE_DIR}/rolling-upgrade-failed"
run_scenario "agent_rescue_failure" \
  rolling-upgrade.yaml \
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

# ── Scenario 4: stage the ombi cutover end to end ───────────────────────────
# ombi already carries the migrated shape, so the preflight parses a real
# manifest and the scenario pins cluster/services/ombi.yaml alongside the
# playbook. state_dir is the temp dir, so the saved sync policy lands there.
run_scenario "migrate_stage_success" \
  migrate-config-to-longhorn.yaml \
  "${SCRIPT_DIR}/test_migrate_stage_success.yml" \
  "-e" "app=ombi" "-t" "stage"

# The saved policy is the contract between stage and resume: resume restores
# exactly what was suspended, so an unreadable file must not be silently ignored.
POLICY_FILE="${STATE_DIR}/migrate-ombi-syncpolicy.json"
if [[ ! -f "$POLICY_FILE" ]]; then
  echo "  ERROR: stage did not save the ArgoCD sync policy to ${POLICY_FILE}"
  exit 1
fi
python3 -c "
import json, sys
policy = json.load(open('${POLICY_FILE}'))
assert policy['automated'] == {'prune': True, 'selfHeal': True}, policy
" || { echo '  ERROR: saved sync policy is not the one the Application had'; exit 1; }
echo "  PASSED: stage saved the ArgoCD sync policy verbatim"

# ── Scenario 5: the copy helper pod fails → play fails, pod still cleaned up ──
run_failing_scenario "migrate_stage_copy_failure" \
  migrate-config-to-longhorn.yaml \
  "${SCRIPT_DIR}/test_migrate_stage_copy_failure.yml" \
  "No space left on device" \
  "-e" "app=ombi" "-t" "stage"

# ── Scenarios 6-8: resume and rollback ──────────────────────────────────────
# stage writes the saved policy; these read it back. Write it here rather than
# depending on scenario 4 having run, so each scenario stands alone.
cat > "${STATE_DIR}/migrate-ombi-syncpolicy.json" <<'JSON'
{
    "automated": {
        "prune": true,
        "selfHeal": true
    }
}
JSON

run_scenario_expecting "migrate_resume_success" \
  migrate-config-to-longhorn.yaml \
  "${SCRIPT_DIR}/test_migrate_resume_success.yml" \
  "ombi is live on ombi-config-ombi-0" \
  "-e" "app=ombi" "-t" "resume"

# The post-check is the last thing standing between a mis-adopted PVC and an app
# live on NFS, so prove it fires rather than trusting that it would. The scenario
# marks the assert `should_fail`, which monkeyble scores as a pass, so the exit
# code proves nothing here — the failure message is the evidence.
run_scenario_expecting "migrate_resume_still_on_nfs" \
  migrate-config-to-longhorn.yaml \
  "${SCRIPT_DIR}/test_migrate_resume_still_on_nfs.yml" \
  "/config resolves to PVC 'app-configs', expected 'ombi-config-ombi-0'" \
  "-e" "app=ombi" "-t" "resume"

run_scenario "migrate_rollback" \
  migrate-config-to-longhorn.yaml \
  "${SCRIPT_DIR}/test_migrate_rollback.yml" \
  "-e" "app=ombi" "-t" "rollback"

echo ""
echo "All Monkeyble scenarios passed."
