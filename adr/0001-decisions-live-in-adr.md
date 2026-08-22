# ADR-0001: Architecture decisions live in `adr/`

- **Status:** accepted
- **Date:** 2026-08-22

## Context

Decision and implementation history kept accumulating in inline comments, `CLAUDE.md`
files and READMEs, next to the description of what is deployed. A reader had to sort
current fact from the archaeology of how it got that way, and the archaeology only
grew. The #208/#239 pass made the failure mode obvious: the README ended up
documenting an upgrade mechanism that does not exist and a rationale for retiring a
model that was never implemented.

## Decision

Decisions that changed this repo get a numbered, append-only record in `adr/`.
Everything outside `adr/` describes the current implementation. Reasoning stays in a
doc or comment only where an aspect is unusual enough that a reader would otherwise
misread it as a mistake, the way `delugevpn.yaml`'s `privileged: true` comment does.
The test is whether the comment explains _what is_ or _what was_.

## Consequences

- `.github/scripts/pr_size.js` exempts `adr/` from the 200/400 LOC gate, so writing a
  record is free. Without it the gate would penalise the behaviour this ADR asks for.
- The root `CLAUDE.md` carries the three rules that follow from this: present tense
  outside `adr/`, no narration of unmerged branch states, and an ADR only for
  decisions with in-repo impact.
- Past decisions are not retrofitted. Only history already sitting in the wrong place
  gets extracted; the rest stays in the Issue and PR threads.
- Reversing a decision costs a new file rather than an edit, so the record of what was
  believed at the time survives.
