"""Pick the known-exception entries that apply to a PR's touched paths."""

import re

import yaml

_HEADER = re.compile(r'^diff --git a/(.+) b/(.+)$', re.MULTILINE)


def touched_paths(diff):
    """Old and new paths from the diff's `diff --git` headers."""
    return {path for pair in _HEADER.findall(diff) for path in pair}


def _matches(files, paths):
    if not files:
        return True
    return any(p == f or (f.endswith('/') and p.startswith(f))
               for f in files for p in paths)


def exceptions_for_paths(text, paths):
    """Return (yaml_text, kept, total) for the entries whose `files` match `paths`.

    A file that does not parse comes back unchanged with kept and total None:
    a broken exceptions file costs tokens, never a missing exception.
    """
    try:
        entries = yaml.safe_load(text)['exceptions']
        kept = [e for e in entries if _matches(e.get('files'), paths)]
    except (yaml.YAMLError, KeyError, TypeError, AttributeError):
        return text, None, None
    if not kept:
        return '', 0, len(entries)
    dumped = yaml.safe_dump({'exceptions': kept}, sort_keys=False, allow_unicode=True, width=100)
    return dumped, len(kept), len(entries)
