"""Tests for the deterministic pre-pass that runs before the agentic loop.

The fixers are driven through a real git repository rather than a mocked
subprocess, because the revert path and the `.github/` guard are the parts
that must not be wrong and both are git behaviour.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import autofix  # noqa: E402


def sh(*args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, check=True, **kwargs)


def fixer(fix, check='true', setup=(), cwd=None):
    return {
        'setup': [['sh', '-c', c] for c in setup],
        'fix': ['sh', '-c', fix],
        'check': ['sh', '-c', check],
        'cwd': cwd,
    }


class RepoFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        repo = self.tmp.name
        sh('git', 'init', '-q', '-b', 'main', repo)
        sh('git', 'config', 'user.email', 'test@example.com', cwd=repo)
        sh('git', 'config', 'user.name', 'test', cwd=repo)
        os.makedirs(os.path.join(repo, '.github', 'workflows'))
        for path, body in (('play.yaml', 'original\n'),
                           ('roles.yaml', 'original\n'),
                           ('.github/workflows/ci.yaml', 'original\n')):
            with open(os.path.join(repo, path), 'w') as f:
                f.write(body)
        sh('git', 'add', '-A', cwd=repo)
        sh('git', 'commit', '-qm', 'init', cwd=repo)

        cwd = os.getcwd()
        os.chdir(repo)
        self.addCleanup(os.chdir, cwd)
        self.repo = repo

    def body(self, path):
        with open(os.path.join(self.repo, path)) as f:
            return f.read()

    def dirty(self):
        r = sh('git', 'status', '--porcelain', cwd=self.repo)
        return r.stdout.strip()


class PrePassTest(RepoFixture):
    def test_clean_check_keeps_the_fix(self):
        with mock.patch.dict(autofix.FIXERS,
                             {'Ansible playbooks': fixer("echo fixed > play.yaml")},
                             clear=True):
            self.assertEqual(autofix.deterministic_pass(['Ansible playbooks']),
                             ['play.yaml'])
        self.assertEqual(self.body('play.yaml'), 'fixed\n')

    def test_failing_check_reverts_the_fix(self):
        with mock.patch.dict(autofix.FIXERS,
                             {'Ansible playbooks': fixer("echo fixed > play.yaml",
                                                         check='false')},
                             clear=True):
            self.assertEqual(autofix.deterministic_pass(['Ansible playbooks']), [])
        self.assertEqual(self.body('play.yaml'), 'original\n')
        self.assertEqual(self.dirty(), '')

    def test_write_under_dot_github_reverts_everything(self):
        with mock.patch.dict(
            autofix.FIXERS,
            {'Ansible playbooks': fixer(
                "echo fixed > play.yaml && echo fixed > .github/workflows/ci.yaml")},
            clear=True,
        ):
            self.assertEqual(autofix.deterministic_pass(['Ansible playbooks']), [])
        self.assertEqual(self.body('.github/workflows/ci.yaml'), 'original\n')
        self.assertEqual(self.body('play.yaml'), 'original\n')
        self.assertEqual(self.dirty(), '')

    def test_no_fixer_for_the_failing_job(self):
        with mock.patch.dict(autofix.FIXERS,
                             {'Ansible playbooks': fixer("echo fixed > play.yaml")},
                             clear=True):
            self.assertEqual(autofix.deterministic_pass(['Kustomize builds']), [])
        self.assertEqual(self.dirty(), '')

    def test_fixer_that_changes_nothing(self):
        with mock.patch.dict(autofix.FIXERS,
                             {'Ansible playbooks': fixer("true")},
                             clear=True):
            self.assertEqual(autofix.deterministic_pass(['Ansible playbooks']), [])

    def test_failed_setup_skips_the_fixer(self):
        with mock.patch.dict(
            autofix.FIXERS,
            {'Ansible playbooks': fixer("echo fixed > play.yaml", setup=('false',))},
            clear=True,
        ):
            self.assertEqual(autofix.deterministic_pass(['Ansible playbooks']), [])
        self.assertEqual(self.body('play.yaml'), 'original\n')

    def test_untracked_file_left_by_a_fixer_is_not_committed(self):
        with mock.patch.dict(
            autofix.FIXERS,
            {'Ansible playbooks': fixer("echo fixed > play.yaml && echo x > scratch")},
            clear=True,
        ):
            self.assertEqual(autofix.deterministic_pass(['Ansible playbooks']),
                             ['play.yaml'])

    def test_second_fixer_reports_only_its_own_paths(self):
        with mock.patch.dict(
            autofix.FIXERS,
            {'A': fixer("echo a > play.yaml"),
             'B': fixer("echo b > roles.yaml")},
            clear=True,
        ):
            self.assertEqual(autofix.deterministic_pass(['A', 'B']),
                             ['play.yaml', 'roles.yaml'])


class FailedJobNamesTest(unittest.TestCase):
    def test_parses_one_name_per_line(self):
        with mock.patch.object(autofix.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess(
                [], 0, stdout='Ansible playbooks\nYAML syntax\n', stderr='')
            self.assertEqual(autofix.failed_job_names('o/r', '1'),
                             ['Ansible playbooks', 'YAML syntax'])

    def test_api_failure_yields_no_names(self):
        with mock.patch.object(autofix.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 1, stdout='', stderr='x')
            self.assertEqual(autofix.failed_job_names('o/r', '1'), [])


if __name__ == '__main__':
    unittest.main()
