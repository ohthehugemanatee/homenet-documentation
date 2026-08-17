"""Decide whether an AI review's findings should block the PR.

Kept out of the inline heredoc in workflows/pr-review.yaml so the gate's
block/pass rule is unit-testable (see tests/test_review_verdict.py).

Pure: no I/O, no network, no environment reads.
"""

# A finding blocks only when it is HIGH *and* the reviewer was reasonably
# sure. A low-confidence HIGH is still reported in the PR comment, but
# hard-blocking CI on one produces more noise than it prevents.
# Tune here — this is the whole policy.
BLOCKING_SEVERITY = 'HIGH'
BLOCKING_CONFIDENCE = ('HIGH', 'MEDIUM')

_KNOWN_SEVERITIES = ('HIGH', 'MEDIUM', 'LOW')
_SEVERITY_ORDER = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}


def _norm(value):
    return value.strip().upper() if isinstance(value, str) else None


def is_blocking(finding):
    """True if this finding should fail the gate.

    Fails closed: anything we cannot parse into a known severity counts as
    blocking, so a malformed reviewer response can never silently pass.
    """
    if not isinstance(finding, dict):
        return True
    severity = _norm(finding.get('severity'))
    if severity not in _KNOWN_SEVERITIES:
        return True
    if severity != BLOCKING_SEVERITY:
        return False
    confidence = _norm(finding.get('confidence'))
    if confidence is None:
        return True
    return confidence in BLOCKING_CONFIDENCE


def decide_verdict(findings):
    """Return (blocking, reason) for a list of findings."""
    if not isinstance(findings, list):
        return True, 'Malformed review response: findings was not a list.'

    blockers = [f for f in findings if is_blocking(f)]
    if not blockers:
        return False, f'AI review passed: no blocking findings ({len(findings)} reported).'

    titles = []
    for f in blockers:
        title = f.get('title') if isinstance(f, dict) else None
        titles.append(title if isinstance(title, str) and title else '<unparseable finding>')
    return True, f'AI review found {len(blockers)} blocking finding(s): ' + '; '.join(titles)


def render_findings(findings):
    """Render findings as markdown for the PR comment.

    Never raises — the comment must get posted even if the payload is odd,
    so a human can see what the reviewer actually said.
    """
    if not isinstance(findings, list) or not findings:
        return 'No findings reported.'

    def sort_key(f):
        severity = _norm(f.get('severity')) if isinstance(f, dict) else None
        return _SEVERITY_ORDER.get(severity, 99)

    lines = []
    for f in sorted(findings, key=sort_key):
        if not isinstance(f, dict):
            lines.append(f'- **[UNPARSEABLE]** `{f!r}`')
            continue
        severity = f.get('severity') or 'UNKNOWN'
        confidence = f.get('confidence') or 'Unknown'
        title = f.get('title') or '(no title)'
        detail = f.get('detail') or ''
        mark = ' **← blocks merge**' if is_blocking(f) else ''
        lines.append(f'- **[{severity}]** [Confidence: {confidence}] {title}{mark}')
        if detail:
            lines.append(f'  {detail}')
    return '\n'.join(lines)
