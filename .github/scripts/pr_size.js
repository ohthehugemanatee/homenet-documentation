// Size accounting for the PR size gate. The decision lives here rather than in
// `pr-size-gate.yaml`'s inline github-script so it can be unit-tested
// (`node --test .github/scripts/tests/`) instead of only being exercised by
// opening a PR against the thresholds.

// ADRs do not count toward the thresholds: writing the record has to stay
// cheap, or the gate discourages the thing it is meant to encourage (ADR-0001).
// Everything else in the same PR still counts.
const EXEMPT_PREFIXES = ['adr/'];

const SOFT_LIMIT = 200;
const HARD_LIMIT = 400;

function isExempt(filename) {
  return EXEMPT_PREFIXES.some((prefix) => filename.startsWith(prefix));
}

// files: the `pulls.listFiles` payload — { filename, additions, deletions }.
function countLines(files) {
  const counted = { additions: 0, deletions: 0 };
  const exempt = { additions: 0, deletions: 0 };
  for (const f of files) {
    const bucket = isExempt(f.filename) ? exempt : counted;
    bucket.additions += f.additions;
    bucket.deletions += f.deletions;
  }
  return { counted, exempt };
}

function classify({ counted, exempt }, hasOverride) {
  const loc = counted.additions + counted.deletions;
  const exemptLoc = exempt.additions + exempt.deletions;
  const churn = `${loc} lines (${counted.additions}+ / ${counted.deletions}−)`;
  const exemptNote = exemptLoc
    ? ` ${exemptLoc} line${exemptLoc === 1 ? '' : 's'} under `
      + `${EXEMPT_PREFIXES.join(', ')} are exempt and not included.`
    : '';

  if (loc >= HARD_LIMIT) {
    return {
      conclusion: 'failure',
      title: `PR exceeds hard limit: ${loc} LOC (max ${HARD_LIMIT})`,
      summary: `This PR changes ${churn}.${exemptNote} `
        + `PRs ≥${HARD_LIMIT} LOC must be split before merge. `
        + `See CLAUDE.md for decomposition guidelines.`,
    };
  }
  if (loc >= SOFT_LIMIT && !hasOverride) {
    return {
      conclusion: 'action_required',
      title: `PR exceeds soft limit: ${loc} LOC (warn ≥${SOFT_LIMIT})`,
      summary: `This PR changes ${churn}.${exemptNote} `
        + `PRs ≥${SOFT_LIMIT} LOC require manual acknowledgment before merge. `
        + `A maintainer must add the \`size/override\` label to unblock.`,
    };
  }
  const note = loc >= SOFT_LIMIT ? ' (size/override acknowledged)' : '';
  return {
    conclusion: 'success',
    title: `PR size: ${loc} LOC — OK${note}`,
    summary: `${churn} changed.${exemptNote}`,
  };
}

module.exports = { EXEMPT_PREFIXES, SOFT_LIMIT, HARD_LIMIT, isExempt, countLines, classify };
