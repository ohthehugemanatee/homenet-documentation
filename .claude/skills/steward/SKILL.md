---
name: steward
description: Repo-specific posture for watching a pull request to merge.
---

# Watching a PR

Skip the scheduled check-in when all three hold on the current head:

- every required check completed successfully,
- no merge conflict,
- no open review thread or outstanding reviewer request.

Say once that the PR is green and waiting on review, then rely on webhook
events alone. Re-arm the check-in as soon as any of the three stops holding.

Where a Claude Approvals check withholds an otherwise green PR, that is agent
work: keep the check-in scheduled.
