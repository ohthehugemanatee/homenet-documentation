"""Tests for check_mariadb_probes."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from check_mariadb_probes import mariadb_container, problems  # noqa: E402


def readiness(**fields):
    return {'exec': {'command': ['mysql', '-e', 'SELECT 1']},
            'periodSeconds': 5, 'successThreshold': 2, **fields}


def container(**probes):
    return {'name': 'mariadb', **probes}


def workload(containers, kind='StatefulSet', name='mariadb'):
    return {'kind': kind, 'metadata': {'name': name},
            'spec': {'template': {'spec': {'containers': containers}}}}


class MariadbContainerTest(unittest.TestCase):
    def test_finds_the_container_in_statefulset_and_deployment(self):
        for kind in ('StatefulSet', 'Deployment'):
            found = mariadb_container(workload([container()], kind=kind))
            self.assertEqual(found['name'], 'mariadb')

    def test_ignores_other_workloads_containers_and_kinds(self):
        self.assertIsNone(mariadb_container(
            workload([container()], name='nextcloud')))
        self.assertIsNone(mariadb_container(
            workload([container()], kind='Service')))
        self.assertIsNone(mariadb_container(
            workload([{'name': 'sidecar'}])))

    def test_malformed_documents_do_not_raise(self):
        for doc in (None, [], 'a string', {}, {'kind': 'StatefulSet'},
                    workload('no'), {'kind': 'StatefulSet',
                                     'metadata': {'name': 'mariadb'},
                                     'spec': {'template': 'no'}}):
            self.assertIsNone(mariadb_container(doc))


class ProblemsTest(unittest.TestCase):
    def test_a_two_pass_readiness_probe_is_clean(self):
        self.assertEqual(problems(container(readinessProbe=readiness())), [])

    def test_more_than_two_passes_is_clean(self):
        self.assertEqual(
            problems(container(readinessProbe=readiness(successThreshold=3))),
            [])

    def test_missing_readiness_probe_is_flagged(self):
        found = problems(container())
        self.assertEqual(len(found), 1)
        self.assertIn('readinessProbe is missing', found[0])

    def test_a_liveness_probe_does_not_stand_in_for_readiness(self):
        found = problems(container(livenessProbe=readiness()))
        self.assertEqual(len(found), 1)
        self.assertIn('readinessProbe is missing', found[0])

    def test_a_single_pass_threshold_is_flagged(self):
        found = problems(container(readinessProbe=readiness(successThreshold=1)))
        self.assertEqual(len(found), 1)
        self.assertIn('successThreshold', found[0])

    def test_the_kubernetes_default_of_one_counts_when_omitted(self):
        probe = readiness()
        del probe['successThreshold']
        found = problems(container(readinessProbe=probe))
        self.assertEqual(len(found), 1)
        self.assertIn('successThreshold', found[0])

    def test_a_non_integer_threshold_is_flagged_without_raising(self):
        for value in ('2', None, [], 2.0):
            found = problems(container(
                readinessProbe=readiness(successThreshold=value)))
            self.assertEqual(len(found), 1)

    def test_a_malformed_probe_is_flagged_without_raising(self):
        for probe in ('no', [], 7, {}):
            self.assertEqual(len(problems(container(readinessProbe=probe))), 1)


if __name__ == '__main__':
    unittest.main()
