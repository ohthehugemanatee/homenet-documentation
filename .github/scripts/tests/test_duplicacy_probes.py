"""Tests for check_duplicacy_probes."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from check_duplicacy_probes import duplicacy_container, problems  # noqa: E402


def startup(port=3875, period=10, threshold=60, kind='tcpSocket'):
    return {kind: {'port': port}, 'periodSeconds': period,
            'failureThreshold': threshold}


def container(**probes):
    return {'name': 'duplicacy', **probes}


def workload(containers, kind='StatefulSet', name='duplicacy'):
    return {'kind': kind, 'metadata': {'name': name},
            'spec': {'template': {'spec': {'containers': containers}}}}


class DuplicacyContainerTest(unittest.TestCase):
    def test_finds_the_container_in_statefulset_and_deployment(self):
        for kind in ('StatefulSet', 'Deployment'):
            found = duplicacy_container(workload([container()], kind=kind))
            self.assertEqual(found['name'], 'duplicacy')

    def test_ignores_other_workloads_containers_and_kinds(self):
        self.assertIsNone(duplicacy_container(
            workload([container()], name='plex')))
        self.assertIsNone(duplicacy_container(
            workload([container()], kind='Service')))
        self.assertIsNone(duplicacy_container(
            workload([{'name': 'promtail-sidecar'}])))

    def test_malformed_documents_do_not_raise(self):
        for doc in (None, [], 'a string', {}, {'kind': 'StatefulSet'},
                    workload('no'), {'kind': 'StatefulSet',
                                     'metadata': {'name': 'duplicacy'},
                                     'spec': {'template': 'no'}}):
            self.assertIsNone(duplicacy_container(doc))


class ProblemsTest(unittest.TestCase):
    def test_a_600_second_tcp_probe_on_3875_is_clean(self):
        self.assertEqual(problems(container(startupProbe=startup())), [])

    def test_the_budget_boundary_is_600_seconds(self):
        self.assertEqual(
            problems(container(startupProbe=startup(period=30, threshold=20))),
            [])
        for period, threshold in ((10, 59), (30, 19)):
            found = problems(container(
                startupProbe=startup(period=period, threshold=threshold)))
            self.assertEqual(len(found), 1)
            self.assertIn('600', found[0])

    def test_kubernetes_defaults_count_when_fields_are_omitted(self):
        found = problems(container(startupProbe={'tcpSocket': {'port': 3875}}))
        self.assertEqual(len(found), 1)
        self.assertIn('600', found[0])

    def test_missing_startup_probe_is_flagged(self):
        found = problems(container())
        self.assertEqual(len(found), 1)
        self.assertIn('startupProbe', found[0])

    def test_a_probe_on_the_wrong_port_is_flagged(self):
        found = problems(container(startupProbe=startup(port=8080)))
        self.assertEqual(len(found), 1)
        self.assertIn('3875', found[0])

    def test_a_non_tcp_probe_is_flagged(self):
        found = problems(container(startupProbe=startup(kind='httpGet')))
        self.assertEqual(len(found), 1)
        self.assertIn('tcpSocket', found[0])

    def test_a_malformed_probe_is_flagged_without_raising(self):
        for probe in ('no', [], 7, {}):
            self.assertEqual(len(problems(container(startupProbe=probe))), 1)


if __name__ == '__main__':
    unittest.main()
