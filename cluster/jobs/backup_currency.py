#!/usr/bin/env python3
"""Weekly Longhorn backup currency check. See cluster/longhorn/README.md."""
import json
import sys
from datetime import datetime, timedelta, timezone

GROUP_LABEL = 'recurring-job-group.longhorn.io/default'
# The backups RecurringJob runs weekly; one missed run is a failure.
MAX_AGE = timedelta(days=8)


def parse(stamp):
    return datetime.fromisoformat(stamp.replace('Z', '+00:00'))


def in_group(volume):
    labels = volume['metadata'].get('labels') or {}
    return labels.get(GROUP_LABEL) == 'enabled'


def stale(volumes, backups, now):
    latest = {}
    for b in backups:
        status = b.get('status') or {}
        if status.get('state') != 'Completed' or \
                not status.get('backupCreatedAt'):
            continue
        name, when = status.get('volumeName'), parse(status['backupCreatedAt'])
        if name and (name not in latest or when > latest[name]):
            latest[name] = when

    found = []
    for v in filter(in_group, volumes):
        name = v['metadata']['name']
        k8s = (v.get('status') or {}).get('kubernetesStatus') or {}
        claim = f"{k8s.get('namespace', '?')}/{k8s.get('pvcName', '?')}"
        when = latest.get(name)
        if when is None:
            # A volume newer than one backup cycle may not have had its first.
            if now - parse(v['metadata']['creationTimestamp']) > MAX_AGE:
                found.append(f'{name} ({claim}) has no completed backup')
        elif now - when > MAX_AGE:
            found.append(f'{name} ({claim}) was last backed up '
                         f'{when.isoformat()}')
    return found


def main(argv, now=None):
    try:
        with open(argv[1], encoding='utf-8') as handle:
            volumes = json.load(handle).get('items') or []
        with open(argv[2], encoding='utf-8') as handle:
            backups = json.load(handle).get('items') or []
    except (OSError, ValueError) as exc:
        print(f'backup check could not read fetched state: {exc}',
              file=sys.stderr)
        return 1

    count = sum(1 for _ in filter(in_group, volumes))
    if count == 0:
        print('no Longhorn volume carries the default group', file=sys.stderr)
        return 1
    found = stale(volumes, backups, now or datetime.now(timezone.utc))
    if not found:
        print(f'all {count} default-group volumes backed up within 8 days.')
        return 0
    print(f'{len(found)} of {count} default-group volumes are not backed up:',
          file=sys.stderr)
    for reason in found:
        print(f'  {reason}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
