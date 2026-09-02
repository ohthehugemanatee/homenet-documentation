"""The steward skill states when to stop polling a PR. See #313."""
import os
import unittest

SKILL = os.path.join(
    os.path.dirname(__file__), '..', '..', '..',
    '.claude', 'skills', 'steward', 'SKILL.md')


class StewardSkillTest(unittest.TestCase):
    def setUp(self):
        with open(SKILL) as f:
            self.skill = f.read()

    def test_names_all_three_skip_conditions(self):
        for condition in ('completed successfully', 'merge conflict', 'review thread'):
            self.assertIn(condition, self.skill, condition)

    def test_requires_rearming_when_the_pr_stops_being_green(self):
        self.assertIn('re-arm', self.skill.lower())


if __name__ == '__main__':
    unittest.main()
