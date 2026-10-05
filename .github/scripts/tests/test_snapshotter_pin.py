"""Tests for check_snapshotter_pin.

The snapshot-controller must run the external-snapshotter release that matches
the csi-snapshotter sidecar the pinned Longhorn chart deploys. The two move
together, so a Longhorn bump without a matching pin bump has to fail CI.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from check_snapshotter_pin import longhorn_snapshotter_version, problems  # noqa: E402

REPO = 'https://github.com/kubernetes-csi/external-snapshotter'


def render(image='longhornio/csi-snapshotter:v8.6.0'):
    env = [{'name': 'CSI_ATTACHER_IMAGE', 'value': 'longhornio/csi-attacher:v4.12.0'}]
    if image is not None:
        env.append({'name': 'CSI_SNAPSHOTTER_IMAGE', 'value': image})
    deployer = {'kind': 'Deployment',
                'metadata': {'name': 'longhorn-driver-deployer'},
                'spec': {'template': {'spec': {
                    'initContainers': [{'name': 'wait-longhorn-manager'}],
                    'containers': [{'name': 'longhorn-driver-deployer', 'env': env}]}}}}
    return [{'kind': 'ConfigMap', 'metadata': {'name': 'x'}}, None, deployer]


def kustomization(crd='v8.6.0', controller='v8.6.0', image='v8.6.0'):
    doc = {'resources': [f'{REPO}/client/config/crd?ref={crd}',
                         f'{REPO}/deploy/kubernetes/snapshot-controller?ref={controller}']}
    if image is not None:
        doc['images'] = [{'name': 'registry.k8s.io/sig-storage/snapshot-controller',
                          'newTag': image}]
    return doc


class LonghornVersionTest(unittest.TestCase):
    def test_reads_the_deployer_env(self):
        self.assertEqual(longhorn_snapshotter_version(render()), 'v8.6.0')

    def test_registry_prefix_is_ignored(self):
        docs = render('docker.io/longhornio/csi-snapshotter:v8.6.0')
        self.assertEqual(longhorn_snapshotter_version(docs), 'v8.6.0')

    def test_longhorn_rebuild_suffix_compares_as_the_upstream_release(self):
        docs = render('longhornio/csi-snapshotter:v8.6.0-20260101')
        self.assertEqual(longhorn_snapshotter_version(docs), 'v8.6.0')

    def test_render_without_the_image_yields_none(self):
        self.assertIsNone(longhorn_snapshotter_version(render(image=None)))


class ProblemsTest(unittest.TestCase):
    def test_pin_matching_longhorn_passes(self):
        self.assertEqual(problems('v8.6.0', kustomization()), [])

    def test_longhorn_bump_without_pin_bump_fails_every_pin(self):
        found = problems('v8.7.0', kustomization())
        self.assertEqual(len(found), 3, found)
        self.assertTrue(all('v8.7.0' in p for p in found), found)

    def test_one_stale_git_ref_fails(self):
        found = problems('v8.6.0', kustomization(crd='v8.5.0'))
        self.assertEqual(len(found), 1, found)
        self.assertIn('client/config/crd', found[0])

    def test_image_left_to_upstream_default_fails(self):
        # Upstream's v8.6.0 manifest still deploys the v8.5.0 image.
        found = problems('v8.6.0', kustomization(image=None))
        self.assertEqual(len(found), 1, found)
        self.assertIn('images', found[0])

    def test_image_disagreeing_with_the_ref_fails(self):
        found = problems('v8.6.0', kustomization(image='v8.5.0'))
        self.assertEqual(len(found), 1, found)
        self.assertIn('v8.5.0', found[0])

    def test_missing_longhorn_version_never_passes(self):
        self.assertTrue(problems(None, kustomization()))

    def test_no_external_snapshotter_resources_fails(self):
        found = problems('v8.6.0', {'resources': [],
                                    'images': kustomization()['images']})
        self.assertIn('external-snapshotter', ' '.join(found))


if __name__ == '__main__':
    unittest.main()
