# CLAUDE.md — repo-wide rules for agents

A homelab k3s cluster's docs + IaC: K8s manifests and Helm overrides in `cluster/`, Ansible (playbooks + roles + tests) in `cluster/ansible/`, an external Ansible runner in `shoebox/`, CI in `.github/`.

Root `*.md` files are operator architecture docs. They are not loaded into context — read the one matching the change: `README.md` for the cluster overview, `monitoring-and-compliance.md` for the Semaphore scheduler and the upgrade runbook, `argocd.md` for GitOps, `cert-manager.md` for TLS issuance, `dns.md` for Pi-hole, `warehouse.md` and `nextcloud.md` for the storage hosts, `remote-debugging.md`, `nextcloud-mcp.md` and `plex-mcp.md` for the MCP surfaces.

Directories with rules of their own carry a `CLAUDE.md` (plus an `AGENTS.md` symlink). Claude Code loads this file from the repo root and a nested one when it reads files in that directory, so this file holds only the cross-cutting rules.

## Workflow

IMPORTANT: every change follows this workflow; do not skip steps.

- **Decompose first.** Break a large request into the smallest set of atomic GitHub Issues, as a numbered list with a sequencing graph (`#3 blocks #4,#5`; `#6,#7 parallel after #4`). Atomic means one testable acceptance criterion, and its PR(s) can merge without simultaneously requiring another Issue's PR — not "doesn't change the cluster".
- **Spec-first, per Issue.** Before any diff: intent, target namespace/host/inventory group, resources touched, expected end-state, rollback path, out-of-scope items. Non-trivial goes in the PR description or `wip/SPEC.md`; trivial goes in the first sentences of the commit body. No diff without a spec.
- **Test-first, and review the tests against the spec.** Add the failing check before the implementation. Review tests for coverage and effectiveness (would they catch a regression?) before writing code, before commit, and again at PR review.
- **Extend the test frameworks when they don't cover the change.** A new `monkeyble` scenario, `molecule` verify, `test-cluster.yaml` step or `shoebox/tests/` case belongs in the spec. "We don't have a test for this kind of thing" is not an excuse to skip test-first.
- **PR size.** Warn at 200 LOC changed (added + removed, non-generated); at 400 LOC the PR must be split before merge. Propose the split in the same sequencing-graph format.
- **Issue ↔ PR is 1:N, never N:1.** Each PR addresses exactly one Issue. An Issue may span several PRs: decompose its acceptance criteria inside the Issue, each PR satisfying a labelled subset.
- **Constrain scope; ask before straying.** Smallest diff that satisfies the spec, no adjacent refactors. Do not modify files outside the Issue's declared scope without asking — a typo fix in an unrelated file is its own Issue. If the operator expands scope mid-flight, name the expansion, propose it as a new Issue with its place in the graph, and finish the original.
- **Prefer upstream components over scripted glue.** In order: upstream Helm chart plus our values, community operator/controller, vendored upstream manifest, raw manifest we author. Bash scripts, `curl | sh` init containers and one-off `kubectl` in CI are the last resort and need justification in the spec.
- **Run tests before commit; fix failures rather than commit around them.** Never commit with known-failing tests, never silence a test or add to an exception file to make CI green, never `--no-verify`.
- **A config change carries its doc fix.** When a change touches K8s manifests, Helm values, Ansible vars or playbooks, CI workflows or docker-compose, check the `*.md` in the affected directory and the repo root; a doc that needs updating is a bug, and the fix ships in the same PR. "Needs updating" means the existing text is now factually wrong, or contradicts the new behavior. It does not mean the topic could carry more explanation, more operational detail, or a note on how the bug was found; those go in the PR description if anywhere.
- **Outside `adr/`, docs describe the current implementation only.** Explain reasoning only where an aspect would otherwise be misread. Do not narrate how the current state was reached.
- **Drafts stay out of the codebase.** With squash-merge a branch's intermediate states are not history. If a PR took three attempts to pass, only the third merged; the other two belong in the Issue or PR thread, nowhere in the repo.
- **An ADR records a decision that changed the repo.** Write one per `adr/CLAUDE.md`.

## Coding behavior

- **Think before coding.** State assumptions; present multiple interpretations rather than picking one silently; stop and ask when something is unclear.
- **Simplicity first.** Minimum code and config that solves the Issue: no speculative abstractions, no unrequested configurability, no error handling for impossible scenarios.
- **Comment budget.** A comment states a non-obvious invariant, an external workaround, or a constraint — nothing else, and one line where one line will do. Never narrate the incident, Issue or PR behind the change; that belongs in the commit message and PR description. If deleting a comment would not leave a future reader confused, delete it rather than trim it. Docstrings and file headers get the same bar.
- **Surgical changes.** Don't improve adjacent code, comments or formatting; match existing style; remove only the imports, vars and functions your change orphaned, and mention other dead code rather than deleting it. "Match existing style" covers formatting and idiom, not comment volume: the budget above wins over the neighbouring file.
- **Goal-driven execution.** For a multi-step task, state a short plan with a verify step per line.

## Secrets — never in repo

**NEVER** commit plaintext secrets. No `*.key` (gitignored under `cluster/keys/`). **NEVER resolve `CHANGEME_*` placeholders** — leave them literal even if the operator pastes a real value in chat. Ansible secrets live in vault (`--ask-vault-pass`). Shoebox uses `SEMAPHORE_ACCESS_KEY_ENCRYPTION` as an env var on the host, validated by `shoebox/scripts/validate-semaphore-key.sh`. Obvious fake tokens like `ci-test-token` are intentional CI fixtures — do not "fix" them.

## Universal linters and exceptions

Gating linters apply to every directory:

- `yamllint` (config `.yamllint.yaml` — line length 160, lax booleans)
- `ansible-lint` (config `.ansible-lint`) — runs on any Ansible file in the diff, in `cluster/ansible/` or `shoebox/`
- `shellcheck` on every `*.sh`

K8s-specific linters (`kubeconform`, `kube-score`, `polaris`, `hadolint`) are in `cluster/CLAUDE.md`.

Consult before "fixing" a finding:

- `.trivyignore.yaml` — documented homelab tradeoffs. An entry with `paths` is scoped to those files so the rule keeps firing elsewhere.
- `.github/agentic-review-exceptions.yaml` — dismissed AI-review findings; do not re-raise.

## Universal verification — before every commit

```sh
yamllint .
shellcheck $(git ls-files '*.sh')
ansible-lint <touched-ansible-paths>   # any Ansible file in the diff
```

Then run the verification block in the nearest `CLAUDE.md` for every directory your diff touches. Green before commit; never silence to commit.

## Commit + PR etiquette

- Imperative mood, lowercase start, short subject; `feat:` / `fix:` prefix optional.
- Bot commits carry `[Claude]`; autofix commits carry `[autofix]` so `autofix.yaml` doesn't re-loop; `[skip-review]` or `[no-review]` skips AI review.
- Open PRs as draft until self-review and local tests pass.

## Documentation style

Terse, operator-first; real names (`warehouse`, `shoebox`, `Pi-hole`, `k3s`, `Longhorn`, `MetalLB`, `traefik`, `cloudflared`, `Semaphore`). No marketing prose, no emojis, no "in conclusion" sections.

Run every piece of prose through the `avoid-ai-writing` skill (voice `technical`, context `docs`) before it ships: Issue bodies, PR descriptions, PR and review comments, `*.md` files, ADRs, commit message bodies. Code and YAML comments are out of scope. It is part of writing the prose, never its own Issue. The skill lives in the operator's Claude profile; an agent without it reads <https://raw.githubusercontent.com/conorbronsdon/avoid-ai-writing/refs/heads/main/SKILL.md>.
