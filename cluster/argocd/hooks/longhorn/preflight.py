#!/usr/bin/env python3
"""Longhorn PreSync gate. See cluster/argocd/CLAUDE.md."""
import json
import os
import ssl
import sys
import urllib.request

GROUP = 'longhorn.io'
VERSION = 'v1beta2'
NAMESPACE = 'longhorn-system'

SA = '/var/run/secrets/kubernetes.io/serviceaccount'

# Excludes 'degraded': self-heals.
FAULTED = 'faulted'

FAILED_FILE_STATES = ('failed', 'failed-and-cleanup')


def collection_url(base, plural):
    return (f'{base}/apis/{GROUP}/{VERSION}'
            f'/namespaces/{NAMESPACE}/{plural}')


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


def fetch(base, token, context, plural):
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

    print('Longhorn is not ready to upgrade:', file=sys.stderr)
    for reason in found:
        print(f'  {reason}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
