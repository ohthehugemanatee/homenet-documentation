"""Tests for the shared upgrade PreSync gate."""
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      '..', '..', '..', 'cluster', 'argocd', 'hooks',
                      'upgrade', 'gate.py')
spec = importlib.util.spec_from_file_location('gate', SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def workload(replicas=1, ready=1, updated=1, observed=2):
    return {'kind': 'StatefulSet',
            'metadata': {'name': 'app', 'generation': 2},
            'spec': {'replicas': replicas,
                     'selector': {'matchLabels': {'app': 'app'}}},
            'status': {'readyReplicas': ready, 'updatedReplicas': updated,
                       'observedGeneration': observed}}


def pod(name='app-0', ready=True, finished_at=None, app='app',
        deleting=False):
    container = {'name': 'main'}
    if finished_at:
        container['lastState'] = {'terminated': {'finishedAt': finished_at}}
    meta = {'name': name, 'labels': {'app': app, 'extra': 'x'}}
    if deleting:
        meta['deletionTimestamp'] = '2026-10-01T11:59:00Z'
    return {'metadata': meta,
            'status': {'conditions': [
                {'type': 'Ready', 'status': 'True' if ready else 'False'}],
                       'containerStatuses': [container]}}


class TestBlockers(unittest.TestCase):

    def test_healthy_app_passes(self):
        self.assertEqual(gate.blockers(workload(), [pod()], NOW), [])

    def test_unsettled_workload_blocks(self):
        for app in (workload(replicas=0, ready=0, updated=0),
                    workload(ready=0), workload(updated=0),
                    workload(observed=1)):
            with self.subTest(status=app['status'], spec=app['spec']):
                self.assertTrue(gate.blockers(app, [pod()], NOW))

    def test_unready_pod_is_named(self):
        self.assertEqual(gate.blockers(workload(), [pod(ready=False)], NOW),
                         ['pod app-0 is not Ready'])

    def test_restart_blocks_only_inside_the_window(self):
        recent = pod(finished_at='2026-10-01T11:50:00Z')
        old = pod(finished_at='2026-10-01T11:00:00Z')
        found = gate.blockers(workload(), [recent], NOW)
        self.assertEqual(len(found), 1)
        self.assertIn('app-0', found[0])
        self.assertEqual(gate.blockers(workload(), [old], NOW), [])

    def test_other_and_terminating_pods_are_ignored(self):
        pods = [pod(), pod('other-0', ready=False, app='other'),
                pod('app-1', ready=False, deleting=True)]
        self.assertEqual(gate.blockers(workload(), pods, NOW), [])

    def test_selector_without_match_labels_blocks(self):
        app = workload()
        app['spec']['selector'] = {'matchExpressions': []}
        self.assertTrue(gate.blockers(app, [pod()], NOW))

    def test_reports_every_blocker_not_just_the_first(self):
        found = gate.blockers(workload(ready=0),
                              [pod(ready=False,
                                   finished_at='2026-10-01T11:59:00Z')], NOW)
        self.assertEqual(len(found), 3)


class TestExitCode(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write(self, name, text):
        path = os.path.join(self.tmpdir, name)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        return path

    def _run(self, app, pods):
        return gate.main(['gate.py',
                          self._write('workload.json', json.dumps(app)),
                          self._write('pods.json',
                                      json.dumps({'items': pods}))], NOW)

    def test_healthy_exits_zero(self):
        self.assertEqual(self._run(workload(), [pod()]), 0)

    def test_unhealthy_exits_nonzero(self):
        self.assertEqual(self._run(workload(), [pod(ready=False)]), 1)

    def test_unreadable_state_exits_nonzero(self):
        app = self._write('workload.json', json.dumps(workload()))
        for pods in (os.path.join(self.tmpdir, 'missing.json'),
                     self._write('bad.json', 'not json')):
            with self.subTest(pods=pods):
                self.assertEqual(gate.main(['gate.py', app, pods], NOW), 1)


if __name__ == '__main__':
    unittest.main()
