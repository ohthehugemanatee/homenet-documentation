#!/usr/bin/env python3
"""ArgoCD PreSync gate: refuse a Longhorn upgrade the cluster is not ready for.

Longhorn's own pre-upgrade check refuses to run past a faulted volume, and a
completed minor upgrade cannot be reverted. Reaching v1.12.1 from v1.7.2 takes
five hops (#281-#285), each an ArgoCD sync, so the check belongs on the sync
rather than in an operator's checklist.

Runs in-cluster on the `longhorn-preflight` ServiceAccount, which holds get and
list on these two collections and nothing else. Exits non-zero to abort the
sync.

Filtering is client-side because it has to be: field selectors reach only
metadata.name and metadata.namespace on a custom resource unless the CRD
declares `selectableFields` (KEP-4358), and Longhorn declares it on none of its
CRDs. The API returns the collection whole.

blockers() and collection_url() are pure; main() does the I/O.
"""
import json
import os
import ssl
import sys
import urllib.request

GROUP = 'longhorn.io'
VERSION = 'v1beta2'
NAMESPACE = 'longhorn-system'

SA = '/var/run/secrets/kubernetes.io/serviceaccount'

# longhorn.io/v1beta2 Volume.status.robustness. 'degraded' is deliberately not
# here: Longhorn rebuilds the replica without help.
FAULTED = 'faulted'

# BackingImage.status.diskFileStatusMap[*].state. The other states are
# 'ready', 'starting', 'in-progress' and 'unknown'.
FAILED_FILE_STATES = ('failed', 'failed-and-cleanup')


def collection_url(base, plural):
    """URL of one namespaced Longhorn collection."""
    return (f'{base}/apis/{GROUP}/{VERSION}'
            f'/namespaces/{NAMESPACE}/{plural}')


def blockers(volumes, backing_images):
    """Return a human-readable reason for each thing blocking an upgrade."""
    found = []

    for v in volumes:
        status = v.get('status') or {}
        # Robustness is only meaningful while an engine is running. A detached
        # volume reports 'unknown' as a matter of course, so only 'faulted' is
        # read as a defect -- it is set on a volume whose replicas are all
        # unusable, attached or not.
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


def fetch(base, token, context, plural):
    """GET one collection, returning its items."""
    request = urllib.request.Request(
        collection_url(base, plural),
        headers={'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(request, context=context,
                                timeout=30) as response:
        return json.load(response).get('items') or []


def main():
    host = os.environ['KUBERNETES_SERVICE_HOST']
    port = os.environ.get('KUBERNETES_SERVICE_PORT_HTTPS', '443')
    base = f'https://{host}:{port}'

    with open(f'{SA}/token', encoding='utf-8') as handle:
        token = handle.read().strip()
    context = ssl.create_default_context(cafile=f'{SA}/ca.crt')

    volumes = fetch(base, token, context, 'volumes')
    backing_images = fetch(base, token, context, 'backingimages')

    found = blockers(volumes, backing_images)

    print(f'{len(volumes)} volumes, {len(backing_images)} backing images')
    if not found:
        print('Longhorn is ready to upgrade.')
        return 0

    # Printed one per line so a blocked sync says what to fix, not just that it
    # was blocked.
    print('Longhorn is not ready to upgrade:', file=sys.stderr)
    for reason in found:
        print(f'  {reason}', file=sys.stderr)
    print("Longhorn's own pre-upgrade check refuses to run past these, and a "
          'completed minor upgrade cannot be reverted.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
