// Decides which PR/SHA a completed "AI Infrastructure Review" workflow_run
// should have its result mirrored onto. Kept separate from the inline
// github-script step in pr-review-gate.yaml so the SHA-selection logic is
// unit-testable (see .github/scripts/tests/).
//
// wf.head_sha is the commit the workflow run actually checked out and
// reviewed. wf.pull_requests[0].head.sha is the PR's head SHA *at the time
// the workflow_run event fired*, which can be newer than what was reviewed
// if a later push superseded (and cancelled) this run.
function resolveMirrorTarget(wf) {
  if (wf.pull_requests && wf.pull_requests.length > 0) {
    return { kind: 'direct', headSha: wf.head_sha, prNumber: wf.pull_requests[0].number };
  }
  if (wf.event === 'workflow_dispatch' && wf.inputs && wf.inputs.pr_number) {
    return { kind: 'dispatch-lookup', prNumber: parseInt(wf.inputs.pr_number, 10) };
  }
  return { kind: 'none' };
}

module.exports = { resolveMirrorTarget };
