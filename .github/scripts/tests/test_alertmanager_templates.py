"""Tests for check_alertmanager_templates.

The failure this guards is a notification that does not say which workload is
affected: the receiver falls back to the generic `summary`, or joins a group's
alerts into one unbroken line.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from check_alertmanager_templates import problems, receiver_templates  # noqa: E402

STS_LINE = ('StatefulSet default/prowlarr has not matched the expected number '
            'of replicas for longer than 15 minutes.')
LIDARR_LINE = STS_LINE.replace('prowlarr', 'lidarr')
SAMPLE = {
    'name': 'statefulset',
    'title': 'k8s alert: KubeStatefulSetReplicasMismatch',
    'want': [STS_LINE],
}
GROUP = {
    'name': 'group',
    'title': 'k8s alert: KubeStatefulSetReplicasMismatch',
    'want': [STS_LINE, LIDARR_LINE],
}


class ProblemsTest(unittest.TestCase):
    def test_body_naming_the_workload_is_clean(self):
        self.assertEqual(problems(SAMPLE, SAMPLE['title'], STS_LINE), [])

    def test_summary_only_body_is_reported(self):
        body = 'StatefulSet has not matched the expected number of replicas.'
        found = problems(SAMPLE, SAMPLE['title'], body)
        self.assertEqual(len(found), 1)
        self.assertIn('default/prowlarr', found[0])

    def test_group_joined_without_a_separator_is_reported(self):
        found = problems(GROUP, GROUP['title'], STS_LINE + LIDARR_LINE)
        self.assertEqual(len(found), 1)

    def test_group_on_separate_lines_is_clean(self):
        body = STS_LINE + '\n' + LIDARR_LINE
        self.assertEqual(problems(GROUP, GROUP['title'], body), [])

    def test_trailing_newline_is_reported(self):
        self.assertEqual(len(problems(SAMPLE, SAMPLE['title'], STS_LINE + '\n')), 1)

    def test_dangling_empty_cluster_clause_is_reported(self):
        body = STS_LINE[:-1] + ' on cluster .'
        self.assertEqual(len(problems(SAMPLE, SAMPLE['title'], body)), 1)

    def test_title_drift_is_reported(self):
        found = problems(SAMPLE, 'k8s alert: Other', STS_LINE)
        self.assertEqual(len(found), 1)
        self.assertIn('title', found[0])

    def test_title_and_body_defects_are_both_reported(self):
        self.assertEqual(len(problems(SAMPLE, 'x', 'y')), 2)


class ReceiverTemplatesTest(unittest.TestCase):
    def values(self, *receivers):
        return {'alertmanager': {'config': {'receivers': list(receivers)}}}

    def test_returns_the_pushover_title_and_message(self):
        values = self.values(
            {'name': 'null'},
            {'name': 'pushover',
             'pushover_configs': [{'title': 'T', 'message': 'M'}]})
        self.assertEqual(receiver_templates(values), ('T', 'M'))

    def test_missing_pushover_receiver_is_an_error(self):
        with self.assertRaises(ValueError):
            receiver_templates(self.values({'name': 'null'}))


if __name__ == '__main__':
    unittest.main()
