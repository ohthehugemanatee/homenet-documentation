"""Pre-pass tests. Fixers run against a real git repo."""

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


class NoApiCallTest(unittest.TestCase):
    def run_main(self, prepass):
        event = {'workflow_run': {'id': 7, 'head_sha': 'abc',
                                  'pull_requests': [{'number': 3,
                                                     'head': {'ref': 'topic'}}]}}
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(event, f)
            path = f.name
        self.addCleanup(os.unlink, path)

        env = {'GITHUB_EVENT_PATH': path, 'REPO': 'o/r'}
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(autofix, 'head_repo_matches', return_value=True), \
                mock.patch.object(autofix, 'failed_job_names', return_value=['j']), \
                mock.patch.object(autofix, 'deterministic_pass', return_value=prepass), \
                mock.patch.object(autofix, 'claude') as claude, \
                mock.patch.object(autofix, 'finish') as finish, \
                mock.patch.object(autofix.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess(
                [], 0, stdout='ansible-lint failed', stderr='')
            claude.return_value = {'content': [], 'stop_reason': 'end_turn',
                                   'usage': {}}
            autofix.main()
        return claude, finish

    def test_successful_prepass_skips_the_api(self):
        claude, finish = self.run_main(['cluster/ansible/node-state.yaml'])
        claude.assert_not_called()
        finish.assert_called_once()
        self.assertEqual(finish.call_args.args[3], ['cluster/ansible/node-state.yaml'])

    def test_empty_prepass_falls_through_to_the_loop(self):
        claude, _ = self.run_main([])
        self.assertTrue(claude.called)


class CommitMarkerTest(unittest.TestCase):
    def test_commit_subject_carries_the_marker(self):
        with mock.patch.object(autofix.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout='', stderr='')
            autofix.finish('o/r', '3', 'topic', ['play.yaml'], 'why')
        subjects = [c.args[0][c.args[0].index('-m') + 1]
                    for c in run.call_args_list
                    if c.args and c.args[0][:2] == ['git', 'commit']]
        self.assertEqual(len(subjects), 1)
        self.assertIn('[autofix]', subjects[0].split('\n')[0])


if __name__ == '__main__':
    unittest.main()
