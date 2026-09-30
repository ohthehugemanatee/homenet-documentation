#!/usr/bin/env python3
"""Fail when the snapshot-controller pin and Longhorn's csi-snapshotter disagree.

The controller must be the external-snapshotter release that matches the
sidecar the pinned Longhorn chart deploys, so the two only ever move together.
Every git ref and the image tag in the kustomization are checked: upstream's
deploy manifest can lag its own tag, so the ref alone does not fix the image.

Usage: check_snapshotter_pin.py <helm-template-output-of-longhorn.yaml>

problems() and longhorn_snapshotter_version() are pure; main() does the I/O.
"""
import re
import sys
from pathlib import Path

import yaml

KUSTOMIZATION = Path('cluster/operators/snapshot-controller/kustomization.yaml')
UPSTREAM = 'github.com/kubernetes-csi/external-snapshotter'
IMAGE = 'registry.k8s.io/sig-storage/snapshot-controller'
RELEASE = re.compile(r'v\d+\.\d+\.\d+')


def longhorn_snapshotter_version(docs):
    """The vX.Y.Z of the CSI_SNAPSHOTTER_IMAGE Longhorn's driver deployer gets."""
    for doc in docs:
        if not doc or doc.get('kind') != 'Deployment':
            continue
        pod = doc['spec']['template']['spec']
        for container in pod.get('containers') or []:
            for env in container.get('env') or []:
                if env.get('name') == 'CSI_SNAPSHOTTER_IMAGE':
                    # Longhorn may suffix a rebuild date; the release is the prefix.
                    match = RELEASE.match(env['value'].rsplit(':', 1)[-1])
                    return match.group(0) if match else None
    return None


def problems(longhorn, kustomization):
    """Human-readable disagreements between Longhorn's version and every pin."""
    if longhorn is None:
        return ['the Longhorn render carries no CSI_SNAPSHOTTER_IMAGE to compare against']
    found = []
    refs = [r for r in kustomization.get('resources') or [] if UPSTREAM in r]
    if not refs:
        found.append(f'no {UPSTREAM} resources in {KUSTOMIZATION}')
    for ref in refs:
        pinned = ref.partition('?ref=')[2]
        if pinned != longhorn:
            found.append(f'{ref} is pinned to {pinned!r}, Longhorn ships {longhorn}')
    images = [i for i in kustomization.get('images') or [] if i.get('name') == IMAGE]
    if not images:
        found.append(f'no images entry for {IMAGE}; upstream\'s manifest does not track its own tag')
    for image in images:
        if image.get('newTag') != longhorn:
            found.append(f'{IMAGE} is pinned to {image.get("newTag")!r}, Longhorn ships {longhorn}')
    return found


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    longhorn = longhorn_snapshotter_version(yaml.safe_load_all(Path(argv[1]).read_text()))
    kustomization = yaml.safe_load(KUSTOMIZATION.read_text())
    found = problems(longhorn, kustomization)
    for problem in found:
        print(f'FAIL :: {problem}')
    if found:
        print('Bump the snapshot-controller pin in the same PR as the Longhorn chart.')
        return 1
    print(f'OK :: snapshot-controller pinned to {longhorn}, matching Longhorn\'s csi-snapshotter')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
