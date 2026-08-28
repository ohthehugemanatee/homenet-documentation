"""Tests for check_ephemeral_volumes.

A generic ephemeral volume on a Longhorn StorageClass lints clean everywhere
else: kubeconform validates it, the pod runs, and the damage only shows up weeks
later as orphaned BackupVolumes on shoebox (#277).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from check_ephemeral_volumes import problems  # noqa: E402


def ephemeral_volume(name='plex-transcode', storage_class='longhorn-ephemeral'):
    spec = {'accessModes': ['ReadWriteOnce'],
            'resources': {'requests': {'storage': '30Gi'}}}
    if storage_class is not None:
        spec['storageClassName'] = storage_class
    return {'name': name, 'ephemeral': {'volumeClaimTemplate': {'spec': spec}}}


def workload(volumes, kind='StatefulSet'):
    return {'apiVersion': 'apps/v1', 'kind': kind,
            'metadata': {'name': 'plex'},
            'spec': {'template': {'spec': {'volumes': volumes}}}}


class ProblemsTest(unittest.TestCase):
    def test_ephemeral_on_longhorn_is_flagged(self):
        self.assertEqual(len(problems(workload([ephemeral_volume()]))), 1)

    def test_message_names_the_volume_and_class(self):
        found = problems(workload([ephemeral_volume()]))[0]
        self.assertIn('plex-transcode', found)
        self.assertIn('longhorn-ephemeral', found)

    def test_every_longhorn_class_is_flagged(self):
        for storage_class in ('longhorn', 'longhorn-static',
                              'longhorn-ephemeral', 'longhorn-ephemeral-fast',
                              'longhorn-performance'):
            volume = ephemeral_volume(storage_class=storage_class)
            self.assertEqual(len(problems(workload([volume]))), 1,
                             f'{storage_class} should be flagged')

    def test_emptydir_is_clean(self):
        volume = {'name': 'plex-transcode', 'emptyDir': {'sizeLimit': '30Gi'}}
        self.assertEqual(problems(workload([volume])), [])

    def test_non_longhorn_ephemeral_is_clean(self):
        volume = ephemeral_volume(storage_class='local-path')
        self.assertEqual(problems(workload([volume])), [])

    def test_statefulset_volumeclaimtemplate_is_clean(self):
        # The stable-UUID case this check must not punish.
        doc = {'apiVersion': 'apps/v1', 'kind': 'StatefulSet',
               'metadata': {'name': 'plex'},
               'spec': {'volumeClaimTemplates': [
                   {'metadata': {'name': 'plex-live-db'},
                    'spec': {'storageClassName': 'longhorn'}}],
                   'template': {'spec': {'volumes': []}}}}
        self.assertEqual(problems(doc), [])

    def test_pvc_reference_is_clean(self):
        volume = {'name': 'media',
                  'persistentVolumeClaim': {'claimName': 'media'}}
        self.assertEqual(problems(workload([volume])), [])

    def test_bare_pod_is_scanned(self):
        doc = {'apiVersion': 'v1', 'kind': 'Pod',
               'metadata': {'name': 'debug'},
               'spec': {'volumes': [ephemeral_volume()]}}
        self.assertEqual(len(problems(doc)), 1)

    def test_multiple_offending_volumes_are_each_reported(self):
        volumes = [ephemeral_volume(name='one'), ephemeral_volume(name='two')]
        self.assertEqual(len(problems(workload(volumes))), 2)

    def test_missing_storage_class_is_clean(self):
        # No storageClassName means the cluster default, which is not
        # necessarily Longhorn; kube-score owns that policy.
        self.assertEqual(problems(workload([ephemeral_volume(
            storage_class=None)])), [])

    def test_malformed_documents_do_not_raise(self):
        for doc in (None, [], 'a string', {}, {'spec': None},
                    {'spec': {'template': 'no'}},
                    {'spec': {'template': {'spec': {'volumes': 'no'}}}},
                    {'spec': {'volumes': [None, 'no', {'ephemeral': 'no'}]}}):
            self.assertEqual(problems(doc), [])


if __name__ == '__main__':
    unittest.main()
