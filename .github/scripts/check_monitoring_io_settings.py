"""Gate that the monitoring stack's I/O settings reach the rendered chart.

Helm merges a values file without validating it, so a key the chart renamed or
moved is ignored rather than rejected. `check_helm_values_keys.py` catches that
by comparing against the chart's own values.yaml, but it cannot cover
kube-prometheus-stack's `grafana` block: grafana is a subchart whose values ship
`storageClassName` commented out, so every override of it reads as unreachable.

This checks the other end instead. Each setting below must be set in our
override AND carry that same value in the rendered manifest. A key the chart
stopped reading renders absent and fails here, and nothing needs editing when a
value is deliberately retuned.

problems() is pure; main() does the I/O.
"""
import argparse
import sys

import yaml

# (override path, rendered kind, rendered path). One row per setting whose
# whole point is disk or network I/O — see #298.
SETTINGS = (
    (('prometheus', 'prometheusSpec', 'scrapeInterval'),
     'Prometheus', ('spec', 'scrapeInterval')),
    (('prometheus', 'prometheusSpec', 'retentionSize'),
     'Prometheus', ('spec', 'retentionSize')),
    (('prometheus', 'prometheusSpec', 'storageSpec', 'volumeClaimTemplate',
      'spec', 'storageClassName'),
     'Prometheus',
     ('spec', 'storage', 'volumeClaimTemplate', 'spec', 'storageClassName')),
    (('alertmanager', 'alertmanagerSpec', 'storage', 'volumeClaimTemplate',
      'spec', 'storageClassName'),
     'Alertmanager',
     ('spec', 'storage', 'volumeClaimTemplate', 'spec', 'storageClassName')),
    (('grafana', 'persistence', 'storageClassName'),
     'PersistentVolumeClaim', ('spec', 'storageClassName')),
)

MISSING = object()


def dig(node, path):
    """Return the value at `path`, or MISSING if any step is absent."""
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return MISSING
        node = node[key]
    return node


def problems(overrides, rendered, settings=SETTINGS):
    """Return human-readable defects across the settings table.

    `rendered` is the list of documents helm template produced.
    """
    found = []
    by_kind = {}
    for doc in rendered:
        if isinstance(doc, dict) and doc.get('kind'):
            by_kind.setdefault(doc['kind'], []).append(doc)

    for override_path, kind, rendered_path in settings:
        dotted = '.'.join(override_path)
        want = dig(overrides, override_path)
        if want is MISSING:
            found.append(f'{dotted} is not set in the override')
            continue

        docs = by_kind.get(kind)
        if not docs:
            found.append(f'{dotted} is set to {want!r} but the chart rendered '
                         f'no {kind}')
            continue

        got = [dig(doc, rendered_path) for doc in docs]
        if want not in got:
            shown = [None if g is MISSING else g for g in got]
            found.append(
                f'{dotted} is set to {want!r} but {kind}.'
                f'{".".join(rendered_path)} rendered as {shown!r}; the chart '
                f'is not reading that key')

    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--overrides', required=True,
                        help='our values override for the chart')
    parser.add_argument('--rendered', required=True,
                        help='manifests from `helm template --version <pin>`')
    args = parser.parse_args(argv)

    with open(args.overrides) as fh:
        overrides = yaml.safe_load(fh)
    with open(args.rendered) as fh:
        rendered = list(yaml.safe_load_all(fh))

    errors = problems(overrides, rendered)
    for error in errors:
        print(f'FAIL :: {args.overrides}: {error}')
    if errors:
        return 1

    print(f'OK :: {len(SETTINGS)} I/O settings in {args.overrides} reach the '
          f'rendered chart')
    return 0


if __name__ == '__main__':
    sys.exit(main())
