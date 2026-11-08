"""Tests for check_nextcloud_probes.

nginx stays up while PHP is starved, so the old `pgrep nginx` probes passed
through an outage while every request timed out (#472).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from check_nextcloud_probes import nextcloud_container, problems  # noqa: E402


def http_probe(path='/status.php', headers=({'name': 'Host', 'value': 'x'},)):
    return {'httpGet': {'path': path, 'port': 80,
                        'httpHeaders': list(headers)}}


def container(**probes):
    return {'name': 'nextcloud', **probes}


def workload(containers, kind='StatefulSet', name='nextcloud'):
    return {'kind': kind, 'metadata': {'name': name},
            'spec': {'template': {'spec': {'containers': containers}}}}


class NextcloudContainerTest(unittest.TestCase):
    def test_finds_the_container_in_statefulset_and_deployment(self):
        for kind in ('StatefulSet', 'Deployment'):
            found = nextcloud_container(workload([container()], kind=kind))
            self.assertEqual(found['name'], 'nextcloud')

    def test_ignores_other_workloads_containers_and_kinds(self):
        self.assertIsNone(nextcloud_container(
            workload([container()], name='mariadb')))
        self.assertIsNone(nextcloud_container(
            workload([container()], kind='Service')))
        self.assertIsNone(nextcloud_container(
            workload([{'name': 'imaginary'}])))

    def test_malformed_documents_do_not_raise(self):
        for doc in (None, [], 'a string', {}, {'kind': 'StatefulSet'},
                    workload('no'), {'kind': 'StatefulSet',
                                     'metadata': {'name': 'nextcloud'},
                                     'spec': {'template': 'no'}}):
            self.assertIsNone(nextcloud_container(doc))


class ProblemsTest(unittest.TestCase):
    def test_http_probes_with_a_host_header_are_clean(self):
        both = container(readinessProbe=http_probe(),
                         livenessProbe=http_probe())
        self.assertEqual(problems(both), [])

    def test_missing_readiness_probe_is_flagged(self):
        found = problems(container(livenessProbe=http_probe()))
        self.assertEqual(len(found), 1)
        self.assertIn('readinessProbe', found[0])

    def test_exec_liveness_probe_is_flagged(self):
        exec_probe = {'exec': {'command': ['pgrep', 'nginx']}}
        found = problems(container(readinessProbe=http_probe(),
                                   livenessProbe=exec_probe))
        self.assertEqual(len(found), 1)
        self.assertIn('livenessProbe', found[0])

    def test_wrong_path_and_missing_host_header_are_flagged(self):
        for probe in (http_probe(path='/'), http_probe(headers=()),
                      http_probe(headers=({'name': 'X-Other'},))):
            found = problems(container(readinessProbe=probe,
                                       livenessProbe=http_probe()))
            self.assertEqual(len(found), 1)

    def test_no_probes_reports_both(self):
        self.assertEqual(len(problems(container())), 2)


if __name__ == '__main__':
    unittest.main()
