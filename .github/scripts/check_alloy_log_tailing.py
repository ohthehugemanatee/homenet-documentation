"""Gate that Alloy tails pod logs from disk, never through the kube-apiserver.

`loki.source.kubernetes` streams every container's log content through the
apiserver, which proxies to the kubelet. On the 4-core Pi control planes that
saturates k3s-server; the kubelet proxy then 502s, Alloy retries every tailer,
and the retry storm feeds the saturation that caused it (#303).

`loki.source.file` reads the same lines off the node's own disk and never
touches the apiserver, so this asserts the rendered chart still does that:

- the config declares the file-tailing components and no apiserver-streaming one
- the DaemonSet mounts every host path those tails resolve through

The mounts are load-bearing and easy to lose. On the Pis `/var/log/pods` is a
symlink to `/mnt/usb/log/pods`, so mounting `/var/log` alone leaves the symlink
dangling inside the container and collection silently yields nothing.

problems() is pure; main() does the I/O.
"""
import argparse
import sys

import yaml

CONFIG_MAP = 'alloy'
CONFIG_KEY = 'config.alloy'
CONTAINER = 'alloy'

# Components that must appear in the rendered Alloy config.
REQUIRED_COMPONENTS = (
    'local.file_match',
    'loki.source.file',
    # containerd writes CRI-format lines; without this stage the timestamp and
    # stream stay embedded in the message.
    'stage.cri',
)

# Components that must not: each streams log content through the apiserver.
FORBIDDEN_COMPONENTS = (
    'loki.source.kubernetes',
)

# mountPath -> hostPath. Both are needed on the Pi control planes, where
# /var/log/pods is a symlink onto the USB disk.
REQUIRED_MOUNTS = {
    '/var/log': '/var/log',
    '/mnt/usb/log': '/mnt/usb/log',
}


def docs_of_kind(rendered, kind):
    """Return the rendered documents of one kind."""
    return [doc for doc in rendered
            if isinstance(doc, dict) and doc.get('kind') == kind]


def config_problems(rendered):
    """Return defects in the Alloy river config the chart rendered."""
    for doc in docs_of_kind(rendered, 'ConfigMap'):
        if doc.get('metadata', {}).get('name') != CONFIG_MAP:
            continue
        config = doc.get('data', {}).get(CONFIG_KEY)
        if config is None:
            return [f'ConfigMap/{CONFIG_MAP} has no {CONFIG_KEY} key']
        found = [f'{CONFIG_KEY} does not declare {component}, so pod logs are '
                 f'not tailed from disk'
                 for component in REQUIRED_COMPONENTS
                 if component not in config]
        found += [f'{CONFIG_KEY} declares {component}, which streams log '
                  f'content through the kube-apiserver'
                  for component in FORBIDDEN_COMPONENTS
                  if component in config]
        return found
    return [f'the chart rendered no ConfigMap/{CONFIG_MAP}']


def mount_problems(rendered):
    """Return defects in the DaemonSet's host log mounts."""
    daemonsets = docs_of_kind(rendered, 'DaemonSet')
    if not daemonsets:
        return ['the chart rendered no DaemonSet; Alloy must run on every '
                'node to read that node\'s logs']

    found = []
    for doc in daemonsets:
        spec = doc.get('spec', {}).get('template', {}).get('spec', {})
        volumes = {vol.get('name'): vol.get('hostPath', {}).get('path')
                   for vol in spec.get('volumes') or []}
        containers = [c for c in spec.get('containers') or []
                      if c.get('name') == CONTAINER]
        if not containers:
            found.append(f'the DaemonSet has no {CONTAINER} container')
            continue

        mounts = {m.get('mountPath'): m
                  for m in containers[0].get('volumeMounts') or []}
        for mount_path, host_path in sorted(REQUIRED_MOUNTS.items()):
            mount = mounts.get(mount_path)
            if mount is None:
                found.append(f'the {CONTAINER} container does not mount '
                             f'{mount_path}; tails resolving through it read '
                             f'nothing')
                continue
            if not mount.get('readOnly'):
                found.append(f'{mount_path} is mounted writable; log '
                             f'collection only ever reads')
            backing = volumes.get(mount.get('name'))
            if backing != host_path:
                found.append(f'{mount_path} is backed by {backing!r}, not the '
                             f'host\'s {host_path!r}')
    return found


def problems(rendered):
    """Return every defect across config and mounts."""
    return config_problems(rendered) + mount_problems(rendered)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rendered', required=True,
                        help='manifests from `helm template --version <pin>`')
    args = parser.parse_args(argv)

    with open(args.rendered) as fh:
        rendered = list(yaml.safe_load_all(fh))

    errors = problems(rendered)
    for error in errors:
        print(f'FAIL :: {args.rendered}: {error}')
    if errors:
        return 1

    print(f'OK :: Alloy tails pod logs from disk, with '
          f'{len(REQUIRED_MOUNTS)} host log paths mounted read-only')
    return 0


if __name__ == '__main__':
    sys.exit(main())
