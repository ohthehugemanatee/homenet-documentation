const test = require('node:test');
const assert = require('node:assert/strict');
const { resolveMirrorTarget } = require('../resolve-review-head-sha.js');

test('uses the run\'s own head_sha, not a superseding push\'s live PR head', () => {
  // Commit A's review run was cancelled after commit B was pushed. By the
  // time this workflow_run event fires, the PR's live head is already B.
  const wf = {
    head_sha: 'commit-a-sha',
    conclusion: 'cancelled',
    pull_requests: [{ number: 42, head: { sha: 'commit-b-sha' } }],
  };
  const target = resolveMirrorTarget(wf);
  assert.equal(target.kind, 'direct');
  assert.equal(target.headSha, 'commit-a-sha');
  assert.equal(target.prNumber, 42);
});

test('workflow_dispatch with pr_number defers to a live PR lookup', () => {
  const wf = { event: 'workflow_dispatch', inputs: { pr_number: '7' } };
  const target = resolveMirrorTarget(wf);
  assert.equal(target.kind, 'dispatch-lookup');
  assert.equal(target.prNumber, 7);
});

test('workflow_dispatch without pr_number is not mirrored', () => {
  const wf = { event: 'workflow_dispatch', inputs: {} };
  assert.equal(resolveMirrorTarget(wf).kind, 'none');
});

test('run with no associated PR is not mirrored', () => {
  const wf = { event: 'push', pull_requests: [] };
  assert.equal(resolveMirrorTarget(wf).kind, 'none');
});
