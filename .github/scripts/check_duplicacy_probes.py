"""Gate on the duplicacy startupProbe.

init.sh runs before duplicacy_web listens and liveness counts from container
start, so without a startupProbe a slow boot is killed in a loop.
"""
import os
import sys

import yaml

MANIFEST = 'cluster/services/duplicacy.yaml'
PORT = 3875
MIN_BUDGET_SECONDS = 600


def as_dict(value):
    return value if isinstance(value, dict) else {}


def duplicacy_container(doc):
    doc = as_dict(doc)
    if doc.get('kind') not in ('StatefulSet', 'Deployment'):
        return None
    if as_dict(doc.get('metadata')).get('name') != 'duplicacy':
        return None
    pod = as_dict(as_dict(as_dict(doc.get('spec')).get('template')).get('spec'))
    containers = pod.get('containers')
    for container in containers if isinstance(containers, list) else []:
        if as_dict(container).get('name') == 'duplicacy':
            return container
    return None


def count(probe, key, default):
    value = probe.get(key, default)
    return value if isinstance(value, int) else 0


def problems(container):
    probe = container.get('startupProbe')
    if not isinstance(probe, dict) or not probe:
        return ['startupProbe is missing']

    found = []
    if as_dict(probe.get('tcpSocket')).get('port') != PORT:
        found.append(f'startupProbe must be a tcpSocket on {PORT}')
    budget = count(probe, 'periodSeconds', 10) * count(probe, 'failureThreshold', 3)
    if budget < MIN_BUDGET_SECONDS:
        found.append(f'startupProbe allows {budget} s; it must allow at least '
                     f'{MIN_BUDGET_SECONDS} s')
    return found


def main():
    root = os.path.join(os.path.dirname(__file__), '..', '..')
    with open(os.path.join(root, MANIFEST)) as fh:
        containers = [c for c in map(duplicacy_container,
                                     yaml.safe_load_all(fh)) if c]
    if not containers:
        print(f'FAIL :: {MANIFEST}: no duplicacy container found')
        return 1

    errors = [e for c in containers for e in problems(c)]
    for error in errors:
        print(f'FAIL :: {MANIFEST}: {error}')
    if errors:
        return 1

    print(f'OK :: {MANIFEST}: startupProbe is a tcpSocket on {PORT} allowing '
          f'at least {MIN_BUDGET_SECONDS} s')
    return 0


if __name__ == '__main__':
    sys.exit(main())
