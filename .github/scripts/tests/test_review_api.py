"""Tests for review_api: a reply the gate cannot trust must raise, never read as a clean review."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from review_api import REPORT_SCHEMA, ReviewError, build_request, extract_report, usage_line  # noqa: E402


def text(payload):
    return {'type': 'text', 'text': payload if isinstance(payload, str) else json.dumps(payload)}


def reply(*blocks, stop_reason='end_turn', **extra):
    return {'type': 'message', 'stop_reason': stop_reason, 'content': list(blocks), **extra}


def closed(schema):
    if isinstance(schema, dict):
        return (schema.get('type') != 'object' or schema.get('additionalProperties') is False) and all(
            closed(v) for v in schema.values())
    return all(closed(v) for v in schema) if isinstance(schema, list) else True


class BuildRequestTest(unittest.TestCase):
    def test_sonnet_5_5_with_a_json_schema_and_medium_effort(self):
        request = build_request('the prompt')
        self.assertEqual(request['model'], 'claude-sonnet-5-5')
        self.assertEqual(request['output_config'],
                         {'effort': 'medium', 'format': {'type': 'json_schema', 'schema': REPORT_SCHEMA}})
        self.assertEqual(request['messages'], [{'role': 'user', 'content': 'the prompt'}])

    def test_omits_parameters_sonnet_5_5_rejects(self):
        for key in ('tools', 'tool_choice', 'thinking', 'temperature', 'top_p', 'top_k'):
            self.assertNotIn(key, build_request('p'))

    def test_every_object_in_the_schema_is_closed(self):
        self.assertTrue(closed(REPORT_SCHEMA))
        self.assertFalse(closed({'type': 'object', 'properties': {'a': {'type': 'object', 'additionalProperties': False}}}))


class ExtractReportTest(unittest.TestCase):
    def test_reads_the_text_block_after_a_thinking_block(self):
        finding = {'severity': 'HIGH', 'confidence': 'High', 'title': 't', 'detail': 'd'}
        response = reply({'type': 'thinking', 'thinking': ''}, text({'findings': [finding], 'review_markdown': 'body'}))
        self.assertEqual(extract_report(response), ([finding], 'body'))

    def test_missing_review_body_gets_a_placeholder(self):
        _, review = extract_report(reply(text({'findings': []})))
        self.assertIn('no review body', review)

    def test_findings_that_are_not_a_list_reach_the_verdict(self):
        findings, _ = extract_report(reply(text({'findings': 'oops', 'review_markdown': 'b'})))
        self.assertEqual(findings, 'oops')

    def test_untrustworthy_replies_raise_with_the_reason(self):
        cases = {
            'truncated': (reply(text({'findings': []}), stop_reason='max_tokens'), 'token limit'),
            'refused': (reply(stop_reason='refusal', stop_details={'category': 'cyber'}), 'cyber'),
            'no text block': (reply({'type': 'thinking', 'thinking': ''}), 'No report'),
            'bad json': (reply(text('{"findings": [')), 'No report'),
            'not an object': (reply(text('[]')), 'No report'),
        }
        for name, (response, reason) in cases.items():
            with self.subTest(name), self.assertRaisesRegex(ReviewError, reason):
                extract_report(response)


class UsageLineTest(unittest.TestCase):
    def test_each_token_kind_is_priced_at_the_sonnet_5_5_list_price(self):
        usage = {'input_tokens': 1_000_000, 'output_tokens': 100_000,
                 'cache_creation_input_tokens': 10_000, 'cache_read_input_tokens': 1_000}
        self.assertEqual(
            usage_line(usage),
            'Usage: input 1,000,000 | output 100,000 | cache write 10,000 | cache read 1,000 | est. $3.0251')

    def test_missing_and_null_cache_fields_count_as_zero(self):
        usage = {'input_tokens': 1000, 'output_tokens': 500, 'cache_read_input_tokens': None}
        self.assertEqual(usage_line(usage), 'Usage: input 1,000 | output 500 | cache write 0 | cache read 0 | est. $0.0070')

    def test_missing_usage_does_not_raise(self):
        self.assertEqual(usage_line(None), 'Usage: not reported')


if __name__ == '__main__':
    unittest.main()
