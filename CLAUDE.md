# CLAUDE.md — repo-wide rules for agents

This is a homelab k3s cluster's docs + IaC: K8s manifests + Helm overrides in `cluster/`, Ansible (playbooks + roles + tests) in `cluster/ansible/`, an external Ansible runner in `shoebox/`, CI in `.github/`. For project context read `@README.md`, `@dns.md`, `@nextcloud.md`, `@warehouse.md`, `@ansible-scheduler.md`, `@remote-debugging.md`, `@nextcloud-mcp.md`, `@plex-mcp.md`, `@cert-manager.md`.

Every directory has its own `CLAUDE.md` (with `AGENTS.md` symlink); Claude Code loads each from cwd up to repo root, so this file holds only the cross-cutting rules.

## Workflow — NON-NEGOTIABLE

**IMPORTANT.** Every change follows this workflow. YOU MUST NOT skip steps.

- **Decompose first.** Large feature requests get broken into the smallest set of atomic GitHub Issues, presented as a numbered list with an explicit **sequencing graph** (`#3 blocks #4,#5`; `#6,#7 parallel after #4`). An Issue is "atomic" if it has a single testable acceptance criterion AND its PR(s) can merge without simultaneously requiring another Issue's PR — *not* "doesn't change the cluster".
- **Spec-first (per Issue).** Before any diff: intent, target namespace/host/inventory group, resources touched, expected end-state, rollback path, out-of-scope items. Non-trivial → PR description or `wip/SPEC.md`; trivial → first sentences of the commit body. **No diff without a spec.**
- **Test-first AND review tests vs spec.** Add the failing check before the implementation; review tests against the spec for *coverage* and *effectiveness* (would they catch a regression?) **before** writing code, **before** commit, and again at PR review.
- **CI/test coverage may need expansion.** If existing frameworks don't adequately cover the change, the spec MUST include extending them — new `monkeyble` scenario, new `molecule` verify, new `test-cluster.yaml` step, new `shoebox/tests/` case. "We don't have a test for this kind of thing" is not an excuse to skip test-first.
- **PR size limits (hard).** Warn at **≥200 LOC** changed (added + removed, non-generated). At **≥400 LOC the PR MUST be split** before merge. When the warning hits, propose the split with the same sequencing-graph format.
- **Issue ↔ PR is 1:N, never N:1.** Each PR addresses exactly one Issue. One Issue MAY span multiple PRs if it doesn't fit; decompose its acceptance criteria inside the Issue, each PR satisfies a labelled subset.
- **Constrain scope; minimal changes; ask before straying.** Smallest diff that satisfies the spec. No adjacent refactors. **Do not modify files outside the Issue's declared scope without asking** — a typo fix in an unrelated file is its own Issue. If the operator expands scope mid-flight, push back: name the expansion, propose it as a new Issue with its place in the graph, finish the original.
- **Prefer established upstream/community components over scripted glue.** Order: (1) upstream Helm chart + our values, (2) community operator/controller, (3) vendored upstream manifest, (4) raw manifest we author. Bash scripts, `curl | sh` init containers, one-off `kubectl` in CI are the **last** resort and require justification in the spec. Ansible: Galaxy roles/collections in `requirements.yaml` over hand-rolled `command:` / `shell:`.
- **Run tests before commit; fix failures, don't commit around them.** Never commit with known-failing tests, never silence a test or add to an exception file to make CI green, never `--no-verify`.
- **Verify configuration changes in updated project documentation.** When a change touches configuration (K8s manifests, Helm values, Ansible vars/playbooks, CI workflows, docker-compose), cross-check the updated project docs (`*.md` in the affected directory and repo root) for correctness and effect — stale docs that contradict the new config are a bug. If docs need updating, include the doc fix in the same PR. "Needs updating" means the existing text is now factually wrong, or contradicts the new behavior. It does not mean the topic could carry more explanation, more operational detail, or a note on how the bug was found; those go in the PR description if anywhere.
- **Outside `adr/`, documentation describes the current implementation only.** Explain reasoning only where an aspect is unusual or significant enough that a reader would otherwise get it wrong. Do not narrate how the current state was reached.
- **Implementation history that never reached `master` stays out of the codebase.** With squash-merge, a branch's intermediate states are not history — they are drafts. If a PR took three attempts to pass tests, only the third was merged; the first two are not worth describing anywhere in the repo. Where that context is worth keeping, it belongs in the Issue or PR thread.
- **An ADR records a decision that changed the repo.** Write one in `adr/` per `adr/CLAUDE.md`; a design discussion that produced no in-repo change does not need one.

## Coding behavior

- **Think before coding.** State assumptions explicitly; if multiple interpretations exist, present them instead of picking silently; if something is unclear, stop and ask.
- **Simplicity first.** Minimum code/config that solves the Issue — no speculative abstractions, no unrequested flexibility or configurability, no error handling for impossible scenarios.
- **Comment budget.** A comment states a non-obvious invariant, an external workaround, or a constraint. Nothing else, and one line where one line will do. Never narrate the incident, Issue, or PR behind the change; that belongs in the commit message and PR description. If deleting a comment would not leave a future reader confused, delete it rather than trim it. Docstrings and file headers get the same bar.
- **Surgical changes.** Don't "improve" adjacent code, comments, or formatting; match existing style; remove only the imports/vars/functions your change orphaned — mention other dead code, don't delete it (see scope rule above). "Match existing style" covers formatting and idiom, not comment volume: the budget above wins over whatever the neighbouring file does.
- **Goal-driven execution.** Convert vague asks into verifiable success criteria before starting — this repo's spec-first/test-first rules already do this per Issue; for multi-step tasks, state a short plan with a verify step per line.

## Repository map

| Path | What lives here | Nearest leaf `CLAUDE.md` |
|---|---|---|
| `cluster/` | All Kubernetes resources + node Ansible | `cluster/CLAUDE.md` |
| `cluster/services/` | Application workloads (raw YAML) | `cluster/services/CLAUDE.md` |
| `cluster/ansible/` | Playbooks, roles, monkeyble + molecule tests | `cluster/ansible/CLAUDE.md` |
| `cluster/helm/` | Values overrides for upstream charts | `cluster/helm/CLAUDE.md` |
| `cluster/storage/` | PV/PVC for stateful services | `cluster/storage/CLAUDE.md` |
| `cluster/argocd/` | ArgoCD Application manifests (app-of-apps) | `cluster/argocd/CLAUDE.md` |
| `shoebox/` | External Ansible runner (Semaphore in Docker) | `shoebox/CLAUDE.md` |
| `.github/` | CI workflows + autofix script | `.github/CLAUDE.md` |
| `adr/` | Architecture Decision Records (append-only) | `adr/CLAUDE.md` |
| root `*.md` | Operator architecture docs (imported above) | — |

## Secrets — never in repo

**NEVER** commit plaintext secrets. No `*.key` (gitignored under `cluster/keys/`). **NEVER resolve `CHANGEME_*` placeholders** — leave them literal even if the operator pastes a real value in chat. Ansible secrets live in vault (`--ask-vault-pass`). Shoebox uses `SEMAPHORE_ACCESS_KEY_ENCRYPTION` as an env var on the host, validated by `shoebox/scripts/validate-semaphore-key.sh`. Obvious fake tokens like `ci-test-token` are intentional CI fixtures — do not "fix" them.

## Universal linters and exceptions

Repo-wide gating linters apply to every directory:

- `yamllint` (config `.yamllint.yaml` — line length 160, lax booleans)
- `ansible-lint` (config `.ansible-lint`) — runs on **any** Ansible file in the diff, whether in `cluster/ansible/` or `shoebox/`
- `shellcheck` on every `*.sh`

K8s-specific linters (`kubeconform`, `kube-score`, `polaris`, `hadolint`) live in `cluster/CLAUDE.md`.

**Consult before "fixing" a finding:**
- `.trivyignore.yaml` — documented homelab tradeoffs (linuxserver images, nodelocaldns privileged, cert-manager, claude-remote-debug's read-only wildcard). An entry with `paths` is scoped to those files so the rule keeps firing elsewhere.
- `.github/agentic-review-exceptions.yaml` — dismissed AI-review findings; do not re-raise.

## Universal verification — before every commit

```sh
yamllint .
shellcheck $(git ls-files '*.sh')
ansible-lint <touched-ansible-paths>   # any Ansible file in the diff
```

**Then run the directory-specific verification listed in the nearest leaf `CLAUDE.md` for every directory your diff touches.** Each leaf owns checks relevant only to its subtree. Green before commit; never silence to commit.

## Commit + PR etiquette

- Imperative mood, lowercase start, short subject; `feat:` / `fix:` prefix optional.
- Bot commits carry `[Claude]` attribution.
- Autofix commits carry `[autofix]` so `autofix.yaml` doesn't re-loop.
- `[skip-review]` or `[no-review]` skips AI review.
- Open PRs as **draft** until self-review + local tests pass.
- PR bodies and review comments are prose: run them through `avoid-ai-writing` before posting (see [Documentation style](#documentation-style)).

## Documentation style

Terse, operator-first; real names (`warehouse`, `shoebox`, `Pi-hole`, `k3s`, `Longhorn`, `MetalLB`, `traefik`, `cloudflared`, `Semaphore`). No marketing prose, no emojis, no "in conclusion" sections.

**Every piece of prose goes through the `avoid-ai-writing` skill before it ships.** Scope is anything a human reads as sentences: Issue bodies, PR descriptions, PR and review comments, `*.md` files, ADRs, commit message bodies. Code and YAML comments are out of scope.

- Invoke it with voice `technical` and context `docs`. That pairing keeps the imperative, one-idea-per-sentence register described above, and tolerates the em dashes and dense lists this repo already uses.
- Run it on the draft, apply the rewrite, then ship. Detect-only mode is for auditing text you did not write.
- The skill lives in the operator's Claude profile. An agent that does not have it reads the current version from <https://raw.githubusercontent.com/conorbronsdon/avoid-ai-writing/refs/heads/main/SKILL.md>.
- Removing AI-isms is part of writing the prose. It never needs its own Issue.
