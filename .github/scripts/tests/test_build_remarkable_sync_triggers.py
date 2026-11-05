"""build-remarkable-sync-image.yaml builds on merge to master. See #454, #457."""
import os
import unittest

import yaml

WORKFLOW = os.path.join(
    os.path.dirname(__file__), '..', '..', 'workflows', 'build-remarkable-sync-image.yaml')
IMAGE = 'ghcr.io/ohthehugemanatee/remarkable-sync'


class BuildRemarkableSyncTriggersTest(unittest.TestCase):
    def setUp(self):
        with open(WORKFLOW) as f:
            self.workflow = yaml.safe_load(f)
        steps = self.workflow['jobs']['build-and-push']['steps']
        self.build = next(s for s in steps if 'build-push-action' in s.get('uses', ''))['with']

    def test_merge_to_master_triggers_a_build(self):
        self.assertEqual(self.workflow['on']['push']['branches'], ['master'])

    def test_push_builds_only_when_the_image_inputs_change(self):
        paths = self.workflow['on']['push']['paths']
        self.assertEqual(
            sorted(paths),
            ['.github/workflows/build-remarkable-sync-image.yaml',
             'cluster/Dockerfiles/remarkable-sync/**'])

    def test_manual_dispatch_remains(self):
        self.assertIn('rmapi_ref', self.workflow['on']['workflow_dispatch']['inputs'])

    def test_every_build_gets_an_immutable_sha_tag(self):
        self.assertIn(f'{IMAGE}:sha-${{{{ github.sha }}}}', self.build['tags'].splitlines())

    def test_push_builds_pass_no_empty_ref(self):
        # inputs.* is empty on push; an unguarded use sends RMAPI_REF= and the
        # rmapi clone fails on --branch "".
        for key in ('tags', 'build-args'):
            for line in self.build[key].splitlines():
                if 'inputs.rmapi_ref' in line:
                    self.assertIn('${{ inputs.rmapi_ref &&', line, f'{key}: {line}')

    def test_ref_tag_is_still_written_by_dispatch(self):
        self.assertIn(f"format('{IMAGE}:{{0}}', inputs.rmapi_ref)", self.build['tags'])

    def test_devel_tag_is_written_only_by_push_builds(self):
        lines = [l for l in self.build['tags'].splitlines() if f'{IMAGE}:devel' in l]
        self.assertEqual(len(lines), 1)
        self.assertIn("github.event_name == 'push' &&", lines[0])

    def test_concurrent_builds_queue_instead_of_cancelling(self):
        self.assertIs(self.workflow['concurrency']['cancel-in-progress'], False)


if __name__ == '__main__':
    unittest.main()
