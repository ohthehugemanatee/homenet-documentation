"""songhub.yaml tracks branch-build tags and pulls them on every start. See #458."""
import os
import re
import unittest

import yaml

ROOT = os.path.join(os.path.dirname(__file__), '..', '..', '..')
MANIFEST = os.path.join(ROOT, 'cluster', 'services', 'songhub.yaml')
WORKFLOW = os.path.join(ROOT, '.github', 'workflows', 'build-remarkable-sync-image.yaml')
OWN_IMAGES = 'ghcr.io/ohthehugemanatee/'
SYNC_IMAGE = OWN_IMAGES + 'remarkable-sync'


def containers():
    with open(MANIFEST, encoding='utf-8') as f:
        for doc in yaml.safe_load_all(f):
            if doc and doc.get('kind') == 'StatefulSet':
                yield from doc['spec']['template']['spec']['containers']


def push_build_tags():
    """Literal tags the push build writes: dispatch-only and per-commit tags are excluded."""
    with open(WORKFLOW, encoding='utf-8') as f:
        workflow = yaml.safe_load(f)
    steps = workflow['jobs']['build-and-push']['steps']
    tags = next(s for s in steps if 'build-push-action' in s.get('uses', ''))['with']['tags']
    found = set()
    for line in tags.splitlines():
        if 'inputs.rmapi_ref' in line:
            continue
        match = re.search(re.escape(SYNC_IMAGE) + r":([^'\s]+)", line)
        if match and '$' not in match.group(1):
            found.add(match.group(1))
    return found


class SonghubImageTagsTest(unittest.TestCase):
    def test_own_images_always_pull(self):
        own = [c for c in containers() if c['image'].startswith(OWN_IMAGES)]
        self.assertEqual({c['name'] for c in own}, {'songhub', 'remarkable-sync'})
        for c in own:
            self.assertEqual(c.get('imagePullPolicy'), 'Always', c['name'])

    def test_sync_tag_is_written_by_the_push_build(self):
        image = next(c['image'] for c in containers() if c['image'].startswith(SYNC_IMAGE))
        self.assertIn(image.rsplit(':', 1)[1], push_build_tags())


if __name__ == '__main__':
    unittest.main()
