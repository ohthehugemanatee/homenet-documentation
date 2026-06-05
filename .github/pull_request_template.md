## Part 1: Standard Code Review Checklist

- [ ] **Functionality**: Meets all requirements; edge cases handled
- [ ] **Readability & Style**: Follows team coding standards
- [ ] **Design**: Follows established architectural patterns
- [ ] **Performance**: No new bottlenecks introduced
- [ ] **Error Handling**: Errors handled gracefully
- [ ] **Testing**: Sufficient unit and integration tests present
- [ ] **Documentation**: Code and PR adequately documented

## Part 2: MANDATORY AI-Specific Validation Checklist

- [ ] **Omission Check**: What security controls is this code missing? (input validation, output encoding, authorization)
- [ ] **Logic Check**: Is there a subtle logic error? (`==` vs `in`, off-by-one, inverted condition)
- [ ] **Dependency Check**: Are all new packages real, secure, and approved? (no hallucinated dependencies)
- [ ] **Context Check**: Did the AI take a dangerous shortcut (e.g., `eval()`, `--no-verify`, disabled auth) that violates our security posture?
- [ ] **Drift Check**: Did the AI change security-critical code (auth, crypto, RBAC, network policy) outside the PR's declared scope?

---

> **Feedback loop:** If you find a recurring AI mistake not already in
> [`.github/agentic-review-exceptions.yaml`](.github/agentic-review-exceptions.yaml),
> document it there with rationale so future reviewers and the AI reviewer won't repeat it.
