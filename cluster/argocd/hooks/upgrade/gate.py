#!/usr/bin/env python3
"""Shared upgrade PreSync gate. See cluster/argocd/CLAUDE.md."""
import json
import sys
from datetime import datetime, timedelta, timezone

# A liveness failure shows up only as a restart.
RESTART_WINDOW = timedelta(minutes=15)


def blockers(workload, pods, now):
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
    return found


def main(argv, now=None):
    try:
        with open(argv[1], encoding='utf-8') as handle:
            workload = json.load(handle)
        with open(argv[2], encoding='utf-8') as handle:
            pods = json.load(handle).get('items') or []
    except (OSError, json.JSONDecodeError) as exc:
        print(f'upgrade gate could not read fetched state: {exc}',
              file=sys.stderr)
        return 1

    name = f"{workload['kind']}/{workload['metadata']['name']}"
    found = blockers(workload, pods, now or datetime.now(timezone.utc))
    if not found:
        print(f'{name} is ready to upgrade.')
        return 0

    print(f'{name} is not ready to upgrade:', file=sys.stderr)
    for reason in found:
        print(f'  {reason}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
