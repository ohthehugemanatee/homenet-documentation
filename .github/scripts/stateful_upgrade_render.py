"""Rewrite an app's manifests to run in k3d on local-path storage."""
import argparse
import glob
import os
import sys

import yaml

STORAGE_CLASS = 'local-path'
DROPPED = {'Ingress', 'ServersTransport', 'IngressRoute', 'PersistentVolume'}
CAPS = {'cpu': 0.25, 'memory': 512 * 2**20}
CAP_TEXT = {'cpu': '250m', 'memory': '512Mi'}
UNITS = {'Ki': 2**10, 'Mi': 2**20, 'Gi': 2**30, 'Ti': 2**40,
         'K': 10**3, 'M': 10**6, 'G': 10**9, 'T': 10**12, 'k': 10**3,
         'm': 1e-3}


def quantity(text):
    text = str(text)
    for suffix, factor in UNITS.items():
        if text.endswith(suffix):
            return float(text[:-len(suffix)]) * factor
    return float(text)


def nfs_claim_names(storage_dir):
    names = set()
    for path in sorted(glob.glob(os.path.join(storage_dir, '*.yaml'))):
        with open(path) as fh:
            names.update(d['metadata']['name'] for d in yaml.safe_load_all(fh)
                         if d and d.get('kind') == 'PersistentVolumeClaim')
    return names


def is_static_claim(doc):
    return (doc.get('kind') == 'PersistentVolumeClaim'
            and (doc.get('spec') or {}).get('volumeName') is not None)


def pod_specs(node):
    if isinstance(node, dict):
        if isinstance(node.get('containers'), list):
            yield node
        for value in node.values():
            yield from pod_specs(value)
    elif isinstance(node, list):
        for value in node:
            yield from pod_specs(value)


def claims(doc):
    yield from (doc.get('spec') or {}).get('volumeClaimTemplates') or []
    if doc.get('kind') == 'PersistentVolumeClaim':
        yield doc


def cap_requests(pod):
    for key in ('containers', 'initContainers'):
        for item in pod.get(key) or []:
            requests = (item.get('resources') or {}).get('requests') or {}
            for name, cap in CAPS.items():
                if name in requests and quantity(requests[name]) > cap:
                    requests[name] = CAP_TEXT[name]


def local_volume(volume, nfs):
    claim = (volume.get('persistentVolumeClaim') or {}).get('claimName')
    return {'name': volume['name'], 'emptyDir': {}} if claim in nfs else volume


def render(docs, nfs_claims):
    nfs = set(nfs_claims) | {d['metadata']['name'] for d in docs
                             if is_static_claim(d)}
    kept = [d for d in docs
            if d.get('kind') not in DROPPED and not is_static_claim(d)]
    for doc in kept:
        for claim in claims(doc):
            claim.setdefault('spec', {})['storageClassName'] = STORAGE_CLASS
        for pod in pod_specs(doc):
            if 'volumes' in pod:
                pod['volumes'] = [local_volume(v, nfs) for v in pod['volumes']]
            cap_requests(pod)
    return kept


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage', default='cluster/storage',
                        help='directory whose claims are NFS-backed')
    parser.add_argument('manifests', nargs='+')
    args = parser.parse_args(argv)
    docs = []
    for path in args.manifests:
        with open(path) as fh:
            docs.extend(d for d in yaml.safe_load_all(fh) if d)
    yaml.safe_dump_all(render(docs, nfs_claim_names(args.storage)),
                       sys.stdout, sort_keys=False)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
