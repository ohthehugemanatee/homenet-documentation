"""Tests for check_default_tls_managed.

The failure this guards is silent for weeks. Deleting the Certificate leaves
the issued Secret in place, Traefik keeps serving it, and nothing reports a
problem until the certificate expires and every internal host breaks at once.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from check_default_tls_managed import (  # noqa: E402
    app_sources, covers, expand_braces, problems)

STORE = ('cluster/services/traefik-default-tls.yaml', 'default', 'wildcard-tls')
CERT = ('cluster/services/berlin-wildcard-cert.yaml', 'berlin-wildcard',
        'wildcard-tls')


def source(path='cluster/services', include=None, exclude=None, recurse=None):
    directory = {}
    if include is not None:
        directory['include'] = include
    if exclude is not None:
        directory['exclude'] = exclude
    if recurse is not None:
        directory['recurse'] = recurse
    src = {'path': path}
    if directory:
        src['directory'] = directory
    return src


COVERING = [source(include='{berlin-wildcard-cert.yaml,'
                           'traefik-default-tls.yaml}')]


class ProblemsTest(unittest.TestCase):
    def test_managed_store_and_certificate_pass(self):
        self.assertEqual(problems([STORE], [CERT], COVERING), [])

    def test_unmanaged_certificate_is_rejected(self):
        found = problems([STORE], [CERT],
                         [source(include='traefik-default-tls.yaml')])
        self.assertTrue(any('berlin-wildcard-cert.yaml' in p and
                            'not reconciled' in p for p in found), found)

    def test_unmanaged_store_is_rejected(self):
        found = problems([STORE], [CERT],
                         [source(include='berlin-wildcard-cert.yaml')])
        self.assertTrue(any('TLSStore' in p and 'nothing restores it' in p
                            for p in found), found)

    def test_secret_no_certificate_issues_is_rejected(self):
        found = problems([STORE], [], COVERING)
        self.assertTrue(any('no Certificate manifest' in p for p in found),
                        found)

    def test_certificate_for_another_secret_does_not_count(self):
        other = ('cluster/services/other.yaml', 'other', 'some-other-tls')
        found = problems([STORE], [other], COVERING)
        self.assertTrue(any('no Certificate manifest' in p for p in found),
                        found)

    def test_no_store_is_not_a_problem(self):
        self.assertEqual(problems([], [CERT], []), [])


class CoversTest(unittest.TestCase):
    def test_include_glob_matches(self):
        self.assertTrue(covers(source(include='*.yaml'), STORE[0]))

    def test_include_glob_excludes_other_files(self):
        self.assertFalse(covers(source(include='plex.yaml'), STORE[0]))

    def test_absent_include_covers_the_whole_directory(self):
        self.assertTrue(covers(source(), STORE[0]))

    def test_exclude_wins_over_include(self):
        src = source(include='*.yaml', exclude='traefik-default-tls.yaml')
        self.assertFalse(covers(src, STORE[0]))

    def test_nested_file_needs_recurse(self):
        nested = 'cluster/services/collabora/collabora.yaml'
        self.assertFalse(covers(source(), nested))
        self.assertTrue(covers(source(recurse=True), nested))
        self.assertTrue(covers(source(path='cluster/services/collabora'),
                               nested))

    def test_sibling_directory_does_not_cover(self):
        self.assertFalse(covers(source(path='cluster/argocd'), STORE[0]))

    def test_partial_directory_name_does_not_cover(self):
        # 'cluster/serv' is a string prefix of 'cluster/services' but not a
        # parent directory of it.
        self.assertFalse(covers(source(path='cluster/serv'), STORE[0]))


class BracesTest(unittest.TestCase):
    def test_plain_pattern_is_unchanged(self):
        self.assertEqual(expand_braces('plex.yaml'), ['plex.yaml'])

    def test_alternation_expands(self):
        self.assertEqual(expand_braces('{a.yaml,b.yaml}'),
                         ['a.yaml', 'b.yaml'])

    def test_alternation_keeps_head_and_tail(self):
        self.assertEqual(expand_braces('x/{a,b}.yaml'),
                         ['x/a.yaml', 'x/b.yaml'])

    def test_unbalanced_brace_is_left_alone(self):
        self.assertEqual(expand_braces('{a,b'), ['{a,b'])


class AppSourcesTest(unittest.TestCase):
    def test_single_source(self):
        doc = {'kind': 'Application', 'spec': {'source': source()}}
        self.assertEqual(app_sources(doc), [source()])

    def test_multi_source_drops_entries_without_a_path(self):
        doc = {'kind': 'Application',
               'spec': {'sources': [{'chart': 'cert-manager'}, source()]}}
        self.assertEqual(app_sources(doc), [source()])

    def test_non_application_is_ignored(self):
        self.assertEqual(app_sources({'kind': 'Certificate', 'spec': {}}), [])


if __name__ == '__main__':
    unittest.main()
