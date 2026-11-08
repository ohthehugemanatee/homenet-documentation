"""Gate on the Nextcloud HTTP probes.

nginx stays up while PHP is starved, so a `pgrep nginx` probe passes through an
outage (#472). Both probes must be an httpGet on /status.php with a Host header
that Nextcloud's trusted_domains accepts.

problems() is pure; main() does the I/O.
"""
import os
import sys

import yaml

MANIFEST = 'cluster/services/nextcloud.yaml'
PATH = '/status.php'
PROBES = ('readinessProbe', 'livenessProbe')


def as_dict(value):
    return value if isinstance(value, dict) else {}


def nextcloud_container(doc):
    """Return the `nextcloud` container of the `nextcloud` workload, or None."""
    doc = as_dict(doc)
    if doc.get('kind') not in ('StatefulSet', 'Deployment'):
        return None
    if as_dict(doc.get('metadata')).get('name') != 'nextcloud':
        return None
    pod = as_dict(as_dict(as_dict(doc.get('spec')).get('template')).get('spec'))
    containers = pod.get('containers')
    for container in containers if isinstance(containers, list) else []:
        if as_dict(container).get('name') == 'nextcloud':
            return container
    return None


def problems(container):
    """Return one message per probe that is not an httpGet on PATH with Host."""
    found = []
    for name in PROBES:
        http = as_dict(as_dict(container.get(name)).get('httpGet'))
        headers = http.get('httpHeaders')
        has_host = any(as_dict(h).get('name') == 'Host'
                       for h in (headers if isinstance(headers, list) else []))
        if http.get('path') != PATH or not has_host:
            found.append(f'{name} must be an httpGet on {PATH} with a Host '
                         f'header')
    return found


def main():
    root = os.path.join(os.path.dirname(__file__), '..', '..')
    with open(os.path.join(root, MANIFEST)) as fh:
        containers = [c for c in map(nextcloud_container,
                                     yaml.safe_load_all(fh)) if c]
    if not containers:
        print(f'FAIL :: {MANIFEST}: no nextcloud container found')
        return 1

    errors = [e for c in containers for e in problems(c)]
    for error in errors:
        print(f'FAIL :: {MANIFEST}: {error}')
    if errors:
        return 1

    print(f'OK :: {MANIFEST}: readiness and liveness probes are httpGet on '
          f'{PATH}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
