"""Tests for check_recurring_jobs.

kubeconform skips these CRs (no longhorn.io schema), so a RecurringJob with a
typo'd task or a missing `groups` would pass every other lint job and then
silently schedule nothing.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from check_recurring_jobs import problems, undocumented  # noqa: E402


def job(name='daily-snapshots2', namespace='longhorn-system', **spec):
    full = {'cron': '33 4 * * ?', 'task': 'snapshot', 'groups': ['default'],
            'retain': 7, 'concurrency': 1}
    full.update(spec)
    return {'apiVersion': 'longhorn.io/v1beta2', 'kind': 'RecurringJob',
            'metadata': {'name': name, 'namespace': namespace}, 'spec': full}


class ProblemsTest(unittest.TestCase):
    def test_valid_job_has_no_problems(self):
        self.assertEqual(problems(job()), [])

    def test_every_supported_task_is_accepted(self):
        for task in ('snapshot', 'snapshot-cleanup', 'snapshot-delete',
                     'backup', 'backup-force-create', 'filesystem-trim'):
            self.assertEqual(problems(job(task=task)), [], task)

    def test_unknown_task_is_rejected(self):
        self.assertIn('task', ' '.join(problems(job(task='snapshots'))))

    def test_missing_namespace_is_rejected(self):
        doc = job()
        del doc['metadata']['namespace']
        self.assertIn('namespace', ' '.join(problems(doc)))

    def test_wrong_namespace_is_rejected(self):
        self.assertIn('namespace', ' '.join(problems(job(namespace='default'))))

    def test_missing_name_is_rejected(self):
        doc = job()
        del doc['metadata']['name']
        self.assertIn('name', ' '.join(problems(doc)))

    def test_empty_groups_is_rejected(self):
        # Longhorn runs the job against nothing rather than erroring.
        self.assertIn('groups', ' '.join(problems(job(groups=[]))))

    def test_missing_groups_is_rejected(self):
        doc = job()
        del doc['spec']['groups']
        self.assertIn('groups', ' '.join(problems(doc)))

    def test_cron_needs_five_fields(self):
        self.assertIn('cron', ' '.join(problems(job(cron='33 4 * *'))))

    def test_missing_cron_is_rejected(self):
        doc = job()
        del doc['spec']['cron']
        self.assertIn('cron', ' '.join(problems(doc)))

    def test_negative_retain_is_rejected(self):
        self.assertIn('retain', ' '.join(problems(job(retain=-1))))

    def test_zero_retain_is_allowed_for_non_snapshot_tasks(self):
        self.assertEqual(problems(job(task='filesystem-trim', retain=0)), [])

    def test_concurrency_below_one_is_rejected(self):
        self.assertIn('concurrency', ' '.join(problems(job(concurrency=0))))

    def test_non_integer_retain_is_rejected(self):
        self.assertIn('retain', ' '.join(problems(job(retain='7'))))

    def test_problems_are_reported_together(self):
        self.assertGreaterEqual(len(problems(job(task='x', groups=[]))), 2)


class UndocumentedTest(unittest.TestCase):
    README = """
    | Job | Task | Cron (UTC) |
    | --- | --- | --- |
    | `daily-snapshots2` | `snapshot` | `33 4 * * ?` |
    | `fs-trim` | `filesystem-trim` | `0 5 */6 * *` |
    """

    def test_documented_jobs_pass(self):
        self.assertEqual(undocumented(['daily-snapshots2', 'fs-trim'], self.README), [])

    def test_undocumented_job_is_reported(self):
        self.assertEqual(undocumented(['backups'], self.README), ['backups'])

    def test_substring_match_does_not_count_as_documented(self):
        # `fs-trim` appearing in the table must not vouch for `fs-trim-weekly`.
        self.assertEqual(undocumented(['fs-trim-weekly'], self.README), ['fs-trim-weekly'])

    def test_fenced_block_does_not_swallow_the_table(self):
        # A ``` run pairs with the prose backticks around it under a naive
        # regex, hiding every documented job behind one giant match.
        readme = self.README + '\n```sh\nkubectl apply -f x.yaml\n```\n'
        self.assertEqual(undocumented(['daily-snapshots2'], readme), [])

    def test_name_only_inside_a_fenced_block_is_not_documented(self):
        readme = '```\nbackups\n`backups`\n```\n'
        self.assertEqual(undocumented(['backups'], readme), ['backups'])


if __name__ == '__main__':
    unittest.main()
