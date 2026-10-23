"""Gate that the Pushover receiver's notification text names the firing workload.

Renders the receiver's `title` and `message` with Alertmanager's own template
engine (`amtool template render`) against sample alerts carrying the stock
kube-prometheus-stack annotations, and compares the result with the expected
text. A message that falls back to the generic `summary`, or runs a group's
alerts together on one line, renders differently and fails.

The sample descriptions are as Prometheus renders them with no `cluster` label
set, which leaves the stock "on cluster ." clause for the template to drop.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

import yaml


def alert(name, labels, summary, description=None):
    annotations = {'summary': summary}
    if description:
        annotations['description'] = description
    return {'labels': {'alertname': name, **labels}, 'annotations': annotations}


STS_SUMMARY = 'StatefulSet has not matched the expected number of replicas.'

SAMPLES = (
    {
        'name': 'DaemonSet',
        'title': 'k8s alert: KubeDaemonSetRolloutStuck',
        'alerts': [alert(
            'KubeDaemonSetRolloutStuck',
            {'namespace': 'monitoring', 'daemonset': 'alloy'},
            'DaemonSet rollout is stuck.',
            'DaemonSet monitoring/alloy has not finished or progressed for '
            'at least 15m on cluster .')],
        'want': ['DaemonSet monitoring/alloy has not finished or progressed '
                 'for at least 15m.'],
    },
    {
        'name': 'StatefulSet',
        'title': 'k8s alert: KubeStatefulSetReplicasMismatch',
        'alerts': [alert(
            'KubeStatefulSetReplicasMismatch',
            {'namespace': 'default', 'statefulset': 'prowlarr'},
            STS_SUMMARY,
            'StatefulSet default/prowlarr has not matched the expected number '
            'of replicas for longer than 15 minutes on cluster .')],
        'want': ['StatefulSet default/prowlarr has not matched the expected '
                 'number of replicas for longer than 15 minutes.'],
    },
    {
        'name': 'Pod',
        'title': 'k8s alert: KubePodCrashLooping',
        'alerts': [alert(
            'KubePodCrashLooping',
            {'namespace': 'default', 'pod': 'prowlarr-0',
             'container': 'prowlarr'},
            'Pod is crash looping.',
            'Pod default/prowlarr-0 (prowlarr) is in waiting state '
            '(reason: "CrashLoopBackOff") on cluster .')],
        'want': ['Pod default/prowlarr-0 (prowlarr) is in waiting state '
                 '(reason: "CrashLoopBackOff").'],
    },
    {
        'name': 'no description',
        'title': 'k8s alert: HomelabPodNotReady',
        'alerts': [alert(
            'HomelabPodNotReady',
            {'namespace': 'default', 'pod': 'prowlarr-0'},
            'Pod default/prowlarr-0 has been not-ready for more than '
            '5 minutes.')],
        'want': ['Pod default/prowlarr-0 has been not-ready for more than '
                 '5 minutes.'],
    },
    {
        'name': 'group of two',
        'title': 'k8s alert: KubeStatefulSetReplicasMismatch',
        'alerts': [
            alert('KubeStatefulSetReplicasMismatch',
                  {'namespace': 'default', 'statefulset': 'prowlarr'},
                  STS_SUMMARY,
                  'StatefulSet default/prowlarr has not matched the expected '
                  'number of replicas for longer than 15 minutes on cluster .'),
            alert('KubeStatefulSetReplicasMismatch',
                  {'namespace': 'default', 'statefulset': 'lidarr'},
                  STS_SUMMARY,
                  'StatefulSet default/lidarr has not matched the expected '
                  'number of replicas for longer than 15 minutes on cluster .'),
        ],
        'want': ['StatefulSet default/prowlarr has not matched the expected '
                 'number of replicas for longer than 15 minutes.',
                 'StatefulSet default/lidarr has not matched the expected '
                 'number of replicas for longer than 15 minutes.'],
    },
    {
        'name': 'cluster label set',
        'title': 'k8s alert: KubeStatefulSetReplicasMismatch',
        'alerts': [alert(
            'KubeStatefulSetReplicasMismatch',
            {'namespace': 'default', 'statefulset': 'radarr',
             'cluster': 'home'},
            STS_SUMMARY,
            'StatefulSet default/radarr has not matched the expected number '
            'of replicas for longer than 15 minutes on cluster home.')],
        'want': ['StatefulSet default/radarr has not matched the expected '
                 'number of replicas for longer than 15 minutes on cluster '
                 'home.'],
    },
)


def receiver_templates(values):
    for receiver in values['alertmanager']['config']['receivers']:
        if receiver['name'] == 'pushover':
            config = receiver['pushover_configs'][0]
            return config['title'], config['message']
    raise ValueError('alertmanager.config.receivers has no pushover receiver')


def payload(sample):
    alerts = [{'status': 'firing', **a} for a in sample['alerts']]
    return {
        'receiver': 'pushover',
        'status': 'firing',
        'alerts': alerts,
        'groupLabels': {'alertname': alerts[0]['labels']['alertname']},
    }


def problems(sample, title, body):
    found = []
    if title != sample['title']:
        found.append(f"{sample['name']}: title rendered as {title!r}, "
                     f"want {sample['title']!r}")
    lines = body.split('\n')
    if lines != sample['want']:
        found.append(f"{sample['name']}: body rendered as lines {lines!r}, "
                     f"want {sample['want']!r}")
    return found


def render(amtool, text, data, glob):
    done = subprocess.run(
        [amtool, 'template', 'render', f'--template.glob={glob}',
         f'--template.text={text}', f'--template.data={data}'],
        capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(done.stderr.strip())
    return done.stdout


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--overrides', required=True,
                        help='our values override for kube-prometheus-stack')
    parser.add_argument('--amtool', required=True,
                        help='amtool binary, the version Alertmanager runs')
    args = parser.parse_args(argv)

    with open(args.overrides) as fh:
        title, message = receiver_templates(yaml.safe_load(fh))

    errors = []
    with tempfile.TemporaryDirectory() as tmp:
        # amtool demands a template glob even when the text is inline.
        glob = os.path.join(tmp, 'empty.tmpl')
        open(glob, 'w').close()
        data = os.path.join(tmp, 'data.json')
        for sample in SAMPLES:
            with open(data, 'w') as fh:
                json.dump(payload(sample), fh)
            try:
                rendered = [render(args.amtool, text, data, glob)
                            for text in (title, message)]
            except RuntimeError as exc:
                errors.append(f"{sample['name']}: {exc}")
                continue
            errors += problems(sample, *rendered)

    for error in errors:
        print(f'FAIL :: {args.overrides}: {error}')
    if errors:
        return 1

    print(f'OK :: {len(SAMPLES)} sample alerts render with their workload in '
          f'{args.overrides}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
