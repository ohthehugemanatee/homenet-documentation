"""The AI review's request to the Anthropic API, and how it reads the reply."""

import json

MODEL = 'claude-sonnet-5-5'

REPORT_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'properties': {
        'findings': {
            'type': 'array',
            'description': 'Concrete issues found. Empty for a clean PR.',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'severity': {'type': 'string', 'enum': ['HIGH', 'MEDIUM', 'LOW']},
                    'confidence': {'type': 'string', 'enum': ['High', 'Medium', 'Low']},
                    'title': {'type': 'string', 'description': 'One line.'},
                    'detail': {'type': 'string', 'description': 'What is wrong and where.'},
                },
                'required': ['severity', 'confidence', 'title', 'detail'],
            },
        },
        'review_markdown': {'type': 'string', 'description': 'The full human-readable review body.'},
    },
    'required': ['findings', 'review_markdown'],
}


class ReviewError(Exception):
    """The reply cannot be trusted as a review, so the gate must not rule on it."""


def build_request(prompt):
    return {
        'model': MODEL,
        'max_tokens': 16000,
        'output_config': {'effort': 'medium', 'format': {'type': 'json_schema', 'schema': REPORT_SCHEMA}},
        'messages': [{'role': 'user', 'content': prompt}],
    }


def extract_report(response):
    """Return (findings, review_markdown) from the reply, or raise ReviewError."""
    stop = response.get('stop_reason')
    if stop == 'max_tokens':
        raise ReviewError('Response hit the token limit: findings may be incomplete, refusing to rule.')
    if stop == 'refusal':
        category = (response.get('stop_details') or {}).get('category')
        raise ReviewError(f'Response was refused (category: {category}), refusing to rule.')
    reply = ''.join(b.get('text', '') for b in response.get('content', []) if b.get('type') == 'text')
    try:
        report = json.loads(reply)
        return report.get('findings'), report.get('review_markdown') or '*(reviewer returned no review body)*'
    except (ValueError, AttributeError) as e:
        raise ReviewError(f'No report in response ({e}); stop_reason={stop}') from e
