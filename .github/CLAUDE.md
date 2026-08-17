# .github/CLAUDE.md — CI workflows and the autofix loop

## Workflow inventory

- `workflows/lint.yaml` — `yamllint` + `kubeconform` + `kustomize build` + `ansible-lint` (+ advisory kube-score/polaris/trivy).
- `workflows/test-ansible.yaml` — three jobs: shoebox validators (`shoebox/tests/*.sh`), monkeyble (`cluster/ansible/tests/monkeyble/run-tests.sh`), molecule (`cluster/ansible/molecule/`).
- `workflows/test-cluster.yaml` — k3d smoke test: spins up a local cluster and applies manifests.
- `workflows/pr-review.yaml` — Claude AI review. Its `review` job is named `AI review required`, and that job's own check run **is** the branch-protection gate: a `pull_request`-triggered job emits a check bound to the SHA it ran on, so nothing needs to mirror a result onto the PR head. Triggers are `[opened, synchronize]` — every event that can produce a new head SHA; `reopened`/`ready_for_review` don't change the SHA, so the existing check still applies. If a run is cancelled by `cancel-in-progress` while the PR head is unchanged, re-run the workflow from the Actions tab to unblock.

  The gate is **substantive**: the reviewer returns structured findings via a forced `report_review` tool call, and `scripts/review_verdict.py` decides. A finding blocks merge when it is `HIGH` **and** confidence is `High` or `Medium` — that policy is two constants at the top of that module, unit-tested in `scripts/tests/test_review_verdict.py`. The rule **fails closed**: an unparseable severity, a missing field, or a response truncated by `max_tokens` blocks rather than passes, so a malformed reply can never look like a clean review. `review/override` on the PR waives a blocking finding (the review is still posted); recurring false positives belong in `agentic-review-exceptions.yaml` instead.
- `workflows/pr-size-gate.yaml` — soft (≥200 LOC) and hard (≥400 LOC) PR size limits; `size/override` label bypasses the soft limit. It fires on `labeled`/`unlabeled` as well as the SHA-changing events, so it can run several times against one head SHA; it therefore **updates** its `PR size check` check run in place instead of creating a new one each time. Creating each time left the pre-label failure sitting on the SHA beside the post-label success, and a re-run could not clear it because GitHub replays the original event payload (#245). The job is named `PR size gate`, deliberately *not* `PR size check`, so it is not a second producer of the gate's name.

**Check names are gates — one producer each.** Branch protection matches required checks by name, so two producers of one name make the gate race itself and strand a red check run that no re-run can clear (#236, #245). `lint.yaml`'s `github-scripts` job enforces this across every `pull_request` workflow. A job whose `name:` is the check name and a `checks.create` using that name both count; when a workflow can run more than once per SHA, the single producer must update in place.
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

- `agentic-review-exceptions.yaml` documents dismissed AI-review findings. Update intentionally when adding/removing a known finding; **never** as a way to silence a real failure. Since the AI review gate blocks on HIGH findings, this file is the durable fix for a recurring false positive — `review/override` is the one-off escape hatch, not a substitute.

## PR template

`pull_request_template.md` provides the checklist for human reviewers: Part 1 is the standard code review checklist; Part 2 is the mandatory AI-specific validation checklist (omission, logic, dependency, context, drift); Part 3 is the explicit security & privacy checklist (secrets, RBAC, network exposure, container security, privacy). The AI review workflow (`pr-review.yaml`) is prompted to run the same Part 2 and Part 3 checks and must report each item explicitly. Recurring AI mistakes found during review belong in `agentic-review-exceptions.yaml` with rationale.
