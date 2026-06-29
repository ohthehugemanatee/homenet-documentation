# shoebox/CLAUDE.md — external Ansible runner

Shoebox is the always-on NFS host. It runs Semaphore UI in Docker to **schedule** the playbooks in `cluster/ansible/` against the k3s cluster. It cannot move into the cluster (observer paradox: the cluster dies during upgrades, so the scheduler can't drive uncordon). See `@ansible-scheduler.md` for the architecture; Ansible foundation (ansible-lint, vault, Galaxy preference) lives in the root `CLAUDE.md`.

## Layout

- `semaphore/docker-compose.yaml` — Semaphore v2.10.22 (port 3000) + Python deps from `requirements.txt`.
- `scripts/validate-semaphore-key.sh` — validates `SEMAPHORE_ACCESS_KEY_ENCRYPTION` (URL-safe base64, exact length, no whitespace).
- `scripts/check-control-plane.sh` — external control-plane watchdog: probes the kube-apiserver VIP and Pushover-alerts on downtime. Driven by the `control-plane-watchdog.timer` systemd unit (every 1 min), installed by the bootstrap playbook. Reuses `/etc/ansible/pushover.env`; state in `/var/lib/ansible-upgrade/`, log in `/var/log/ansible/`.
- `tests/validate-semaphore-key` + `tests/check-control-plane` — unit tests for the scripts above.
- `shoebox-ansible-setup.yaml` — bootstrap playbook; runs from the operator's workstation against the shoebox host.

## Conventions

- **`SEMAPHORE_ACCESS_KEY_ENCRYPTION` is an env var on the shoebox host, never in repo.** Any change to its format MUST update both the validator and its tests (test-first).
- **Bash scripts:** every script starts with `set -euo pipefail`; every script is `shellcheck`-clean; every script has a unit test under `shoebox/tests/`.
- **No kubectl in shoebox scripts.** kubectl access from playbooks uses `delegate_to: localhost` with shoebox's kubeconfig (on the host, not in repo).
- **State and log dirs on the shoebox host:** `/var/lib/ansible-upgrade/` (upgrade state, maintenance flags) and `/var/log/ansible/` (run history). Any script that writes here documents the path inline with a comment.

## Verification — run before commit

```sh
bash shoebox/tests/test-validate-semaphore-key.sh
bash shoebox/tests/test-check-control-plane.sh
shellcheck shoebox/scripts/*.sh shoebox/tests/*.sh
```

(Bootstrap playbook is covered by the root universal `ansible-lint` step.) For a new validator, follow test-first: add a failing case under `shoebox/tests/` before writing the script.
