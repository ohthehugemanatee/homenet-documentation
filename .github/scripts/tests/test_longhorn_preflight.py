"""Unit tests for the Longhorn PreSync gate (#280).

Deliberately shallow. The Kubernetes and Longhorn APIs are tested upstream; the
two things that are ours are that the right collections get requested and that a
blocking response actually blocks.
"""
import importlib.util
import os
import unittest
from unittest import mock

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


class TestAPICalls(unittest.TestCase):

    def test_collection_url_is_namespaced_longhorn_v1beta2(self):
        self.assertEqual(
            preflight.collection_url('https://10.0.0.1:443', 'volumes'),
            'https://10.0.0.1:443/apis/longhorn.io/v1beta2'
            '/namespaces/longhorn-system/volumes')


class TestBlockers(unittest.TestCase):

    def test_faulted_volume_blocks(self):
        found = preflight.blockers([vol('pvc-a', robustness='faulted')], [])
        self.assertEqual(len(found), 1)
        self.assertIn('pvc-a', found[0])

    def test_failed_backing_image_blocks(self):
        found = preflight.blockers([], [bi('bi-a', 'ready', 'failed')])
        self.assertEqual(len(found), 1)
        self.assertIn('bi-a', found[0])

    # The semantic worth pinning: a detached volume has no engine to evaluate
    # its replicas and always reports 'unknown'. Blocking on that would fail
    # every sync, which is how a gate gets switched off.
    def test_detached_degraded_and_statusless_do_not_block(self):
        vols = [vol('pvc-a', state='detached', robustness='unknown'),
                vol('pvc-b', robustness='degraded'),
                vol('pvc-c', state='attaching', robustness='unknown'),
                {'metadata': {'name': 'pvc-d'}}]
        self.assertEqual(preflight.blockers(vols, [bi('bi-a', 'ready')]), [])

    # This cluster runs no BackingImages; an empty collection is the norm.
    def test_empty_collections_do_not_block(self):
        self.assertEqual(preflight.blockers([], []), [])

    def test_reports_every_blocker_not_just_the_first(self):
        found = preflight.blockers([vol('p', robustness='faulted')],
                                   [bi('b', 'failed-and-cleanup')])
        self.assertEqual(len(found), 2)


class TestExitCode(unittest.TestCase):
    """A blocking response returns the status ArgoCD reads to abort the sync."""

    def setUp(self):
        self.real_fetch = preflight.fetch
        os.environ['KUBERNETES_SERVICE_HOST'] = '10.0.0.1'

    def tearDown(self):
        preflight.fetch = self.real_fetch

    def _run(self, volumes, backing_images):
        preflight.fetch = lambda base, tok, ctx, plural: (
            volumes if plural == 'volumes' else backing_images)
        # main() reads the ServiceAccount token and CA off disk.
        with mock.patch('builtins.open', mock.mock_open(read_data='tok')), \
             mock.patch.object(preflight.ssl, 'create_default_context',
                               return_value=None):
            return preflight.main()

    def test_faulted_volume_exits_nonzero(self):
        self.assertEqual(self._run([vol('p', robustness='faulted')], []), 1)

    def test_clean_cluster_exits_zero(self):
        self.assertEqual(self._run([vol('p'), vol('q', state='detached',
                                                  robustness='unknown')], []), 0)


if __name__ == '__main__':
    unittest.main()
