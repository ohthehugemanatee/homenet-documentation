---
name: steward
description: Repo-specific posture for watching a pull request to merge.
---

# Watching a PR in this repo

This file governs how proactive to be while watching a PR. Everything the
default rules state as "never" still binds: no skipping, disabling or
quarantining a test, no empty commit or reopen to kick CI, no rewriting
history on someone else's branch, no approving or merging.

## Stop the scheduled check-in once the PR only waits on a human

The default posture keeps a self check-in scheduled until the PR merges or
closes, because webhook delivery is best-effort and silence looks the same as
"CI is still running". That reasoning holds while the PR needs agent work. It
does not hold once the PR needs a person.

Skip the check-in when all three hold on the current head:

- every required check has completed successfully,
- there is no merge conflict,
- there is no open review thread and no reviewer request left to address.

In that state, rely on webhook events alone, say once that the PR is green and
waiting on review, and schedule nothing further. A dropped webhook here costs a
late merge notification and nothing else, because the next actor is human
either way.

Re-arm the check-in as soon as any of the three stops holding: CI turns red, a
conflict appears, or a review comment lands. A red or conflicted PR keeps the
default cadence, and so does one where a reviewer is waiting on you.

Green does not mean finished where the repo runs a Claude Approvals check: a
PR that check withholds still has agent work, so keep the check-in scheduled.
