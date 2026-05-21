#!/usr/bin/env bash
# Weekly wrapper for node-state.yaml.
# Fires a Pushover alert on non-zero exit. Logs to /var/log/ansible/.
# Invoked by homelab/systemd/ansible-node-state.service.
set -euo pipefail

LOG="/var/log/ansible/node-state-$(date +%Y%m%d-%H%M%S).log"
VAULT_PASS="/etc/ansible/vault-password"
PLAYBOOK_DIR="/home/user/homenet-documentation/cluster/ansible"

mkdir -p /var/log/ansible

cd "$PLAYBOOK_DIR"

if ansible-playbook -i inventory.yaml \
    --vault-password-file "$VAULT_PASS" \
    -e vault_file=group_vars/vault.yaml \
    node-state.yaml 2>&1 | tee "$LOG"; then
  exit 0
fi

# Playbook exited non-zero — fire Pushover alert
# shellcheck source=/dev/null
source /etc/ansible/pushover.env
curl -s -X POST https://api.pushover.net/1/messages.json \
  -d "token=${PUSHOVER_TOKEN}&user=${PUSHOVER_USER}" \
  --data-urlencode "message=WARNING: node-state.yaml failed on $(hostname). Review: $LOG" \
  -d "priority=1"

exit 1
