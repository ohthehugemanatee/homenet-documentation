"""Gate on the mariadb readinessProbe.

The image init starts a throwaway server and stops it seconds later, so a single
passing probe can land just before that shutdown. Two passes in a row cannot.
"""
import os
import sys

import yaml

MANIFEST = 'cluster/services/mariadb.yaml'
MIN_SUCCESS_THRESHOLD = 2


def as_dict(value):
    return value if isinstance(value, dict) else {}


def mariadb_container(doc):
    doc = as_dict(doc)
    if doc.get('kind') not in ('StatefulSet', 'Deployment'):
        return None
    if as_dict(doc.get('metadata')).get('name') != 'mariadb':
        return None
    pod = as_dict(as_dict(as_dict(doc.get('spec')).get('template')).get('spec'))
    containers = pod.get('containers')
    for container in containers if isinstance(containers, list) else []:
        if as_dict(container).get('name') == 'mariadb':
            return container
    return None


def problems(container):
    probe = container.get('readinessProbe')
    if not isinstance(probe, dict) or not probe:
        return ['readinessProbe is missing']

    threshold = probe.get('successThreshold', 1)
    if not isinstance(threshold, int) or threshold < MIN_SUCCESS_THRESHOLD:
        return [f'readinessProbe successThreshold must be at least '
                f'{MIN_SUCCESS_THRESHOLD}']
    return []


def main():
    root = os.path.join(os.path.dirname(__file__), '..', '..')
    with open(os.path.join(root, MANIFEST)) as fh:
        containers = [c for c in map(mariadb_container,
                                     yaml.safe_load_all(fh)) if c]
    if not containers:
        print(f'FAIL :: {MANIFEST}: no mariadb container found')
        return 1

    errors = [e for c in containers for e in problems(c)]
    for error in errors:
        print(f'FAIL :: {MANIFEST}: {error}')
    if errors:
        return 1

    print(f'OK :: {MANIFEST}: readinessProbe needs at least '
          f'{MIN_SUCCESS_THRESHOLD} passes in a row')
    return 0


if __name__ == '__main__':
    sys.exit(main())
