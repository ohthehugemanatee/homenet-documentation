#!/usr/bin/env python3
"""Shared upgrade PreSync gate. See cluster/argocd/CLAUDE.md."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

# A liveness failure shows up only as a restart.
RESTART_WINDOW = timedelta(minutes=15)


def blockers(workload, pods, now, integrity=None):
    spec = workload.get('spec') or {}
    status = workload.get('status') or {}
    want = spec.get('replicas', 1)
    if want < 1:
        return [f'scaled to {want} replicas']

    found = []
    if status.get('observedGeneration', 0) < \
            workload['metadata'].get('generation', 0):
        found.append('the controller has not observed the latest spec')
    for field in ('readyReplicas', 'updatedReplicas'):
        if status.get(field, 0) != want:
            found.append(f'{field} is {status.get(field, 0)}, want {want}')

    selector = (spec.get('selector') or {}).get('matchLabels')
    if not selector:
        found.append('selector has no matchLabels to find the pods by')
        return found
    for pod in pods:
        meta = pod['metadata']
        labels = meta.get('labels') or {}
        if meta.get('deletionTimestamp') or \
                any(labels.get(k) != v for k, v in selector.items()):
            continue
        pod_status = pod.get('status') or {}
        if not any(c.get('type') == 'Ready' and c.get('status') == 'True'
                   for c in pod_status.get('conditions') or []):
            found.append(f"pod {meta['name']} is not Ready")
        for container in pod_status.get('containerStatuses') or []:
            finished = ((container.get('lastState') or {}).get('terminated')
                        or {}).get('finishedAt')
            if finished and now - datetime.fromisoformat(
                    finished.replace('Z', '+00:00')) < RESTART_WINDOW:
                found.append(f"container {container['name']} in pod "
                             f"{meta['name']} restarted at {finished}")
    if integrity and integrity[0] != 0:
        lines = [line for line in integrity[1].splitlines() if line.strip()]
        found.append(f'integrity check exited {integrity[0]}'
                     + (f': {lines[-1]}' if lines else ''))
    return found


def main(argv, now=None):
    try:
        with open(argv[1], encoding='utf-8') as handle:
            workload = json.load(handle)
        with open(argv[2], encoding='utf-8') as handle:
            pods = json.load(handle).get('items') or []
        integrity = None
        # The fetch writes these only when INTEGRITY_COMMAND is set.
        if len(argv) > 4 and os.path.exists(argv[3]):
            with open(argv[3], encoding='utf-8') as handle:
                rc = int(handle.read())
            with open(argv[4], encoding='utf-8') as handle:
                integrity = (rc, handle.read())
    except (OSError, ValueError) as exc:
        print(f'upgrade gate could not read fetched state: {exc}',
              file=sys.stderr)
        return 1

    name = f"{workload['kind']}/{workload['metadata']['name']}"
    found = blockers(workload, pods, now or datetime.now(timezone.utc),
                     integrity)
    if not found:
        print(f'{name} is ready to upgrade.')
        return 0

    if integrity and integrity[0] != 0:
        print(integrity[1], file=sys.stderr)
    print(f'{name} is not ready to upgrade:', file=sys.stderr)
    for reason in found:
        print(f'  {reason}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
