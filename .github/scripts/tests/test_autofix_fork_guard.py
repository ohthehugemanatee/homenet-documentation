"""Tests for autofix's fork guard.

The guard runs before everything else, so getting it wrong either stops
autofix dead (#385) or lets a fork PR through, where the push would leak
write access.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from autofix import head_repo_matches  # noqa: E402

REPO = 'owner/repo'


def gh(stdout, returncode=0):
    return mock.Mock(stdout=stdout, returncode=returncode)


class ForkGuardTest(unittest.TestCase):
    def test_same_repo_matches(self):
        with mock.patch('autofix.subprocess.run', return_value=gh('owner/repo\n')):
            self.assertTrue(head_repo_matches(REPO, '1'))

    def test_fork_does_not_match(self):
        with mock.patch('autofix.subprocess.run', return_value=gh('someone/fork\n')):
            self.assertFalse(head_repo_matches(REPO, '1'))

    def test_failed_lookup_fails_closed(self):
        with mock.patch('autofix.subprocess.run', return_value=gh('', 1)):
            self.assertFalse(head_repo_matches(REPO, '1'))

    def test_empty_output_fails_closed(self):
        with mock.patch('autofix.subprocess.run', return_value=gh('\n')):
            self.assertFalse(head_repo_matches(REPO, '1'))

    def test_deleted_head_repo_fails_closed(self):
        # jq renders a null head.repo as the literal string "null".
        with mock.patch('autofix.subprocess.run', return_value=gh('null\n')):
            self.assertFalse(head_repo_matches(REPO, '1'))

    def test_resolves_from_the_api_not_the_event_payload(self):
        # #385: workflow_run's pull_requests[] has no full_name to read.
        with mock.patch('autofix.subprocess.run', return_value=gh('owner/repo\n')) as run:
            head_repo_matches(REPO, '42')
        argv = run.call_args[0][0]
        self.assertEqual(argv[:2], ['gh', 'api'])
        self.assertIn('repos/owner/repo/pulls/42', argv)


if __name__ == '__main__':
    unittest.main()
