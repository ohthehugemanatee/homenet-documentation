"""Tests for autofix's agentic loop bounds."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import autofix  # noqa: E402


class LoopBudgetTest(unittest.TestCase):
    def test_turn_cap_is_below_the_old_tail(self):
        self.assertEqual(autofix.MAX_TURNS, 6)
        self.assertLess(autofix.MAX_TURNS, 15)

    def test_non_converging_loop_stops_at_cap_with_bounded_tool_results(self):
        calls = 0

        def tool_use(_messages, _system):
            nonlocal calls
            calls += 1
            return {
                'content': [{
                    'type': 'tool_use',
                    'id': f't{calls}',
                    'name': 'run_bash',
                    'input': {'command': 'printf x'},
                }],
                'stop_reason': 'tool_use',
                'usage': {},
            }

        messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'fix'}]}]
        with mock.patch.object(autofix, 'claude', side_effect=tool_use) as claude, \
                mock.patch.object(autofix, 'use_tool', return_value='x' * 8000):
            written, explanation = autofix.repair_loop(messages, 'system')

        self.assertEqual(claude.call_count, autofix.MAX_TURNS)
        self.assertEqual(written, [])
        self.assertEqual(explanation, '')

        tool_results = [
            b['content']
            for m in messages
            if m['role'] == 'user' and isinstance(m['content'], list)
            for b in m['content']
            if isinstance(b, dict) and b.get('type') == 'tool_result'
        ]
        self.assertEqual(len(tool_results), autofix.MAX_TURNS)
        self.assertLessEqual(
            sum(len(r.encode('utf-8')) for r in tool_results),
            autofix.MAX_TOOL_RESULT_BYTES,
        )


if __name__ == '__main__':
    unittest.main()
