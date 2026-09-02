"""Comment-budget and doc-currency rules stay in force. See #307."""
import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), '..', '..', '..')


def read(*parts):
    with open(os.path.join(ROOT, *parts)) as f:
        return f.read()


def checklist_items(template, heading):
    """Bold item names under one `## Part N:` heading of the PR template."""
    body = template.split(heading, 1)[1].split('\n## ', 1)[0].split('\n---', 1)[0]
    return re.findall(r'^- \[ \] \*\*(.+?)\*\*', body, re.MULTILINE)


class CommentBudgetRuleTest(unittest.TestCase):
    def setUp(self):
        self.rules = read('CLAUDE.md')

    def test_coding_behavior_caps_comment_content(self):
        section = self.rules.split('## Coding behavior', 1)[1].split('\n## ', 1)[0]
        self.assertIn('Comment budget', section)
        for subject in ('non-obvious invariant', 'workaround', 'constraint'):
            self.assertIn(subject, section)

    def test_coding_behavior_forbids_narrating_the_change(self):
        section = self.rules.split('## Coding behavior', 1)[1].split('\n## ', 1)[0]
        self.assertRegex(section, r'commit message and PR description')
        self.assertRegex(section, r'[Dd]elete it rather than trim it')

    def test_doc_currency_rule_defines_needs_updating(self):
        self.assertIn('"Needs updating" means', self.rules)
        self.assertIn('factually wrong', self.rules)


class ReviewChecklistParityTest(unittest.TestCase):
    """The AI reviewer is prompted with the same items the humans check."""

    def setUp(self):
        self.template = read('.github', 'pull_request_template.md')
        self.prompt = read('.github', 'workflows', 'pr-review.yaml')

    def test_part2_items_reach_the_reviewer_prompt(self):
        items = checklist_items(
            self.template, '## Part 2: MANDATORY AI-Specific Validation Checklist')
        self.assertIn('Comment Budget Check', items)
        for item in items:
            self.assertIn(item.removesuffix(' Check'), self.prompt, item)

    def test_part3_items_reach_the_reviewer_prompt(self):
        items = checklist_items(self.template, '## Part 3: Security & Privacy Review')
        self.assertTrue(items)
        for item in items:
            self.assertIn(item, self.prompt, item)

    def test_prompt_scores_comment_to_code_ratio(self):
        self.assertIn('against added code lines', self.prompt)
        self.assertIn('never HIGH', self.prompt)


if __name__ == '__main__':
    unittest.main()
