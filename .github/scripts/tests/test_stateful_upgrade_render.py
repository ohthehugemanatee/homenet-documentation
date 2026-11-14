"""Tests for stateful_upgrade_render."""
import contextlib
import copy
import io
import os
import sys
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from stateful_upgrade_render import main, nfs_claim_names, render  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), '..', '..', '..')
STORAGE = os.path.join(ROOT, 'cluster', 'storage')
MARIADB = os.path.join(ROOT, 'cluster', 'services', 'mariadb.yaml')
NFS = {'app-configs', 'media'}
LIMITS = {'cpu': '1000m', 'memory': '2Gi'}


def container(requests=None, limits=None, **extra):
    resources = {}
    if requests:
        resources['requests'] = requests
    if limits:
        resources['limits'] = limits
    return {'name': 'app', 'image': 'example/app:1.2.3',
            'resources': resources, **extra}


def claim_volume(name, claim):
    return {'name': name, 'persistentVolumeClaim': {'claimName': claim}}


def statefulset(volumes=(), templates=(), containers=None, init=()):
    pod = {'volumes': list(volumes),
           'containers': containers or [container()],
           'initContainers': list(init)}
    return {'apiVersion': 'apps/v1', 'kind': 'StatefulSet',
            'metadata': {'name': 'app'},
            'spec': {'volumeClaimTemplates': list(templates),
                     'template': {'spec': pod}}}


def pod_spec(doc):
    return doc['spec']['template']['spec']


def load(path):
    with open(path) as fh:
        return list(yaml.safe_load_all(fh))


class StorageClassTest(unittest.TestCase):
    def test_template_claims_use_local_path(self):
        template = {'metadata': {'name': 'datadir'},
                    'spec': {'storageClassName': 'longhorn'}}
        [out] = render([statefulset(templates=[template])], NFS)
        self.assertEqual(
            out['spec']['volumeClaimTemplates'][0]['spec']['storageClassName'],
            'local-path')

    def test_standalone_claims_use_local_path(self):
        pvc = {'kind': 'PersistentVolumeClaim', 'metadata': {'name': 'data'},
               'spec': {'storageClassName': 'longhorn'}}
        [out] = render([pvc], NFS)
        self.assertEqual(out['spec']['storageClassName'], 'local-path')


class NfsVolumeTest(unittest.TestCase):
    def test_nfs_claim_becomes_emptydir_and_keeps_its_subpath_mount(self):
        mount = {'name': 'nfs', 'mountPath': '/config', 'subPath': 'mariadb'}
        doc = statefulset(volumes=[claim_volume('nfs', 'app-configs')],
                          containers=[container(volumeMounts=[dict(mount)])])
        [out] = render([doc], NFS)
        self.assertEqual(pod_spec(out)['volumes'],
                         [{'name': 'nfs', 'emptyDir': {}}])
        self.assertEqual(pod_spec(out)['containers'][0]['volumeMounts'],
                         [mount])

    def test_other_claims_are_kept(self):
        volumes = [claim_volume('data', 'data')]
        [out] = render([statefulset(volumes=copy.deepcopy(volumes))], NFS)
        self.assertEqual(pod_spec(out)['volumes'], volumes)

    def test_static_volume_and_its_claim_are_dropped(self):
        pv = {'kind': 'PersistentVolume', 'metadata': {'name': 'unifi-pv'}}
        pvc = {'kind': 'PersistentVolumeClaim',
               'metadata': {'name': 'unifi-configs'},
               'spec': {'volumeName': 'unifi-pv'}}
        doc = statefulset(volumes=[claim_volume('cfg', 'unifi-configs')])
        out = render([pv, pvc, doc], NFS)
        self.assertEqual([d['kind'] for d in out], ['StatefulSet'])
        self.assertEqual(pod_spec(out[0])['volumes'],
                         [{'name': 'cfg', 'emptyDir': {}}])


class DroppedKindTest(unittest.TestCase):
    def test_traefik_and_ingress_objects_are_dropped(self):
        kinds = ['Ingress', 'ServersTransport', 'IngressRoute']
        docs = [{'kind': k, 'metadata': {'name': 'x'}} for k in kinds]
        service = {'kind': 'Service', 'metadata': {'name': 'x'}}
        out = render(docs + [service], NFS)
        self.assertEqual(out, [service])


class RequestCapTest(unittest.TestCase):
    def test_requests_above_the_cap_are_lowered_and_limits_kept(self):
        for cpu, memory in (('1000m', '2Gi'), ('2', '1G'), ('251m', '513Mi')):
            with self.subTest(cpu=cpu, memory=memory):
                doc = statefulset(containers=[container(
                    requests={'cpu': cpu, 'memory': memory},
                    limits=dict(LIMITS))])
                [out] = render([doc], NFS)
                resources = pod_spec(out)['containers'][0]['resources']
                self.assertEqual(resources['requests'],
                                 {'cpu': '250m', 'memory': '512Mi'})
                self.assertEqual(resources['limits'], LIMITS)

    def test_requests_below_the_cap_are_kept(self):
        requests = {'cpu': '100m', 'memory': '128Mi'}
        doc = statefulset(containers=[container(requests=dict(requests))])
        [out] = render([doc], NFS)
        self.assertEqual(
            pod_spec(out)['containers'][0]['resources']['requests'], requests)

    def test_init_container_requests_are_capped(self):
        init = container(requests={'cpu': '1', 'memory': '1Gi'})
        [out] = render([statefulset(init=[init])], NFS)
        self.assertEqual(
            pod_spec(out)['initContainers'][0]['resources']['requests'],
            {'cpu': '250m', 'memory': '512Mi'})


class UntouchedTest(unittest.TestCase):
    def test_image_and_probes_are_untouched(self):
        probe = {'exec': {'command': ['true']}, 'periodSeconds': 60}
        doc = statefulset(containers=[container(
            livenessProbe=copy.deepcopy(probe))])
        [out] = render([doc], NFS)
        rendered = pod_spec(out)['containers'][0]
        self.assertEqual(rendered['image'], 'example/app:1.2.3')
        self.assertEqual(rendered['livenessProbe'], probe)


class RepoManifestTest(unittest.TestCase):
    def test_storage_claims_are_read_from_cluster_storage(self):
        self.assertLessEqual({'app-configs', 'media', 'nextcloud', 'shoebox'},
                             nfs_claim_names(STORAGE))

    def test_mariadb_renders_for_k3d_with_its_image_unchanged(self):
        [source] = [d for d in load(MARIADB) if d['kind'] == 'StatefulSet']
        out = [d for d in render(load(MARIADB), nfs_claim_names(STORAGE))
               if d['kind'] == 'StatefulSet'][0]
        template = out['spec']['volumeClaimTemplates'][0]
        self.assertEqual(template['spec']['storageClassName'], 'local-path')
        self.assertEqual(pod_spec(out)['volumes'],
                         [{'name': 'nfs', 'emptyDir': {}}])
        self.assertEqual(pod_spec(out)['containers'][0]['image'],
                         pod_spec(source)['containers'][0]['image'])

    def test_cli_prints_the_rendered_manifest(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(['--storage', STORAGE, MARIADB]), 0)
        docs = list(yaml.safe_load_all(out.getvalue()))
        self.assertEqual([d['kind'] for d in docs],
                         ['StatefulSet', 'Service', 'Service'])
        self.assertEqual(pod_spec(docs[0])['volumes'],
                         [{'name': 'nfs', 'emptyDir': {}}])


if __name__ == '__main__':
    unittest.main()
