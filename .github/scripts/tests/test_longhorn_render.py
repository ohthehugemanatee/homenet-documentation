"""Tests for check_longhorn_render.

The Longhorn StorageClass and settings are not chart objects: the chart writes
each into a ConfigMap that longhorn-manager applies. A drifted render therefore
reaches live config, and the class's `parameters` are immutable (#279).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from check_longhorn_render import mismatches  # noqa: E402

CAPTURE = {
    'storageClass': {
        'isDefaultClass': 'true',
        'provisioner': 'driver.longhorn.io',
        'allowVolumeExpansion': True,
        'reclaimPolicy': 'Delete',
        'volumeBindingMode': 'Immediate',
        'parameters': {'numberOfReplicas': '3', 'fsType': 'ext4',
                       'dataLocality': 'disabled'},
    },
    'settings': {'default-replica-count': '2', 'orphan-auto-deletion': 'true',
                 'v2-data-engine-hugepage-limit': '1024'},
}


def rendered(parameters=None, settings=None):
    """What the chart's two ConfigMaps parse to, matching CAPTURE by default."""
    sc = {'metadata': {'annotations':
                       {'storageclass.kubernetes.io/is-default-class': 'true'}},
          'provisioner': 'driver.longhorn.io',
          'allowVolumeExpansion': True,
          'reclaimPolicy': 'Delete',
          'volumeBindingMode': 'Immediate',
          'parameters': parameters or dict(CAPTURE['storageClass']['parameters'])}
    # Helm renders these unquoted, so YAML gives back bool and int.
    return {'longhorn-storageclass': sc,
            'longhorn-default-setting': settings if settings is not None else
            {'default-replica-count': 2, 'orphan-auto-deletion': True,
             'v2-data-engine-hugepage-limit': 1024}}


class MismatchesTest(unittest.TestCase):
    def test_matching_render_is_clean(self):
        self.assertEqual(mismatches(CAPTURE, rendered()), [])

    def test_changed_storage_class_parameter_is_named(self):
        params = dict(CAPTURE['storageClass']['parameters'], numberOfReplicas='2')
        (found,) = mismatches(CAPTURE, rendered(parameters=params))
        self.assertIn('storageClass.parameters.numberOfReplicas', found)

    def test_dropped_storage_class_parameter_is_caught(self):
        params = {'numberOfReplicas': '3', 'fsType': 'ext4'}
        (found,) = mismatches(CAPTURE, rendered(parameters=params))
        self.assertIn('dataLocality', found)

    def test_dropped_setting_is_caught(self):
        settings = {'default-replica-count': 2, 'orphan-auto-deletion': True}
        (found,) = mismatches(CAPTURE, rendered(settings=settings))
        self.assertIn('v2-data-engine-hugepage-limit', found)

    def test_changed_setting_is_caught(self):
        settings = {'default-replica-count': 3, 'orphan-auto-deletion': True,
                    'v2-data-engine-hugepage-limit': 1024}
        (found,) = mismatches(CAPTURE, rendered(settings=settings))
        self.assertIn('settings.default-replica-count', found)

    def test_missing_configmap_is_caught(self):
        found = mismatches(CAPTURE, {'longhorn-storageclass':
                                     rendered()['longhorn-storageclass']})
        self.assertEqual(len(found), 1)
        self.assertIn('longhorn-default-setting', found[0])


if __name__ == '__main__':
    unittest.main()
