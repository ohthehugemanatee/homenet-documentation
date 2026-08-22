# adr/CLAUDE.md — Architecture Decision Records

Numbered, immutable records of decisions that changed this repo. One decision per
file, `NNNN-kebab-case-title.md`, numbers never reused.

## Rules

- **Append-only.** An accepted ADR is not edited to reflect a later change of mind.
  A reversed or replaced decision gets a new ADR; the old file stays and its `Status`
  becomes `superseded by ADR-NNNN`. That status line is the only edit it ever gets.
- **In-repo impact is the bar.** Write an ADR when a decision changed what is in this
  repo. A design discussion that produced no in-repo change does not get one.
- **Short.** Homelab scale, not MADR. Three sections, a few sentences each. Past a
  screen, it is describing implementation, which belongs in the doc for the thing.
- **Present tense elsewhere.** Moving history out of a file is half the job; the
  sentence left behind has to read as current fact.
- **Not counted by the PR size gate.** `.github/scripts/pr_size.js` exempts `adr/`, so
  writing the record never pushes a PR over the 200/400 LOC thresholds. Everything
  else in the same PR still counts.

Start from [`template.md`](template.md).

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-decisions-live-in-adr.md) | Architecture decisions live in `adr/` | accepted |
| [0002](0002-node-ansible-stays-under-cluster.md) | Node Ansible stays under `cluster/ansible/` | accepted |
| [0003](0003-argocd-supersedes-install-scripts.md) | ArgoCD owns ongoing state; `install.sh` is bootstrap only | accepted |
| [0004](0004-cloud-sessions-reach-the-cluster-over-mcp.md) | Cloud sessions reach the cluster over MCP | accepted |
