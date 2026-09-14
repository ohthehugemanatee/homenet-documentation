"""Comment-budget and doc-currency rules stay in force. See #307."""
import ast
import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), '..', '..', '..')
# Static prompt character count from .github/workflows/pr-review.yaml at
# 9c7ff57c0807df39b65ca913fd4b1a107f082174, before this PR removed step 3b.
PRE_STEP_3B_STATIC_PROMPT_CHARS = 4716


def read(*parts):
    with open(os.path.join(ROOT, *parts)) as f:
        return f.read()


def checklist_items(template, heading):
    """Bold item names under one `## Part N:` heading of the PR template."""
    body = template.split(heading, 1)[1].split('\n## ', 1)[0].split('\n---', 1)[0]
    return re.findall(r'^- \[ \] \*\*(.+?)\*\*', body, re.MULTILINE)


def review_prompt_static_chars(prompt_workflow):
    """Count literal prompt text, excluding diff and prior-review runtime payloads."""
    source = re.search(
        r"python3 << 'PYEOF'\n(.*?)\n\s*PYEOF", prompt_workflow, re.DOTALL
    ).group(1)
    source = re.sub(r'^ {10}', '', source, flags=re.MULTILINE)
    module = ast.parse(source)
    assignment = next(
        node for node in ast.walk(module)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'prompt'
                for target in node.targets)
    )

    def count_string_literals(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return len(node.value)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return count_string_literals(node.left) + count_string_literals(node.right)
        if isinstance(node, ast.Name):
            return 0
        return sum(count_string_literals(child) for child in ast.iter_child_nodes(node))

    return count_string_literals(assignment.value)


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

    def test_scanner_covered_security_part_stays_out_of_ai_review(self):
        self.assertNotIn('## Part 3: Security & Privacy Review', self.template)
        self.assertNotIn('Security & Privacy Review', self.prompt)
        for scanner_covered_item in (
                'Secrets', 'RBAC & Access Control', 'Network Exposure',
                'Container Security'):
            self.assertNotIn(scanner_covered_item, self.template)
            self.assertNotIn(scanner_covered_item, self.prompt)

    def test_trivy_gate_covers_removed_kubernetes_misconfiguration_classes(self):
        lint_workflow = read('.github', 'workflows', 'lint.yaml')
        self.assertIn('IaC security scan (Trivy)', lint_workflow)
        self.assertIn('trivy config', lint_workflow)
        self.assertIn('--exit-code 1', lint_workflow)
        self.assertIn('--severity CRITICAL,HIGH', lint_workflow)
        self.assertIn('--ignorefile .trivyignore.yaml', lint_workflow)

    def test_prompt_static_text_shrinks_from_recorded_baseline(self):
        self.assertLess(
            review_prompt_static_chars(self.prompt), PRE_STEP_3B_STATIC_PROMPT_CHARS)

    def test_prompt_scores_comment_to_code_ratio(self):
        self.assertIn('against added code lines', self.prompt)
        self.assertIn('never HIGH', self.prompt)


if __name__ == '__main__':
    unittest.main()
