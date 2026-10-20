#!/usr/bin/env python3
"""Picks the weekly restore check's backup. See cluster/longhorn/README.md."""
import json
import os
import random
import sys
from datetime import datetime


def claim_of(volume):
    k8s = (volume.get('status') or {}).get('kubernetesStatus') or {}
    return f"{k8s.get('namespace')}/{k8s.get('pvcName')}"


def created(backup):
    return datetime.fromisoformat(
        backup['status']['backupCreatedAt'].replace('Z', '+00:00'))


def choose(volumes, backups, claims, rng):
    by_volume = {}
    for b in backups:
        status = b.get('status') or {}
        if status.get('state') == 'Completed' and \
                status.get('backupCreatedAt'):
            by_volume.setdefault(status.get('volumeName'), []).append(b)

    candidates = sorted((claim_of(v), v['metadata']['name']) for v in volumes
                        if claim_of(v) in claims
                        and v['metadata']['name'] in by_volume)
    if not candidates:
        return None
    claim, volume = rng.choice(candidates)
    newest = max(by_volume[volume], key=created)
    return {'CLAIM': claim,
            'SNAPSHOT_HANDLE': f"bak://{volume}/{newest['metadata']['name']}",
            'SIZE': newest['status']['volumeSize']}


def main(argv, rng=random):
    claims = [c for c in os.environ.get('RESTORE_CLAIMS', '').split(',') if c]
    if not claims:
        print('no restore target configured; skipping restore')
        return 0
    try:
        with open(argv[1], encoding='utf-8') as handle:
            volumes = json.load(handle).get('items') or []
        with open(argv[2], encoding='utf-8') as handle:
            backups = json.load(handle).get('items') or []
    except (OSError, ValueError) as exc:
        print(f'restore check could not read fetched state: {exc}',
              file=sys.stderr)
        return 1

    chosen = choose(volumes, backups, claims, rng)
    if chosen is None:
        print(f"no completed backup for any of {', '.join(claims)}",
              file=sys.stderr)
        return 1
    with open(argv[3], 'w', encoding='utf-8') as handle:
        handle.writelines(f"{k}='{v}'\n" for k, v in chosen.items())
    print(f"chose {chosen['SNAPSHOT_HANDLE']} of {chosen['CLAIM']}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
