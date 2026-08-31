"""Tests for check_helm_values_keys.

The defect this catches is invisible everywhere else: helm merges an unknown
key without complaint, so the dry-run renders, kubeconform passes, and the
override does nothing. Loki's `monitoring.lokiCanary.enabled: false` read as
clean config for eleven chart majors while the canary kept running.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from check_helm_values_keys import problems  # noqa: E402

# Shaped like the loki chart.
CHART = {
    'deploymentMode': 'Monolithic',
    'gateway': {'enabled': True},
    'lokiCanary': {'enabled': True},
    'monitoring': {'dashboards': {'enabled': False},
                   'serviceMonitor': {'enabled': False}},
    'singleBinary': {'replicas': 0,
                     'nodeSelector': {},
                     'resources': {},
                     'persistence': {'enabled': True, 'size': '10Gi'}},
    'loki': {'auth_enabled': True, 'commonConfig': {'replication_factor': 3}},
}


class ProblemsTest(unittest.TestCase):
    def test_removed_key_is_flagged(self):
        found = problems({'monitoring': {'selfMonitoring': {'enabled': False}}},
                         CHART)
        self.assertEqual(len(found), 1)
        self.assertIn('monitoring.selfMonitoring', found[0])

    def test_hoisted_key_is_flagged_at_its_old_home(self):
        found = problems({'monitoring': {'lokiCanary': {'enabled': False}}},
                         CHART)
        self.assertEqual(len(found), 1)
        self.assertIn('monitoring.lokiCanary', found[0])

    def test_hoisted_key_is_clean_at_its_new_home(self):
        self.assertEqual(problems({'lokiCanary': {'enabled': False}}, CHART),
                         [])

    def test_unknown_top_level_key_is_flagged(self):
        found = problems({'lokiCanry': {'enabled': False}}, CHART)
        self.assertEqual(len(found), 1)
        self.assertIn('lokiCanry', found[0])

    def test_defined_keys_are_clean(self):
        overrides = {'deploymentMode': 'Monolithic',
                     'gateway': {'enabled': False},
                     'singleBinary': {'replicas': 1,
                                      'persistence': {'size': '5Gi'}}}
        self.assertEqual(problems(overrides, CHART), [])

    def test_children_of_an_empty_mapping_are_free_form(self):
        overrides = {'singleBinary': {
            'nodeSelector': {'kubernetes.io/arch': 'amd64'},
            'resources': {'requests': {'cpu': '100m'},
                          'limits': {'memory': '512Mi'}}}}
        self.assertEqual(problems(overrides, CHART), [])

    def test_children_of_a_null_default_are_free_form(self):
        self.assertEqual(problems({'extra': {'anything': 1}},
                                  {'extra': None}), [])

    def test_passthrough_block_is_skipped_whole(self):
        overrides = {'loki': {'limits_config': {'retention_period': '168h'},
                              'compactor': {'retention_enabled': True}}}
        self.assertEqual(len(problems(overrides, CHART)), 2)
        self.assertEqual(problems(overrides, CHART, passthrough=('loki',)), [])

    def test_passthrough_applies_only_at_the_top_level(self):
        found = problems({'monitoring': {'loki': {'enabled': False}}}, CHART,
                         passthrough=('loki',))
        self.assertEqual(len(found), 1)
        self.assertIn('monitoring.loki', found[0])

    def test_mapping_set_below_a_scalar_is_flagged(self):
        found = problems({'deploymentMode': {'enabled': True}}, CHART)
        self.assertEqual(len(found), 1)
        self.assertIn('not a mapping', found[0])

    def test_every_defect_is_reported(self):
        overrides = {'monitoring': {'selfMonitoring': {'enabled': False},
                                    'lokiCanary': {'enabled': False}},
                     'nonsense': True}
        self.assertEqual(len(problems(overrides, CHART)), 3)

    def test_lists_are_leaves(self):
        self.assertEqual(problems({'singleBinary': {'resources': [1, 2]}},
                                  CHART), [])

    def test_malformed_input_does_not_raise(self):
        for overrides in (None, [], 'a string', {}):
            self.assertEqual(problems(overrides, CHART), [])
        self.assertEqual(len(problems({'a': 1}, None)), 1)


if __name__ == '__main__':
    unittest.main()
