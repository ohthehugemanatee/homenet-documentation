"""Tests for autofix's request payload — model, effort, and cache breakpoints.

A breakpoint that silently stops matching costs real money without failing
anything, so placement is asserted rather than eyeballed.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from autofix import MAX_CACHE_BREAKPOINTS, MODEL, build_payload  # noqa: E402


def user(text='hi'):
    return {'role': 'user', 'content': [{'type': 'text', 'text': text}]}


def assistant(text='ok'):
    return {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}


def breakpoints(payload):
    return [
        (i, j)
        for i, m in enumerate(payload['messages'])
        for j, b in enumerate(m['content'])
        if isinstance(b, dict) and 'cache_control' in b
    ]


class ModelTest(unittest.TestCase):
    def test_uses_sonnet(self):
        self.assertEqual(build_payload([user()], 's')['model'], MODEL)
        self.assertEqual(MODEL, 'claude-sonnet-5')

    def test_effort_is_low(self):
        payload = build_payload([user()], 's')
        self.assertEqual(payload['output_config']['effort'], 'low')

    def test_thinking_is_adaptive(self):
        payload = build_payload([user()], 's')
        self.assertEqual(payload['thinking'], {'type': 'adaptive'})

    def test_system_and_tools_still_sent(self):
        payload = build_payload([user()], 'sys prompt')
        self.assertEqual(payload['system'], 'sys prompt')
        self.assertTrue(payload['tools'])


class BreakpointTest(unittest.TestCase):
    def test_single_message_marked_once(self):
        # Static and rolling are the same block here; it must not double-mark.
        payload = build_payload([user()], 's')
        self.assertEqual(breakpoints(payload), [(0, 0)])

    def test_static_on_first_and_rolling_on_last(self):
        msgs = [user('first'), assistant(), user('latest')]
        self.assertEqual(breakpoints(build_payload(msgs, 's')), [(0, 0), (2, 0)])

    def test_rolling_moves_as_conversation_grows(self):
        msgs = [user('first')]
        build_payload(msgs, 's')
        msgs += [assistant(), user('second')]
        first_round = breakpoints(build_payload(msgs, 's'))
        msgs += [assistant(), user('third')]
        self.assertEqual(first_round, [(0, 0), (2, 0)])
        self.assertEqual(breakpoints(build_payload(msgs, 's')), [(0, 0), (4, 0)])

    def test_marks_last_block_of_a_multi_block_turn(self):
        msgs = [user('first'), assistant(), {'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': 'a', 'content': 'x'},
            {'type': 'tool_result', 'tool_use_id': 'b', 'content': 'y'},
        ]}]
        self.assertEqual(breakpoints(build_payload(msgs, 's')), [(0, 0), (2, 1)])

    def test_never_exceeds_the_api_cap(self):
        msgs = [user('first')]
        for _ in range(20):
            msgs += [assistant(), user()]
        self.assertLessEqual(len(breakpoints(build_payload(msgs, 's'))), MAX_CACHE_BREAKPOINTS)

    def test_assistant_turns_are_never_marked(self):
        # Thinking blocks must go back unchanged, so only user turns get marked.
        msgs = [user('first'), assistant(), user('latest'), assistant()]
        for i, _ in breakpoints(build_payload(msgs, 's')):
            self.assertEqual(msgs[i]['role'], 'user')

    def test_string_content_is_left_alone(self):
        msgs = [{'role': 'user', 'content': 'plain string'}]
        self.assertEqual(build_payload(msgs, 's')['messages'][0]['content'], 'plain string')


if __name__ == '__main__':
    unittest.main()
