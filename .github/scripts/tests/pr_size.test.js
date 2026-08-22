const assert = require('node:assert');
const { test } = require('node:test');

const { isExempt, countLines, classify } = require('../pr_size.js');

const file = (filename, additions, deletions) => ({ filename, additions, deletions });

test('only the ADR directory is exempt', () => {
  assert.equal(isExempt('adr/0001-adrs-live-in-adr.md'), true);
  assert.equal(isExempt('adr/template.md'), true);
  assert.equal(isExempt('adrs/0001-x.md'), false);
  assert.equal(isExempt('cluster/adr/0001-x.md'), false);
  assert.equal(isExempt('adr.md'), false);
});

test('countLines splits exempt lines out of the counted total', () => {
  const { counted, exempt } = countLines([
    file('adr/0001-adrs-live-in-adr.md', 40, 0),
    file('cluster/services/songhub.yaml', 6, 6),
    file('CLAUDE.md', 4, 1),
  ]);
  assert.deepEqual(counted, { additions: 10, deletions: 7 });
  assert.deepEqual(exempt, { additions: 40, deletions: 0 });
});

test('a small PR passes', () => {
  const result = classify(countLines([file('CLAUDE.md', 10, 2)]), false);
  assert.equal(result.conclusion, 'success');
  assert.match(result.title, /12 LOC/);
});

test('the soft limit needs the override label', () => {
  const files = [file('cluster/services/songhub.yaml', 150, 50)];
  assert.equal(classify(countLines(files), false).conclusion, 'action_required');
  const overridden = classify(countLines(files), true);
  assert.equal(overridden.conclusion, 'success');
  assert.match(overridden.title, /size\/override acknowledged/);
});

test('the hard limit is not overridable', () => {
  const files = [file('cluster/services/songhub.yaml', 300, 100)];
  assert.equal(classify(countLines(files), true).conclusion, 'failure');
});

test('ADR lines alone never trip either limit', () => {
  const files = [
    file('adr/0001-adrs-live-in-adr.md', 250, 0),
    file('adr/0002-ansible-stays-under-cluster.md', 250, 0),
    file('CLAUDE.md', 4, 1),
  ];
  const result = classify(countLines(files), false);
  assert.equal(result.conclusion, 'success');
  assert.match(result.title, /5 LOC/);
  assert.match(result.summary, /500 line/);
});
