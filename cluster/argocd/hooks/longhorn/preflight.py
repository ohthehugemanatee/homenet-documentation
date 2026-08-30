#!/usr/bin/env python3
"""Longhorn PreSync gate. See cluster/argocd/CLAUDE.md."""
import json
import sys

# Excludes 'degraded': self-heals.
FAULTED = 'faulted'

FAILED_FILE_STATES = ('failed', 'failed-and-cleanup')


def blockers(volumes, backing_images):
    found = []

    for v in volumes:
        status = v.get('status') or {}
        # Detached volumes report 'unknown'.
        if status.get('robustness') == FAULTED:
            found.append(
                f"volume {v['metadata']['name']} is faulted")

    for b in backing_images:
        status = b.get('status') or {}
        disks = status.get('diskFileStatusMap') or {}
        bad = sorted(disk for disk, s in disks.items()
                     if (s or {}).get('state') in FAILED_FILE_STATES)
        if bad:
            found.append(
                f"backing image {b['metadata']['name']} has a failed disk "
                f"file on {', '.join(bad)}")

    return found


def load_items(path):
    with open(path, encoding='utf-8') as handle:
        return json.load(handle).get('items') or []


def main(argv):
    volumes_path, backing_images_path = argv[1], argv[2]

    try:
        volumes = load_items(volumes_path)
        backing_images = load_items(backing_images_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f'Longhorn preflight could not read fetched state: {exc}',
              file=sys.stderr)
        return 1

    found = blockers(volumes, backing_images)

    print(f'{len(volumes)} volumes, {len(backing_images)} backing images')
    if not found:
        print('Longhorn is ready to upgrade.')
        return 0

    print('Longhorn is not ready to upgrade:', file=sys.stderr)
    for reason in found:
        print(f'  {reason}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
