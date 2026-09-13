"""Gate Traefik's default TLS certificate on ArgoCD management.

`TLSStore/default` names the one Secret Traefik serves for every host without a
certificate of its own, which here is roughly eighteen names under
`*.berlin.vertesi.com`. That Secret comes from a standalone cert-manager
Certificate with no Ingress behind it, so ingress-shim cannot rebuild it the
way it rebuilds the annotation-derived certs.

The August 2026 cert-manager teardown deleted the CRDs and every object under
them. The hand-applied Certificate did not come back, cert-manager stopped
renewing a Secret it no longer knew about, and Traefik served the stale one
until its ninety days ran out (#391). An Application reconciling the manifest
is what keeps a teardown from costing TLS on every internal host again.

problems() is pure; main() does the I/O.
"""
import fnmatch
import glob
import os
import sys

import yaml

MANIFEST_GLOB = 'cluster/**/*.yaml'
APP_GLOB = 'cluster/argocd/apps/*.yaml'
CERT_GROUP = 'cert-manager.io/'
STORE_GROUP = 'traefik.io/'
SECRET_REF = 'secretName'


def expand_braces(pattern):
    """Expand `{a,b}` alternation the way ArgoCD's glob matcher does.

    fnmatch has no alternation, and `directory.include` is the only place this
    repo needs it.
    """
    open_at = pattern.find('{')
    if open_at == -1:
        return [pattern]
    close_at = pattern.find('}', open_at)
    if close_at == -1:
        return [pattern]

    head = pattern[:open_at]
    tail = pattern[close_at + 1:]
    expanded = []
    for choice in pattern[open_at + 1:close_at].split(','):
        expanded.extend(expand_braces(head + choice.strip() + tail))
    return expanded


def app_sources(doc):
    """Return the directory sources of one ArgoCD Application document."""
    if not isinstance(doc, dict) or doc.get('kind') != 'Application':
        return []
    spec = doc.get('spec')
    if not isinstance(spec, dict):
        return []

    found = spec.get('sources') or [spec.get('source')]
    return [s for s in found if isinstance(s, dict) and s.get('path')]


def covers(source, rel_path):
    """Whether one Application source reconciles the manifest at rel_path."""
    base = source['path'].rstrip('/')
    if os.path.commonpath([base, rel_path]) != base:
        return False

    rel = os.path.relpath(rel_path, base)
    directory = source.get('directory') or {}
    # recurse defaults off, so a nested file needs an explicit opt-in.
    if os.sep in rel and not directory.get('recurse'):
        return False

    include = directory.get('include')
    if include and not any(fnmatch.fnmatch(rel, p)
                           for p in expand_braces(include)):
        return False

    exclude = directory.get('exclude')
    if exclude and any(fnmatch.fnmatch(rel, p)
                       for p in expand_braces(exclude)):
        return False

    return True


def problems(stores, certificates, sources):
    """Return human-readable defects across the whole repo.

    stores and certificates are (path, name, cert_ref) triples, where cert_ref
    is the name of the Secret holding the certificate, never its contents.
    sources are the directory sources of every Application.
    """
    found = []
    for path, name, cert_ref in stores:
        if not any(covers(s, path) for s in sources):
            found.append(
                f'{path}: TLSStore {name!r} is not reconciled by any ArgoCD '
                f'Application, so nothing restores it once it is deleted')

        issuers = [c for c in certificates if c[2] == cert_ref]
        if not issuers:
            found.append(
                f'{path}: TLSStore {name!r} serves {cert_ref!r} by default, '
                f'and no Certificate manifest in cluster/ issues it')
            continue

        if any(any(covers(s, cert_path) for s in sources)
               for cert_path, _, _ in issuers):
            continue

        listed = ', '.join(sorted(c[0] for c in issuers))
        found.append(
            f'{path}: TLSStore {name!r} serves {cert_ref!r} by default, but '
            f'the Certificate issuing it ({listed}) is not reconciled by any '
            f'ArgoCD Application. A cert-manager teardown deletes it and '
            f'nothing brings it back (#391)')

    return found


def read(root, pattern):
    """Yield (relative path, document) for every YAML document under pattern."""
    for path in sorted(glob.glob(os.path.join(root, pattern), recursive=True)):
        rel = os.path.relpath(path, root)
        try:
            with open(path) as fh:
                documents = list(yaml.safe_load_all(fh))
        except yaml.YAMLError:
            # yamllint owns syntax; skip rather than double-report.
            continue
        for doc in documents:
            yield rel, doc


def main():
    root = os.path.join(os.path.dirname(__file__), '..', '..')
    stores, certificates = [], []

    for rel, doc in read(root, MANIFEST_GLOB):
        if not isinstance(doc, dict):
            continue
        api = doc.get('apiVersion') or ''
        name = (doc.get('metadata') or {}).get('name')
        spec = doc.get('spec')
        if not isinstance(spec, dict):
            continue

        # Both fields hold the name of a Secret, not its contents.
        if doc.get('kind') == 'TLSStore' and api.startswith(STORE_GROUP):
            cert_ref = (spec.get('defaultCertificate') or {}).get(SECRET_REF)
            if cert_ref:
                stores.append((rel, name, cert_ref))
        elif doc.get('kind') == 'Certificate' and api.startswith(CERT_GROUP):
            cert_ref = spec.get(SECRET_REF)
            if cert_ref:
                certificates.append((rel, name, cert_ref))

    sources = [s for _, doc in read(root, APP_GLOB) for s in app_sources(doc)]

    errors = problems(stores, certificates, sources)
    for error in errors:
        print(f'FAIL :: {error}')
    if errors:
        return 1

    print(f'OK :: {len(stores)} TLSStore(s) checked against '
          f'{len(certificates)} Certificate(s) and {len(sources)} '
          f'Application source(s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
