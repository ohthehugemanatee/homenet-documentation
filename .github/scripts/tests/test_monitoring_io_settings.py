"""Tests for check_monitoring_io_settings.

The failure this guards is silent: helm merges an override key the chart no
longer reads, the dry-run renders, and the setting simply does not exist on the
deployed object.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from check_monitoring_io_settings import dig, problems, MISSING  # noqa: E402

SETTINGS = ((('a', 'b'), 'Prometheus', ('spec', 'interval')),)


def overrides(**spec):
    full = {'a': {'b': '60s'}}
    full.update(spec)
    return full


def rendered(value='60s', kind='Prometheus'):
    return [{'kind': kind, 'spec': {'interval': value}}]


class DigTest(unittest.TestCase):
    def test_reaches_a_nested_value(self):
        self.assertEqual(dig({'a': {'b': 1}}, ('a', 'b')), 1)

    def test_absent_key_is_missing(self):
        self.assertIs(dig({'a': {}}, ('a', 'b')), MISSING)

    def test_scalar_midway_is_missing_not_a_crash(self):
        self.assertIs(dig({'a': 1}, ('a', 'b')), MISSING)

    def test_index_reaches_a_list_element(self):
        self.assertEqual(dig({'a': [{'b': 1}]}, ('a', 0, 'b')), 1)

    def test_index_past_the_end_is_missing(self):
        self.assertIs(dig({'a': []}, ('a', 0)), MISSING)

    def test_index_into_a_dict_is_missing_not_a_crash(self):
        self.assertIs(dig({'a': {'b': 1}}, ('a', 0)), MISSING)


class ProblemsTest(unittest.TestCase):
    def test_matching_override_and_render_is_clean(self):
        self.assertEqual(problems(overrides(), rendered(), SETTINGS), [])

    def test_unset_override_is_reported(self):
        found = problems({}, rendered(), SETTINGS)
        self.assertEqual(len(found), 1)
        self.assertIn('not set in the override', found[0])

    def test_render_missing_the_field_is_reported(self):
        found = problems(overrides(), [{'kind': 'Prometheus', 'spec': {}}],
                         SETTINGS)
        self.assertEqual(len(found), 1)
        self.assertIn('not reading that key', found[0])

    def test_render_missing_the_kind_is_reported(self):
        found = problems(overrides(), rendered(kind='Alertmanager'), SETTINGS)
        self.assertEqual(len(found), 1)
        self.assertIn('rendered no Prometheus', found[0])

    def test_value_drift_between_override_and_render_is_reported(self):
        found = problems(overrides(), rendered(value='30s'), SETTINGS)
        self.assertEqual(len(found), 1)
        self.assertIn("'30s'", found[0])

    def test_any_matching_doc_of_that_kind_satisfies_the_setting(self):
        # The chart renders one PVC per persisted component; only one of them
        # is the Grafana claim the override names.
        docs = [{'kind': 'Prometheus', 'spec': {'interval': '30s'}}] + rendered()
        self.assertEqual(problems(overrides(), docs, SETTINGS), [])

    def test_non_mapping_documents_are_skipped(self):
        # A values file's trailing `---` renders as a None document.
        self.assertEqual(problems(overrides(), [None] + rendered(), SETTINGS), [])


class RealSettingsTest(unittest.TestCase):
    def test_the_shipped_table_covers_every_issue_298_setting(self):
        from check_monitoring_io_settings import SETTINGS as shipped
        paths = {'.'.join(path) for path, _, _ in shipped}
        self.assertIn('prometheus.prometheusSpec.scrapeInterval', paths)
        self.assertIn('prometheus.prometheusSpec.retentionSize', paths)
        self.assertIn('grafana.persistence.storageClassName', paths)

    def test_the_shipped_table_covers_the_kubelet_drop(self):
        from check_monitoring_io_settings import SETTINGS as shipped
        paths = {'.'.join(path) for path, _, _ in shipped}
        self.assertIn('kubelet.serviceMonitor.metricRelabelings', paths)

    def test_a_list_index_in_a_rendered_path_formats_in_the_message(self):
        settings = ((('a', 'b'), 'ServiceMonitor', ('spec', 'endpoints', 0, 'x')),)
        found = problems(overrides(), [{'kind': 'ServiceMonitor', 'spec': {}}],
                         settings)
        self.assertIn('spec.endpoints.0.x', found[0])


if __name__ == '__main__':
    unittest.main()
