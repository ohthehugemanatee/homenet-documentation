"""Tests for review_verdict — the gate's block/pass decision.

The gate blocks a PR on this logic, so a wrong answer either lets a real
HIGH finding through or hard-blocks a clean PR. Both directions are tested.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from review_verdict import decide_verdict, render_findings  # noqa: E402


def finding(severity='HIGH', confidence='High', title='t', detail='d'):
    return {'severity': severity, 'confidence': confidence,
            'title': title, 'detail': detail}


class DecideVerdictTest(unittest.TestCase):
    def test_no_findings_passes(self):
        blocking, reason = decide_verdict([])
        self.assertFalse(blocking)
        self.assertIn('no blocking', reason.lower())

    def test_high_high_blocks(self):
        blocking, reason = decide_verdict([finding('HIGH', 'High')])
        self.assertTrue(blocking)
        self.assertIn('1', reason)

    def test_high_medium_blocks(self):
        blocking, _ = decide_verdict([finding('HIGH', 'Medium')])
        self.assertTrue(blocking)

    def test_high_low_confidence_passes(self):
        # A low-confidence HIGH is reported but must not hard-block CI.
        blocking, _ = decide_verdict([finding('HIGH', 'Low')])
        self.assertFalse(blocking)

    def test_medium_high_passes(self):
        blocking, _ = decide_verdict([finding('MEDIUM', 'High')])
        self.assertFalse(blocking)

    def test_low_passes(self):
        blocking, _ = decide_verdict([finding('LOW', 'High')])
        self.assertFalse(blocking)

    def test_mixed_list_blocks_on_the_one_high(self):
        blocking, reason = decide_verdict([
            finding('LOW', 'High'),
            finding('MEDIUM', 'High'),
            finding('HIGH', 'Medium', title='wildcard verbs in ClusterRole'),
        ])
        self.assertTrue(blocking)
        self.assertIn('wildcard verbs in ClusterRole', reason)

    def test_counts_every_blocking_finding(self):
        blocking, reason = decide_verdict([
            finding('HIGH', 'High'), finding('HIGH', 'Medium'),
        ])
        self.assertTrue(blocking)
        self.assertIn('2', reason)

    # --- fail closed on anything we cannot read ---

    def test_missing_severity_blocks(self):
        blocking, _ = decide_verdict([{'confidence': 'High', 'title': 't'}])
        self.assertTrue(blocking)

    def test_unknown_severity_blocks(self):
        blocking, _ = decide_verdict([finding('CATASTROPHIC', 'High')])
        self.assertTrue(blocking)

    def test_missing_confidence_blocks_when_high(self):
        blocking, _ = decide_verdict([{'severity': 'HIGH', 'title': 't'}])
        self.assertTrue(blocking)

    def test_non_dict_finding_blocks(self):
        blocking, _ = decide_verdict(['just a string'])
        self.assertTrue(blocking)

    def test_findings_not_a_list_blocks(self):
        blocking, _ = decide_verdict(None)
        self.assertTrue(blocking)

    def test_severity_matching_is_case_insensitive(self):
        # The schema pins the casing, but a model that returns "high"
        # must not silently become a non-blocking unknown severity.
        blocking, _ = decide_verdict([finding('high', 'high')])
        self.assertTrue(blocking)


class RenderFindingsTest(unittest.TestCase):
    def test_empty_says_so(self):
        self.assertIn('No findings', render_findings([]))

    def test_includes_severity_confidence_title_and_detail(self):
        out = render_findings([
            finding('HIGH', 'Medium', 'wildcard verbs', 'ClusterRole grants *'),
        ])
        self.assertIn('HIGH', out)
        self.assertIn('Medium', out)
        self.assertIn('wildcard verbs', out)
        self.assertIn('ClusterRole grants *', out)

    def test_orders_high_first(self):
        out = render_findings([
            finding('LOW', 'High', 'low-thing'),
            finding('HIGH', 'High', 'high-thing'),
        ])
        self.assertLess(out.index('high-thing'), out.index('low-thing'))

    def test_survives_malformed_entries(self):
        # Rendering must never raise — the comment still has to get posted
        # so a human can see what the reviewer actually said.
        out = render_findings(['nonsense', {}, finding()])
        self.assertIsInstance(out, str)
        self.assertTrue(out)


if __name__ == '__main__':
    unittest.main()
