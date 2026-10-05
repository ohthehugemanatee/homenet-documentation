## Part 1: Standard Code Review Checklist

- [ ] **Functionality**: Meets all requirements; edge cases handled
- [ ] **Readability & Style**: Follows team coding standards
- [ ] **Design**: Follows established architectural patterns
- [ ] **Performance**: No new bottlenecks introduced
- [ ] **Error Handling**: Errors handled gracefully
- [ ] **Testing**: Sufficient unit and integration tests present
- [ ] **Documentation**: Code and PR adequately documented

## Part 2: MANDATORY AI-Specific Validation Checklist

- [ ] **Omission Check**: Did the change omit required behavior, tests, docs, or rollback steps implied by the PR description or touched files?
- [ ] **Logic Check**: Is there a subtle logic error? (`==` vs `in`, off-by-one, inverted condition)
- [ ] **Idempotency Check**: Does an Ansible task, controller config, or workflow step create repeated side effects when it runs twice?
- [ ] **Dependency Check**: Are all new packages real and verifiable? (no hallucinated dependencies)
- [ ] **Context Check**: Did the AI take a dangerous shortcut (e.g., `eval()`, `--no-verify`, disabled auth) that violates our security posture?
- [ ] **Drift Check**: Did the AI change infrastructure, workflow, or documentation areas outside the PR's declared scope?
- [ ] **Doc Drift Check**: Do changed docs contradict manifests, Ansible, workflows, or scripts?
- [ ] **Rollback Check**: Is the stated rollback path real for the resources changed?
- [ ] **Comment Budget Check**: Do added comments, docstrings, and doc lines state non-obvious invariants only, or do they narrate the change? (compare added comment lines against added code lines)

---

> **Feedback loop:** If you find a recurring AI mistake not already in
> [`.github/agentic-review-exceptions.yaml`](.github/agentic-review-exceptions.yaml),
> document it there with rationale so future reviewers and the AI reviewer won't repeat it.
>
> **AI review gate:** the `AI review required` check fails when the reviewer reports a
> `HIGH` finding at `High` or `Medium` confidence. If it's a genuine false positive, add the
> `review/override` label to unblock this PR, then add the pattern to the exceptions file above
> so it doesn't recur.
