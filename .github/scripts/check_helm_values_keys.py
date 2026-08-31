"""Gate against Helm values overrides the chart no longer reads.

Helm merges a values file into the chart's defaults without validating it. A
key the chart renamed or dropped is silently ignored: `helm template` renders,
the dry-run passes, kubeconform is happy, and the override quietly does
nothing. `cluster/helm/loki/values.yaml` carried `monitoring.lokiCanary` long
after the chart hoisted it to a top-level `lokiCanary`, so a canary we thought
was off ran against a gateway we never deployed; `monitoring.selfMonitoring`
went the same way when chart 9.0.0 dropped it.

A key is accepted when the chart's own `values.yaml` defines it, or when its
nearest defined ancestor is an empty mapping or null. That is the chart's way
of saying "put anything here" (`resources: {}`, `nodeSelector: {}`).

Blocks named by --passthrough are skipped whole. Those are the values a chart
copies into some other program's config file rather than reading itself, so
chart defaults say nothing about which keys are valid; `loki:` is Loki's own
config file.

problems() is pure; main() does the I/O.
"""
import argparse
import sys

import yaml


def problems(overrides, defaults, passthrough=()):
    """Return human-readable defects in one values override.

    Walks every leaf path in `overrides` and reports the ones that `defaults`,
    the chart's own values.yaml, gives the chart no way to read.
    """
    found = []
    if not isinstance(overrides, dict):
        return found
    if not isinstance(defaults, dict):
        return ['chart defaults are not a mapping']

    def walk(node, default, path):
        for key, value in node.items():
            trail = path + [str(key)]
            dotted = '.'.join(trail)

            if len(trail) == 1 and key in passthrough:
                continue

            if default is None:
                # A null default is the chart inviting arbitrary keys.
                continue

            if not isinstance(default, dict):
                found.append(
                    f'{dotted} is set below {".".join(path)}, which the chart '
                    f'defines as a {type(default).__name__}, not a mapping')
                continue

            if key not in default:
                if default == {}:
                    # An empty mapping is the same invitation.
                    continue
                found.append(
                    f'{dotted} is not defined by the chart; it is merged in '
                    f'and then ignored')
                continue

            if isinstance(value, dict):
                walk(value, default[key], trail)

    walk(overrides, defaults, [])
    return sorted(found)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chart-values', required=True,
                        help="the chart's own values.yaml "
                             '(`helm show values <chart> --version <pin>`)')
    parser.add_argument('--overrides', required=True,
                        help='our values override for that chart')
    parser.add_argument('--passthrough', action='append', default=[],
                        metavar='KEY',
                        help='top-level block the chart copies verbatim into '
                             'another program\'s config; repeatable')
    args = parser.parse_args(argv)

    with open(args.chart_values) as fh:
        defaults = yaml.safe_load(fh)
    with open(args.overrides) as fh:
        overrides = yaml.safe_load(fh)

    errors = problems(overrides, defaults, tuple(args.passthrough))
    for error in errors:
        print(f'FAIL :: {args.overrides}: {error}')
    if errors:
        return 1

    print(f'OK :: {args.overrides} sets no key the chart ignores')
    return 0


if __name__ == '__main__':
    sys.exit(main())
