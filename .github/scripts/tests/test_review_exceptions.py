"""Tests for review_exceptions: the reviewer is sent only the exceptions that apply to a PR's paths."""

import os
import sys
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from review_exceptions import exceptions_for_paths, touched_paths  # noqa: E402

REAL_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'agentic-review-exceptions.yaml')

SAMPLE = """\
exceptions:
  - pattern: "alpha"
    files: [cluster/a.yaml]
    reason: >-
      Alpha reason.
  - pattern: "beta"
    files: [cluster/ansible/]
    reason: Beta reason.
  - pattern: "gamma"
    files: [docs/c.md, cluster/c.yaml]
    reason: Gamma reason.
  - pattern: "unscoped"
    reason: Applies everywhere.
"""


def header(old, new=None):
    return f'diff --git a/{old} b/{new or old}\n'


def patterns(text):
    return [e['pattern'] for e in yaml.safe_load(text)['exceptions']]


class TouchedPathsTest(unittest.TestCase):
    def test_modified_file(self):
        diff = header('cluster/a.yaml') + '--- a/cluster/a.yaml\n+++ b/cluster/a.yaml\n@@ -1 +1 @@\n-x\n+y\n'
        self.assertEqual(touched_paths(diff), {'cluster/a.yaml'})

    def test_rename_returns_old_and_new_path(self):
        diff = header('old/x.yaml', 'new/x.yaml') + 'rename from old/x.yaml\nrename to new/x.yaml\n'
        self.assertEqual(touched_paths(diff), {'old/x.yaml', 'new/x.yaml'})

    def test_added_and_deleted_files_exclude_dev_null(self):
        diff = (header('n.yaml') + '--- /dev/null\n+++ b/n.yaml\n@@ -0,0 +1 @@\n+x\n'
                + header('gone.yaml') + '--- a/gone.yaml\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n')
        self.assertEqual(touched_paths(diff), {'n.yaml', 'gone.yaml'})

    def test_binary_and_mode_only_changes_count(self):
        diff = header('img.png') + 'Binary files a/img.png and b/img.png differ\n' + header('run.sh') + 'new mode 100755\n'
        self.assertEqual(touched_paths(diff), {'img.png', 'run.sh'})

    def test_header_text_inside_a_hunk_is_not_a_path(self):
        diff = header('a.yaml') + '@@ -1 +1 @@\n+diff --git a/evil.yaml b/evil.yaml\n'
        self.assertEqual(touched_paths(diff), {'a.yaml'})


class ExceptionsForPathsTest(unittest.TestCase):
    def test_exact_path_keeps_that_entry_and_the_unscoped_one(self):
        text, kept, total = exceptions_for_paths(SAMPLE, {'cluster/a.yaml'})
        self.assertEqual(patterns(text), ['alpha', 'unscoped'])
        self.assertEqual((kept, total), (2, 4))

    def test_directory_prefix_matches_files_below_it(self):
        text, _, _ = exceptions_for_paths(SAMPLE, {'cluster/ansible/site.yaml'})
        self.assertEqual(patterns(text), ['beta', 'unscoped'])

    def test_directory_prefix_needs_the_slash_boundary(self):
        text, _, _ = exceptions_for_paths(SAMPLE, {'cluster/ansible-extra/x.yaml'})
        self.assertEqual(patterns(text), ['unscoped'])

    def test_exact_path_does_not_match_a_longer_name(self):
        text, _, _ = exceptions_for_paths(SAMPLE, {'cluster/a.yaml.bak'})
        self.assertEqual(patterns(text), ['unscoped'])

    def test_any_file_of_a_multi_file_entry_matches(self):
        text, _, _ = exceptions_for_paths(SAMPLE, {'cluster/c.yaml'})
        self.assertEqual(patterns(text), ['gamma', 'unscoped'])

    def test_entries_keep_their_fields(self):
        text, _, _ = exceptions_for_paths(SAMPLE, {'cluster/a.yaml'})
        self.assertEqual(yaml.safe_load(text)['exceptions'][0],
                         {'pattern': 'alpha', 'files': ['cluster/a.yaml'], 'reason': 'Alpha reason.'})

    def test_nothing_kept_returns_empty_text(self):
        scoped = 'exceptions:\n  - pattern: "a"\n    files: [x.yaml]\n    reason: r\n'
        self.assertEqual(exceptions_for_paths(scoped, {'README.md'}), ('', 0, 1))

    def test_unparseable_file_comes_back_unchanged(self):
        broken = 'exceptions: [unclosed'
        self.assertEqual(exceptions_for_paths(broken, {'a'}), (broken, None, None))

    def test_file_without_an_exceptions_list_comes_back_unchanged(self):
        for text in ('other: 1\n', 'exceptions: {a: b}\n', 'exceptions:\n', '- just\n- a list\n'):
            with self.subTest(text=text):
                self.assertEqual(exceptions_for_paths(text, {'a'}), (text, None, None))


class RealExceptionsFileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(REAL_FILE) as f:
            cls.text = f.read()
        cls.entries = yaml.safe_load(cls.text)['exceptions']

    def test_every_entry_is_path_scoped(self):
        for entry in self.entries:
            with self.subTest(pattern=entry['pattern']):
                self.assertTrue(entry.get('files'), 'an unscoped entry is sent with every review')
                self.assertIsInstance(entry['files'], list)

    def test_each_entry_is_selected_by_its_own_paths(self):
        probes = {f + 'x' if f.endswith('/') else f for e in self.entries for f in e['files']}
        _, kept, total = exceptions_for_paths(self.text, probes)
        self.assertEqual((kept, total), (len(self.entries), len(self.entries)))

    def test_an_unrelated_path_keeps_nothing(self):
        self.assertEqual(exceptions_for_paths(self.text, {'no/such/file.txt'}), ('', 0, len(self.entries)))


if __name__ == '__main__':
    unittest.main()
