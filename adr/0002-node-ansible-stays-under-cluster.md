# ADR-0002: Node Ansible stays under `cluster/ansible/`

- **Status:** accepted
- **Date:** 2026-08-22

## Context

`cluster/CLAUDE.md` is loaded for every directory beneath `cluster/`, and its content
is Kubernetes manifest foundation: explicit `metadata.namespace`, default resource
requests, priority classes, `pv-`/`pvc-` naming. `cluster/ansible/` provisions the OS
on the nodes and uses almost none of that, so it inherits a rules file that mostly
does not apply to it. Hoisting it to a top-level `/ansible/` would fix the mismatch.

## Decision

Node Ansible stays at `cluster/ansible/`. The path is referenced from CI workflows,
`shoebox/`, the monkeyble and molecule harnesses, and the repository map; moving it is
a wide rename whose only benefit is which `CLAUDE.md` gets loaded.

## Consequences

- Agents working in `cluster/ansible/` load K8s-manifest rules that do not apply there.
  `cluster/ansible/CLAUDE.md` is the authority for that subtree.
- Ansible outside the cluster (`shoebox/`) already lives at root, so the two Ansible
  trees are not siblings. That asymmetry is accepted.
- Revisit only if a change is already touching those paths for another reason.
