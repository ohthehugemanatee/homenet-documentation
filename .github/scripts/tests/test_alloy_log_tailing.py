"""Tests for check_alloy_log_tailing.

The failures these guard are silent. Reverting to `loki.source.kubernetes`
renders a perfectly valid chart that quietly streams every log line through the
apiserver, and dropping the `/mnt/usb/log` mount renders a valid DaemonSet whose
tails resolve through a dangling symlink and collect nothing.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from check_alloy_log_tailing import (  # noqa: E402
    config_problems, mount_problems, problems)

GOOD_CONFIG = '''
local.file_match "pods" { }
loki.source.file "pods" { }
loki.process "cri" { stage.cri {} }
'''


def config_map(config=GOOD_CONFIG, name='alloy', key='config.alloy'):
    return {'kind': 'ConfigMap', 'metadata': {'name': name},
            'data': {key: config}}


def daemonset(mounts=None, volumes=None, container='alloy'):
    if mounts is None:
        mounts = [{'name': 'varlog', 'mountPath': '/var/log', 'readOnly': True},
                  {'name': 'usblog', 'mountPath': '/mnt/usb/log',
                   'readOnly': True}]
    if volumes is None:
        volumes = [{'name': 'varlog', 'hostPath': {'path': '/var/log'}},
                   {'name': 'usblog', 'hostPath': {'path': '/mnt/usb/log'}}]
    return {'kind': 'DaemonSet',
            'spec': {'template': {'spec': {
                'volumes': volumes,
                'containers': [{'name': container, 'volumeMounts': mounts}]}}}}


class ConfigTest(unittest.TestCase):
    def test_file_tailing_config_passes(self):
        self.assertEqual(config_problems([config_map()]), [])

    def test_apiserver_streaming_is_rejected(self):
        config = GOOD_CONFIG + '\nloki.source.kubernetes "pods" { }\n'
        found = config_problems([config_map(config)])
        self.assertTrue(any('kube-apiserver' in p for p in found), found)

    def test_missing_file_source_is_rejected(self):
        found = config_problems([config_map('local.file_match "pods" { }')])
        self.assertTrue(any('loki.source.file' in p for p in found), found)

    def test_missing_cri_stage_is_rejected(self):
        config = 'local.file_match "x" { }\nloki.source.file "x" { }'
        found = config_problems([config_map(config)])
        self.assertTrue(any('stage.cri' in p for p in found), found)

    def test_absent_config_map_is_rejected(self):
        self.assertTrue(config_problems([config_map(name='other')]))

    def test_absent_config_key_is_rejected(self):
        self.assertTrue(config_problems([config_map(key='other')]))

    def test_unrelated_documents_are_ignored(self):
        docs = [{'kind': 'Service'}, None, config_map()]
        self.assertEqual(config_problems(docs), [])


class MountTest(unittest.TestCase):
    def test_both_host_log_paths_pass(self):
        self.assertEqual(mount_problems([daemonset()]), [])

    def test_missing_usb_mount_is_rejected(self):
        mounts = [{'name': 'varlog', 'mountPath': '/var/log', 'readOnly': True}]
        found = mount_problems([daemonset(mounts=mounts)])
        self.assertTrue(any('/mnt/usb/log' in p for p in found), found)

    def test_missing_varlog_mount_is_rejected(self):
        mounts = [{'name': 'usblog', 'mountPath': '/mnt/usb/log',
                   'readOnly': True}]
        found = mount_problems([daemonset(mounts=mounts)])
        self.assertTrue(any('/var/log' in p for p in found), found)

    def test_writable_mount_is_rejected(self):
        mounts = [{'name': 'varlog', 'mountPath': '/var/log'},
                  {'name': 'usblog', 'mountPath': '/mnt/usb/log',
                   'readOnly': True}]
        found = mount_problems([daemonset(mounts=mounts)])
        self.assertTrue(any('writable' in p for p in found), found)

    def test_mount_backed_by_the_wrong_host_path_is_rejected(self):
        volumes = [{'name': 'varlog', 'hostPath': {'path': '/var/log'}},
                   {'name': 'usblog', 'hostPath': {'path': '/mnt/usb'}}]
        found = mount_problems([daemonset(volumes=volumes)])
        self.assertTrue(any('/mnt/usb/log' in p for p in found), found)

    def test_emptydir_backed_mount_is_rejected(self):
        volumes = [{'name': 'varlog', 'hostPath': {'path': '/var/log'}},
                   {'name': 'usblog', 'emptyDir': {}}]
        self.assertTrue(mount_problems([daemonset(volumes=volumes)]))

    def test_a_deployment_instead_of_a_daemonset_is_rejected(self):
        self.assertTrue(mount_problems([{'kind': 'Deployment'}]))

    def test_renamed_container_is_rejected(self):
        self.assertTrue(mount_problems([daemonset(container='agent')]))


class ProblemsTest(unittest.TestCase):
    def test_a_whole_good_render_passes(self):
        self.assertEqual(problems([config_map(), daemonset()]), [])

    def test_reports_config_and_mount_defects_together(self):
        config = GOOD_CONFIG + '\nloki.source.kubernetes "pods" { }\n'
        found = problems([config_map(config), daemonset(mounts=[])])
        self.assertTrue(any('kube-apiserver' in p for p in found), found)
        self.assertTrue(any('/var/log' in p for p in found), found)


if __name__ == '__main__':
    unittest.main()
