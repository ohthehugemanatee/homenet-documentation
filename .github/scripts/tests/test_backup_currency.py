"""Tests for the weekly backup currency check."""
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      '..', '..', '..', 'cluster', 'jobs',
                      'backup_currency.py')
spec = importlib.util.spec_from_file_location('backup_currency', SCRIPT)
currency = importlib.util.module_from_spec(spec)
spec.loader.exec_module(currency)

NOW = datetime(2026, 10, 19, 11, 0, tzinfo=timezone.utc)
GROUP = 'recurring-job-group.longhorn.io/default'


def vol(name, group='enabled', created='2026-01-01T00:00:00Z'):
    labels = {GROUP: group} if group else {}
    return {'metadata': {'name': name, 'labels': labels,
                         'creationTimestamp': created},
            'status': {'kubernetesStatus': {'namespace': 'default',
                                            'pvcName': f'claim-{name}'}}}


def backup(volume, created, state='Completed'):
    return {'metadata': {'name': f'backup-{volume}-{created}'},
            'status': {'volumeName': volume, 'state': state,
                       'backupCreatedAt': created}}


class TestStale(unittest.TestCase):

    def test_recent_backup_passes(self):
        self.assertEqual(currency.stale(
            [vol('pvc-a')], [backup('pvc-a', '2026-10-19T05:10:00Z')], NOW),
            [])

    def test_backup_older_than_eight_days_is_named(self):
        found = currency.stale(
            [vol('pvc-a')], [backup('pvc-a', '2026-10-10T05:10:00Z')], NOW)
        self.assertEqual(len(found), 1)
        self.assertIn('default/claim-pvc-a', found[0])

    def test_newest_completed_backup_counts(self):
        backups = [backup('pvc-a', '2026-10-05T05:00:00Z'),
                   backup('pvc-a', '2026-10-19T05:00:00Z'),
                   backup('pvc-a', '2026-10-19T06:00:00Z', state='Error')]
        self.assertEqual(currency.stale([vol('pvc-a')], backups, NOW), [])

    def test_only_failed_backups_count_as_none(self):
        found = currency.stale(
            [vol('pvc-a')],
            [backup('pvc-a', '2026-10-19T05:00:00Z', state='Error')], NOW)
        self.assertEqual(len(found), 1)
        self.assertIn('no completed backup', found[0])

    def test_young_volume_without_backup_passes(self):
        self.assertEqual(
            currency.stale([vol('pvc-a', created='2026-10-15T00:00:00Z')],
                           [], NOW), [])

    def test_other_groups_and_orphan_backups_are_ignored(self):
        volumes = [vol('pvc-a', group=None), vol('pvc-b', group='disabled')]
        backups = [backup('pvc-gone', '2025-01-01T00:00:00Z')]
        self.assertEqual(currency.stale(volumes, backups, NOW), [])

    def test_reports_every_stale_volume(self):
        found = currency.stale([vol('pvc-a'), vol('pvc-b')], [], NOW)
        self.assertEqual(len(found), 2)


class TestExitCode(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write(self, name, text):
        path = os.path.join(self.tmpdir, name)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        return path

    def _run(self, volumes, backups):
        return currency.main(
            ['backup_currency.py',
             self._write('volumes.json', json.dumps({'items': volumes})),
             self._write('backups.json', json.dumps({'items': backups}))],
            NOW)

    def test_current_backups_exit_zero(self):
        self.assertEqual(
            self._run([vol('pvc-a')],
                      [backup('pvc-a', '2026-10-19T05:00:00Z')]), 0)

    def test_stale_backup_exits_nonzero(self):
        self.assertEqual(
            self._run([vol('pvc-a')],
                      [backup('pvc-a', '2026-09-01T05:00:00Z')]), 1)

    def test_no_default_group_volumes_exits_nonzero(self):
        self.assertEqual(self._run([vol('pvc-a', group=None)], []), 1)

    def test_unreadable_state_exits_nonzero(self):
        volumes = self._write('volumes.json', json.dumps({'items': []}))
        for backups in (os.path.join(self.tmpdir, 'missing.json'),
                        self._write('bad.json', 'not json')):
            with self.subTest(backups=backups):
                self.assertEqual(currency.main(
                    ['backup_currency.py', volumes, backups], NOW), 1)


if __name__ == '__main__':
    unittest.main()
