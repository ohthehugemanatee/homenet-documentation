# .github/CLAUDE.md — CI workflows and the autofix loop

## Workflow inventory

- `workflows/lint.yaml` — `yamllint` + `kubeconform` + `ansible-lint`.
- `workflows/test-ansible.yaml` — three jobs: shoebox validators (`shoebox/tests/*.sh`), monkeyble (`cluster/ansible/tests/monkeyble/run-tests.sh`), molecule (`cluster/ansible/molecule/`).
- `workflows/test-cluster.yaml` — k3d smoke test: spins up a local cluster and applies manifests.
- `workflows/pr-review.yaml` + `workflows/pr-review-gate.yaml` — Claude AI review + status-check gate.
- `workflows/autofix.yaml` — fires on `lint.yaml` / `test-cluster.yaml` failure; runs `scripts/autofix.py` (Claude agentic loop: read_file / write_file / run_bash; commits + comments).

## `autofix.py` invariants — DO NOT BREAK

**IMPORTANT.** The autofix loop is the only thing keeping CI green without manual intervention. When editing `scripts/autofix.py`:

- **Read-only bash allowlist stays in place.** No `curl`, no commands that can exfiltrate secrets.
- **Same-repo PRs only.** No forks — write permission would leak.
- **Autofix commits MUST carry `[autofix]` in the subject** so this workflow does not re-loop on its own pushes. The marker check happens early; removing it deadlocks CI.
- Any change to `autofix.py` needs a spec + a dry-run before merge.

## Commit subject markers

- `[autofix]` — autofix workflow ignores (anti-loop).
- `[skip-review]` or `[no-review]` — AI review skipped.
- `[Claude]` — bot-authored attribution.

## Exception files

- `agentic-review-exceptions.yaml` documents dismissed AI-review findings. Update intentionally when adding/removing a known finding; **never** as a way to silence a real failure.

## PR template

`pull_request_template.md` provides the checklist for human reviewers: Part 1 is the standard code review checklist; Part 2 is the mandatory AI-specific validation checklist (omission, logic, dependency, context, drift). The AI review workflow (`pr-review.yaml`) is prompted to run the same Part 2 checks and must report each item explicitly. Recurring AI mistakes found during review belong in `agentic-review-exceptions.yaml` with rationale.
