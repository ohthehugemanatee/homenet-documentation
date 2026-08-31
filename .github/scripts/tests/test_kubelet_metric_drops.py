"""kubelet drops apiserver/etcd duplicates. See #300."""
import os
import re
import unittest

import yaml

VALUES = os.path.join(
    os.path.dirname(__file__), '..', '..', '..',
    'cluster', 'helm', 'kube-prometheus-stack', 'values.yaml')

DUPLICATED = (
    'apiserver_request_duration_seconds_bucket',
    'etcd_request_duration_seconds_bucket',
    'apiserver_request_sli_duration_seconds_bucket',
    'apiserver_watch_cache_read_wait_seconds_bucket',
    'apiserver_response_sizes_bucket',
    'apiserver_watch_list_duration_seconds_bucket',
    'apiserver_watch_events_sizes_bucket',
    'apiserver_request_body_size_bytes_bucket',
)

SPARED = (
    'kubelet_running_pods',
    'container_cpu_usage_seconds_total',
    'node_cpu_seconds_total',
    'rest_client_requests_total',
    'up',
)


def drop_rule():
    with open(VALUES) as f:
        values = yaml.safe_load(f)
    rules = values['kubelet']['serviceMonitor']['metricRelabelings']
    self_check = [r for r in rules if r.get('sourceLabels') == ['__name__']]
    return self_check[0]


class KubeletMetricDropsTest(unittest.TestCase):
    def test_rule_drops_by_name(self):
        rule = drop_rule()
        self.assertEqual(rule['action'], 'drop')

    def test_drops_every_duplicated_family(self):
        rule = drop_rule()
        regex = rule['regex']
        for name in DUPLICATED:
            self.assertIsNotNone(re.fullmatch(regex, name), name)

    def test_spares_kubelet_and_cadvisor_metrics(self):
        rule = drop_rule()
        regex = rule['regex']
        for name in SPARED:
            self.assertIsNone(re.fullmatch(regex, name), name)


if __name__ == '__main__':
    unittest.main()
