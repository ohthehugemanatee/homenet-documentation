"""Structural gate for the Longhorn RecurringJob manifests.

The JSON Schema store has no longhorn.io schema, so kubeconform's
--ignore-missing-schemas skips these manifests entirely. A typo'd task, an empty
`groups`, or a four-field cron lints clean and then schedules nothing. This
checks what a schema would have, and asserts each job is in
cluster/longhorn/README.md so the table cannot drift from the manifests.

problems() and undocumented() are pure; main() does the I/O.
"""
import glob
import os
import re
import sys

import yaml

MANIFEST_GLOB = 'cluster/longhorn/*.yaml'
README = 'cluster/longhorn/README.md'
NAMESPACE = 'longhorn-system'

# longhorn.io/v1beta2 RecurringJobSpec.task
TASKS = ('snapshot', 'snapshot-cleanup', 'snapshot-delete',
         'backup', 'backup-force-create', 'filesystem-trim')


def problems(doc):
    """Return a list of human-readable defects in one RecurringJob document."""
    found = []
    meta = doc.get('metadata') or {}
    spec = doc.get('spec') or {}

    if not meta.get('name'):
        found.append('metadata.name is missing')
    # Repo rule: metadata.namespace is always explicit (cluster/CLAUDE.md).
    if meta.get('namespace') != NAMESPACE:
        found.append(f'metadata.namespace must be {NAMESPACE!r}, '
                     f'got {meta.get("namespace")!r}')

    task = spec.get('task')
    if task not in TASKS:
        found.append(f'spec.task {task!r} is not one of {", ".join(TASKS)}')

    cron = spec.get('cron')
    if not isinstance(cron, str) or len(cron.split()) != 5:
        found.append(f'spec.cron {cron!r} is not a 5-field cron expression')

    groups = spec.get('groups')
    if not isinstance(groups, list) or not groups:
        # Longhorn runs the job against nothing rather than erroring.
        found.append(f'spec.groups {groups!r} is empty or missing')

    retain = spec.get('retain')
    if not isinstance(retain, int) or isinstance(retain, bool) or retain < 0:
        found.append(f'spec.retain {retain!r} is not a non-negative integer')

    concurrency = spec.get('concurrency')
    if (not isinstance(concurrency, int) or isinstance(concurrency, bool)
            or concurrency < 1):
        found.append(f'spec.concurrency {concurrency!r} is not a positive integer')

    return found


def undocumented(names, readme_text):
    """Return the job names with no `name` entry in the README schedule table.

    Fenced blocks are stripped first: their ``` runs otherwise pair up with the
    prose backticks around them and swallow the table whole. Spans are matched
    without newlines for the same reason.
    """
    prose = re.sub(r'```.*?```', '', readme_text, flags=re.DOTALL)
    documented = set(re.findall(r'`([^`\n]+)`', prose))
    return [n for n in names if n not in documented]


def main():
    root = os.path.join(os.path.dirname(__file__), '..', '..')
    jobs = []
    errors = []

    for path in sorted(glob.glob(os.path.join(root, MANIFEST_GLOB))):
        rel = os.path.relpath(path, root)
        with open(path) as fh:
            for doc in yaml.safe_load_all(fh):
                if not isinstance(doc, dict) or doc.get('kind') != 'RecurringJob':
                    continue
                name = (doc.get('metadata') or {}).get('name')
                jobs.append(name)
                for problem in problems(doc):
                    errors.append(f'{rel}: {name}: {problem}')

    if not jobs:
        print(f'FAIL :: no RecurringJob found in {MANIFEST_GLOB}')
        return 1

    with open(os.path.join(root, README)) as fh:
        for name in undocumented(jobs, fh.read()):
            errors.append(f'{README}: {name} is not in the schedule table')

    for error in errors:
        print(f'FAIL :: {error}')
    if errors:
        return 1

    print(f'OK :: {len(jobs)} RecurringJob(s) valid and documented: '
          f'{", ".join(jobs)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
