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

# test-tls-cert.yaml lives under tests/monkeyble/, not ANSIBLE_DIR, so the
# default playbook-relative role search misses roles/tls_cert.
export ANSIBLE_ROLES_PATH="${ANSIBLE_DIR}/roles"

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
# Every expected regex must match, except one prefixed '!', which must not.
# Regexes are the arguments before the first one starting with '-'; the rest are
# passed through to ansible-playbook.
# run_scenario_expecting <name> <playbook> <vars_file> <expected regex>... [extra args...]
run_scenario_expecting() {
  local name=$1 playbook=$2 vars_file=$3
  shift 3
  local -a expected_patterns=()
  while [ $# -gt 0 ] && [[ $1 != -* ]]; do
    expected_patterns+=("$1")
    shift
  done
  banner "$name"
  local output
  output=$(_play "$name" "$playbook" "$vars_file" "$@") || {
    echo "$output"
    echo "  ERROR: expected ${name} to pass"
    exit 1
  }
  echo "$output"
  local pattern
  for pattern in "${expected_patterns[@]}"; do
    if [[ $pattern == '!'* ]]; then
      if grep -Eq "${pattern#!}" <<<"$output"; then
        echo "  ERROR: ${name} passed, but forbidden evidence is present: ${pattern#!}"
        exit 1
      fi
    elif ! grep -Eq "$pattern" <<<"$output"; then
      echo "  ERROR: ${name} passed, but the expected evidence is missing: ${pattern}"
      exit 1
    fi
  done
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

# ── Scenario 0: k3s-agent.yaml mounts the USB disk with its detected fstype ──
run_scenario_expecting "k3s_agent_fstype_detection" \
  k3s-agent.yaml \
  "${SCRIPT_DIR}/test_k3s_agent_fstype_detection.yml" \
  "TASK \[Mount USB disk and persist in fstab\]" \
  "-e" "@${SCRIPT_DIR}/monkeyble_shared_tasks.yml" \
  "-e" "usb_disk=/dev/sda1" \
  "--limit" "agents"

# ── Scenario 1: health check fails, rebuild succeeds → WARNING sent ──────────
rm -f "${STATE_DIR}/rolling-upgrade-failed"
run_scenario_expecting "agent_rescue_success" \
  rolling-upgrade.yaml \
  "${SCRIPT_DIR}/test_agent_rescue_success.yml" \
  "TASK \[upgrade_rescue_agent : Alert WARNING" \
  "Rebuilding on k3s v1\.31\.5\+k3s1" \
  "-e" "@${SCRIPT_DIR}/monkeyble_shared_tasks.yml" \
  "--limit" "agents"

# ── Scenario 2: health check fails, rebuild also fails → CRITICAL sent ───────
rm -f "${STATE_DIR}/rolling-upgrade-failed"
run_scenario_expecting "agent_rescue_failure" \
  rolling-upgrade.yaml \
  "${SCRIPT_DIR}/test_agent_rescue_failure.yml" \
  "TASK \[upgrade_rescue_agent : Alert CRITICAL" \
  "TASK \[upgrade_rescue_agent : Report k3s-agent state\]" \
  "Active: failed \(Result: exit-code\)" \
  "Rebuilding on k3s v1\.31\.5\+k3s1" \
  "-e" "@${SCRIPT_DIR}/monkeyble_shared_tasks.yml" \
  "--limit" "agents"

# ── Scenario 2c: servers disagree on k3s version → refuse before teardown ───
rm -f "${STATE_DIR}/rolling-upgrade-failed"
run_scenario_expecting "agent_rescue_version_split" \
  rolling-upgrade.yaml \
  "${SCRIPT_DIR}/test_agent_rescue_version_split.yml" \
  "Refusing to guess which version the rebuilt agent should join" \
  "TASK \[upgrade_rescue_agent : Alert CRITICAL" \
  "!TASK \[upgrade_rescue_agent : Uninstall k3s agent\]" \
  "-e" "@${SCRIPT_DIR}/monkeyble_shared_tasks.yml" \
  "--limit" "agents"

# ── Scenario 2b: health check passes first try → k3s_health's own restore runs ──
rm -f "${STATE_DIR}/rolling-upgrade-failed"
run_scenario_expecting "agent_upgrade_success" \
  rolling-upgrade.yaml \
  "${SCRIPT_DIR}/test_agent_upgrade_success.yml" \
  "TASK \[cordon_drain : Clear pre-drain annotations after restore\]" \
  "-e" "@${SCRIPT_DIR}/monkeyble_shared_tasks.yml" \
  "--limit" "agents"

# ── Scenario 2e: nothing pending → upgrade_check skips cordon/drain entirely ──
rm -f "${STATE_DIR}/rolling-upgrade-failed"
run_scenario "agent_upgrade_skipped" \
  rolling-upgrade.yaml \
  "${SCRIPT_DIR}/test_agent_upgrade_skipped.yml" \
  "--limit" "agents"

# ── Scenario 2d: operator-owned workload → scale down the owning CR ─────────
rm -f "${STATE_DIR}/rolling-upgrade-failed"
run_scenario_expecting "cordon_drain_scaledown_owner" \
  rolling-upgrade.yaml \
  "${SCRIPT_DIR}/test_cordon_drain_scaledown_owner.yml" \
  "TASK \[cordon_drain : Read the pre-drain replica count from that object\]" \
  "-e" "@${SCRIPT_DIR}/monkeyble_shared_tasks.yml" \
  "--limit" "agents"

# ── Scenario 2c: operator-owned workload → restore the owning CR ────────────
rm -f "${STATE_DIR}/rolling-upgrade-failed"
run_scenario_expecting "cordon_drain_restore_owner" \
  rolling-upgrade.yaml \
  "${SCRIPT_DIR}/test_cordon_drain_restore_owner.yml" \
  "TASK \[cordon_drain : Resolve the object to restore\]" \
  "-e" "@${SCRIPT_DIR}/monkeyble_shared_tasks.yml" \
  "--limit" "agents"

# ── Scenario 2d: failure before health checks → no rebuild, k3s left alone ──
rm -f "${STATE_DIR}/rolling-upgrade-failed"
run_scenario_expecting "agent_pre_health_failure" \
  rolling-upgrade.yaml \
  "${SCRIPT_DIR}/test_agent_pre_health_failure.yml" \
  "TASK \[upgrade_rescue_agent : Uncordon node after pre-health failure\]" \
  "TASK \[cordon_drain : Scale StatefulSet back to pre-drain replica count\]" \
  "TASK \[upgrade_rescue_agent : Alert CRITICAL — upgrade failed before health checks\]" \
  "--limit" "agents"

# ── Scenario 2f: volume on the node still degraded → refuse before the cordon ──
# The wait bound is two seconds here; the default would hold CI for fifteen minutes.
rm -f "${STATE_DIR}/rolling-upgrade-failed"
run_scenario_expecting "drain_gate_degraded_volume" \
  rolling-upgrade.yaml \
  "${SCRIPT_DIR}/test_drain_gate_degraded_volume.yml" \
  "Longhorn still reports pvc-degraded degraded" \
  "TASK \[upgrade_rescue_agent : Alert CRITICAL — upgrade failed before health checks\]" \
  "!pvc-elsewhere" \
  "!TASK \[cordon_drain : Cordon node before drain\]" \
  "-e" "cordon_drain_longhorn_wait=2" \
  "-e" "cordon_drain_longhorn_poll=1" \
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

# A missing state directory must report the precondition, not a traceback (#264).
run_scenario_expecting "migrate_stage_no_state_dir" \
  migrate-config-to-longhorn.yaml \
  "${SCRIPT_DIR}/test_migrate_stage_no_state_dir.yml" \
  "shoebox-ansible-setup.yaml" \
  "-e" "app=ombi" "-e" "state_dir=${STATE_DIR}/definitely-not-here" "-t" "stage"

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

# calibre: two workloads, two source subPaths on one volume (#270).
run_scenario "migrate_stage_calibre" \
  migrate-config-to-longhorn.yaml \
  "${SCRIPT_DIR}/test_migrate_stage_calibre.yml" \
  "-e" "app=calibre" "-t" "stage" \
  "-e" "migrate_manifest=${SCRIPT_DIR}/fixtures/two-container-app.yaml" \
  "-e" '{"migrate_sources":[{"subpath":"calibre","dest":"calibre"},{"subpath":"calibre-web","dest":"calibre-web"}],"migrate_scale_targets":[{"kind":"StatefulSet","name":"calibre"},{"kind":"StatefulSet","name":"calibre-web"}],"migrate_replace_workloads":true}'

cat > "${STATE_DIR}/migrate-calibre-syncpolicy.json" <<'JSON'
{"automated": {"prune": true, "selfHeal": true}}
JSON

# A merged pod mounts /config once per container. The post-check has to accept
# that while still requiring every mount to be on the staged volume.
run_scenario_expecting "migrate_resume_calibre" \
  migrate-config-to-longhorn.yaml \
  "${SCRIPT_DIR}/test_migrate_resume_calibre.yml" \
  "calibre is live on calibre-config-calibre-0" \
  "-e" "app=calibre" "-t" "resume" \
  "-e" "migrate_manifest=${SCRIPT_DIR}/fixtures/two-container-app.yaml"

# Only the second container left on NFS. Checking one mount would miss it.
# Claim order is not guaranteed, so match both halves rather than a literal.
run_scenario_expecting "migrate_resume_calibre_split" \
  migrate-config-to-longhorn.yaml \
  "${SCRIPT_DIR}/test_migrate_resume_calibre_split.yml" \
  "resolves to PVC .*'app-configs'.*expected 'calibre-config-calibre-0'" \
  "-e" "app=calibre" "-t" "resume" \
  "-e" "migrate_manifest=${SCRIPT_DIR}/fixtures/two-container-app.yaml"

run_scenario "migrate_rollback" \
  migrate-config-to-longhorn.yaml \
  "${SCRIPT_DIR}/test_migrate_rollback.yml" \
  "-e" "app=ombi" "-t" "rollback"

# ── tls_cert: deliver a cluster-issued cert to an off-cluster host (#364) ───
TLS_CERT_COMMON_ARGS=(
  "-e" "tls_cert_secret=shoebox-tls"
  "-e" "tls_cert_namespace=default"
  "-e" "tls_cert_format=separate"
  "-e" "tls_cert_min_days=30"
  "-e" "tls_cert_reload_command=/bin/echo TLS_CERT_RELOAD_FIRED"
  "--limit" "shoebox"
)

# Scenario: first delivery of a long-dated cert — copy changes both files, so
# the reload command fires. ansible.builtin.copy does not create missing
# parent directories, so the destination must exist first.
mkdir -p "${STATE_DIR}/tls-cert-reload"
run_scenario_expecting "tls_cert_delivers_and_reloads" \
  "${SCRIPT_DIR}/test-tls-cert.yaml" \
  "${SCRIPT_DIR}/test_tls_cert_delivers_and_reloads.yml" \
  "TLS_CERT_RELOAD_FIRED" \
  "-e" "tls_cert_dest_cert=${STATE_DIR}/tls-cert-reload/tls.crt" \
  "-e" "tls_cert_dest_key=${STATE_DIR}/tls-cert-reload/tls.key" \
  "${TLS_CERT_COMMON_ARGS[@]}"

# Scenario: the destination already holds the exact cert and key the Secret
# would deliver (seeded below from the same fixture) — copy's checksum
# compare reports no change, so the reload command must not fire.
mkdir -p "${STATE_DIR}/tls-cert-unchanged"
install -m 0600 "${SCRIPT_DIR}/fixtures/tls-cert-valid.crt" "${STATE_DIR}/tls-cert-unchanged/tls.crt"
install -m 0600 "${SCRIPT_DIR}/fixtures/tls-cert-valid.key" "${STATE_DIR}/tls-cert-unchanged/tls.key"
run_scenario_expecting "tls_cert_skips_reload_unchanged" \
  "${SCRIPT_DIR}/test-tls-cert.yaml" \
  "${SCRIPT_DIR}/test_tls_cert_skips_reload_unchanged.yml" \
  "TASK \[tls_cert : Deliver the certificate\]" \
  "!TLS_CERT_RELOAD_FIRED" \
  "-e" "tls_cert_dest_cert=${STATE_DIR}/tls-cert-unchanged/tls.crt" \
  "-e" "tls_cert_dest_key=${STATE_DIR}/tls-cert-unchanged/tls.key" \
  "${TLS_CERT_COMMON_ARGS[@]}"

# Scenario: a short-dated fixture (combined/Pi-hole format) fails the run
# rather than delivering quietly.
mkdir -p "${STATE_DIR}/tls-cert-short"
run_failing_scenario "tls_cert_short_dated_fails" \
  "${SCRIPT_DIR}/test-tls-cert.yaml" \
  "${SCRIPT_DIR}/test_tls_cert_short_dated_fails.yml" \
  "expires .* within tls_cert_min_days" \
  "-e" "tls_cert_secret=shoebox-tls" \
  "-e" "tls_cert_namespace=default" \
  "-e" "tls_cert_format=combined" \
  "-e" "tls_cert_min_days=30" \
  "-e" "tls_cert_reload_command=/bin/echo TLS_CERT_RELOAD_FIRED" \
  "-e" "tls_cert_dest_cert=${STATE_DIR}/tls-cert-short/combined.pem" \
  "--limit" "shoebox"

echo ""
echo "All Monkeyble scenarios passed."
