"""Tests for the Longhorn PreSync gate."""
import importlib.util
import json
import os
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      '..', '..', '..', 'cluster', 'argocd', 'hooks',
                      'longhorn', 'preflight.py')
spec = importlib.util.spec_from_file_location('preflight', SCRIPT)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def vol(name, state='attached', robustness='healthy'):
    return {'metadata': {'name': name},
            'status': {'state': state, 'robustness': robustness}}


def bi(name, *states):
    return {'metadata': {'name': name},
            'status': {'diskFileStatusMap': {
                f'disk-{i}': {'state': s} for i, s in enumerate(states)}}}


class TestBlockers(unittest.TestCase):

    def test_faulted_volume_blocks(self):
        found = preflight.blockers([vol('pvc-a', robustness='faulted')], [])
        self.assertEqual(len(found), 1)
        self.assertIn('pvc-a', found[0])

    def test_failed_backing_image_blocks(self):
        found = preflight.blockers([], [bi('bi-a', 'ready', 'failed')])
        self.assertEqual(len(found), 1)
        self.assertIn('bi-a', found[0])

    def test_detached_degraded_and_statusless_do_not_block(self):
        vols = [vol('pvc-a', state='detached', robustness='unknown'),
                vol('pvc-b', robustness='degraded'),
                vol('pvc-c', state='attaching', robustness='unknown'),
                {'metadata': {'name': 'pvc-d'}}]
        self.assertEqual(preflight.blockers(vols, [bi('bi-a', 'ready')]), [])

    def test_empty_collections_do_not_block(self):
        self.assertEqual(preflight.blockers([], []), [])

    def test_reports_every_blocker_not_just_the_first(self):
        found = preflight.blockers([vol('p', robustness='faulted')],
                                   [bi('b', 'failed-and-cleanup')])
        self.assertEqual(len(found), 2)


class TestExitCode(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write(self, name, items):
        path = os.path.join(self.tmpdir, name)
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump({'items': items}, handle)
        return path

    def _run(self, volumes, backing_images):
        volumes_path = self._write('volumes.json', volumes)
        backing_images_path = self._write('backingimages.json',
                                          backing_images)
        return preflight.main(['preflight.py', volumes_path,
                               backing_images_path])

    def test_faulted_volume_exits_nonzero(self):
        self.assertEqual(self._run([vol('p', robustness='faulted')], []), 1)

    def test_clean_cluster_exits_zero(self):
        self.assertEqual(self._run([vol('p'), vol('q', state='detached',
                                                  robustness='unknown')], []), 0)

    def test_empty_items_do_not_block(self):
        self.assertEqual(self._run([], []), 0)

    def test_missing_file_exits_nonzero(self):
        missing = os.path.join(self.tmpdir, 'missing.json')
        backing_images_path = self._write('backingimages.json', [])
        self.assertEqual(
            preflight.main(['preflight.py', missing, backing_images_path]),
            1)

    def test_malformed_file_exits_nonzero(self):
        bad_path = os.path.join(self.tmpdir, 'bad.json')
        with open(bad_path, 'w', encoding='utf-8') as handle:
            handle.write('not json')
        backing_images_path = self._write('backingimages.json', [])
        self.assertEqual(
            preflight.main(['preflight.py', bad_path, backing_images_path]),
            1)


if __name__ == '__main__':
    unittest.main()
