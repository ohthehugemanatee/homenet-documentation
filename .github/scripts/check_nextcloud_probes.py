"""Gate on the Nextcloud probes.

Readiness must be an httpGet on /status.php with a Host header that Nextcloud's
trusted_domains accepts. Liveness must not use /status.php: it needs MariaDB, so
a database outage would restart Nextcloud and a restart cannot fix it (#472).

problems() is pure; main() does the I/O.
"""
import os
import sys

import yaml

MANIFEST = 'cluster/services/nextcloud.yaml'
PATH = '/status.php'


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
    """Return one message per probe that breaks the readiness/liveness rule."""
    found = []
    http = as_dict(as_dict(container.get('readinessProbe')).get('httpGet'))
    headers = http.get('httpHeaders')
    has_host = any(as_dict(h).get('name') == 'Host'
                   for h in (headers if isinstance(headers, list) else []))
    if http.get('path') != PATH or not has_host:
        found.append(f'readinessProbe must be an httpGet on {PATH} with a Host '
                     f'header')

    liveness = container.get('livenessProbe')
    if not isinstance(liveness, dict):
        found.append('livenessProbe is missing')
    elif as_dict(liveness.get('httpGet')).get('path') == PATH:
        found.append(f'livenessProbe must not use {PATH}: it fails when '
                     f'MariaDB is down, and a restart does not fix that')
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

    print(f'OK :: {MANIFEST}: readiness is an httpGet on {PATH}, liveness '
          f'does not use it')
    return 0


if __name__ == '__main__':
    sys.exit(main())
