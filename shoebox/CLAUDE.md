# shoebox/CLAUDE.md — external Ansible runner

Shoebox is the always-on NFS host. It runs Semaphore UI in Docker to **schedule** the playbooks in `cluster/ansible/` against the k3s cluster. It cannot move into the cluster (observer paradox: the cluster dies during upgrades, so the scheduler can't drive uncordon). See `@ansible-scheduler.md` for the architecture; Ansible foundation (ansible-lint, vault, Galaxy preference) lives in the root `CLAUDE.md`.

## Layout

- `semaphore/docker-compose.yaml` — Semaphore v2.10.22 (port 3000) + Gatus v5.12.0 (port 8080); Python deps from `requirements.txt`.
- `gatus/config.yaml` — Gatus external availability monitor config: probes key services (kube-apiserver VIP, Nextcloud, Plex, Grafana, ArgoCD, Semaphore) and Pushover-alerts on consecutive failures. Credentials injected from `/etc/ansible/pushover.env` via docker-compose `env_file`. Status page on `localhost:8080`.
- `scripts/validate-semaphore-key.sh` — validates `SEMAPHORE_ACCESS_KEY_ENCRYPTION` (URL-safe base64, exact length, no whitespace).
- `tests/test-validate-semaphore-key.sh` — unit tests for the validator.
- `shoebox-ansible-setup.yaml` — bootstrap playbook; runs from the operator's workstation against the shoebox host.

## Conventions

- **`SEMAPHORE_ACCESS_KEY_ENCRYPTION` is an env var on the shoebox host, never in repo.** Any change to its format MUST update both the validator and its tests (test-first).
- **Bash scripts:** every script starts with `set -euo pipefail`; every script is `shellcheck`-clean; every script has a unit test under `shoebox/tests/`.
- **No kubectl in shoebox scripts.** kubectl access from playbooks uses `delegate_to: localhost` with shoebox's kubeconfig (on the host, not in repo).
- **State and log dirs on the shoebox host:** `/var/lib/ansible-upgrade/` (upgrade state, maintenance flags) and `/var/log/ansible/` (run history). Any script that writes here documents the path inline with a comment.

## Verification — run before commit

```sh
bash shoebox/tests/test-validate-semaphore-key.sh
shellcheck shoebox/scripts/*.sh shoebox/tests/*.sh
```

(Bootstrap playbook is covered by the root universal `ansible-lint` step.) For a new validator, follow test-first: add a failing case under `shoebox/tests/` before writing the script.
