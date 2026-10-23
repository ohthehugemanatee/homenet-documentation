"""Tests for the weekly restore check's choice of backup."""
import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      '..', '..', '..', 'cluster', 'jobs',
                      'restore_target.py')
spec = importlib.util.spec_from_file_location('restore_target', SCRIPT)
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)


class Last:
    def choice(self, seq):
        return seq[-1]


def vol(name, claim):
    return {'metadata': {'name': name},
            'status': {'kubernetesStatus': {'namespace': 'default',
                                            'pvcName': claim}}}


def backup(name, volume, created, state='Completed', size='3221225472'):
    return {'metadata': {'name': name},
            'status': {'volumeName': volume, 'state': state,
                       'backupCreatedAt': created, 'volumeSize': size}}


VOLUMES = [vol('pvc-r', 'radarr-db-radarr-0'),
           vol('pvc-s', 'sonarr-db-sonarr-0'),
           vol('pvc-x', 'plex-config-plex-0')]
CLAIMS = ['default/radarr-db-radarr-0', 'default/sonarr-db-sonarr-0']


class TestChoose(unittest.TestCase):

    def test_newest_completed_backup_of_the_chosen_claim(self):
        backups = [backup('backup-old', 'pvc-s', '2026-10-05T05:00:00Z'),
                   backup('backup-new', 'pvc-s', '2026-10-12T05:00:00Z'),
                   backup('backup-bad', 'pvc-s', '2026-10-19T05:00:00Z',
                          state='Error')]
        self.assertEqual(
            target.choose(VOLUMES, backups, CLAIMS, Last()),
            {'CLAIM': 'default/sonarr-db-sonarr-0',
             'SNAPSHOT_HANDLE': 'bak://pvc-s/backup-new',
             'SIZE': '3221225472'})

    def test_only_configured_claims_with_a_backup_are_candidates(self):
        backups = [backup('backup-r', 'pvc-r', '2026-10-12T05:00:00Z'),
                   backup('backup-x', 'pvc-x', '2026-10-12T05:00:00Z')]
        chosen = target.choose(VOLUMES, backups, CLAIMS, Last())
        self.assertEqual(chosen['SNAPSHOT_HANDLE'], 'bak://pvc-r/backup-r')

    def test_no_candidate_returns_none(self):
        backups = [backup('backup-x', 'pvc-x', '2026-10-12T05:00:00Z')]
        self.assertIsNone(target.choose(VOLUMES, backups, CLAIMS, Last()))


class TestMain(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.out = os.path.join(self.tmpdir, 'restore.env')

    def _write(self, name, text):
        path = os.path.join(self.tmpdir, name)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        return path

    def _run(self, claims, backups):
        argv = ['restore_target.py',
                self._write('volumes.json', json.dumps({'items': VOLUMES})),
                self._write('backups.json', json.dumps({'items': backups})),
                self.out]
        with mock.patch.dict(os.environ, {'RESTORE_CLAIMS': claims}):
            return target.main(argv)

    def test_writes_the_choice_as_shell_assignments(self):
        rc = self._run(CLAIMS[0], [backup('backup-r', 'pvc-r',
                                          '2026-10-12T05:00:00Z')])
        self.assertEqual(rc, 0)
        with open(self.out, encoding='utf-8') as handle:
            self.assertIn("SNAPSHOT_HANDLE='bak://pvc-r/backup-r'\n",
                          handle.read())

    def test_no_backup_for_any_configured_claim_exits_nonzero(self):
        self.assertEqual(self._run(','.join(CLAIMS), []), 1)
        self.assertFalse(os.path.exists(self.out))

    def test_no_configured_claims_writes_nothing(self):
        self.assertEqual(self._run('', []), 0)
        self.assertFalse(os.path.exists(self.out))

    def test_unreadable_state_exits_nonzero(self):
        argv = ['restore_target.py', os.path.join(self.tmpdir, 'missing'),
                self._write('backups.json', '{}'), self.out]
        with mock.patch.dict(os.environ, {'RESTORE_CLAIMS': CLAIMS[0]}):
            self.assertEqual(target.main(argv), 1)


if __name__ == '__main__':
    unittest.main()
