"""Gate against generic ephemeral volumes backed by a Longhorn StorageClass.

An `ephemeral.volumeClaimTemplate` mints a fresh PVC, and so a fresh Longhorn
volume UUID, on every pod restart. Longhorn stamps each new volume into the
`default` recurring job group (`datastore.FixupRecurringJob`, called from both
CreateVolume and UpdateVolume), the weekly `backups` job copies it to shoebox,
and `retain` never collects the copy once the volume is gone. Plex transcode
accumulated 11 orphaned BackupVolumes and 27 GiB that way (#277).

Scratch that does not survive a restart belongs in an `emptyDir`. Scratch that
must survive belongs in a StatefulSet volumeClaimTemplate, which keeps one
stable UUID.

problems() is pure; main() does the I/O.
"""
import glob
import os
import sys

import yaml

MANIFEST_GLOB = 'cluster/**/*.yaml'
LONGHORN_PREFIX = 'longhorn'


def problems(doc):
    """Return human-readable defects in one Kubernetes document.

    Walks every pod template in the document and flags each generic ephemeral
    volume whose volumeClaimTemplate names a Longhorn StorageClass.
    """
    found = []
    if not isinstance(doc, dict):
        return found

    spec = doc.get('spec')
    if not isinstance(spec, dict):
        return found

    # Deployment/StatefulSet/DaemonSet/Job wrap the pod spec in .template;
    # a bare Pod carries .spec.volumes directly.
    template = spec.get('template')
    pod = template.get('spec') if isinstance(template, dict) else spec
    if not isinstance(pod, dict):
        return found

    volumes = pod.get('volumes')
    if not isinstance(volumes, list):
        return found

    for volume in volumes:
        if not isinstance(volume, dict):
            continue
        ephemeral = volume.get('ephemeral')
        if not isinstance(ephemeral, dict):
            continue
        claim = ephemeral.get('volumeClaimTemplate')
        if not isinstance(claim, dict):
            continue
        claim_spec = claim.get('spec')
        if not isinstance(claim_spec, dict):
            continue

        storage_class = claim_spec.get('storageClassName') or ''
        if storage_class.startswith(LONGHORN_PREFIX):
            found.append(
                f'volume {volume.get("name")!r} is a generic ephemeral volume '
                f'on StorageClass {storage_class!r}; every pod restart orphans '
                f'a BackupVolume. Use emptyDir, or a StatefulSet '
                f'volumeClaimTemplate if the data must survive.')

    return found


def main():
    root = os.path.join(os.path.dirname(__file__), '..', '..')
    errors = []
    scanned = 0

    pattern = os.path.join(root, MANIFEST_GLOB)
    for path in sorted(glob.glob(pattern, recursive=True)):
        rel = os.path.relpath(path, root)
        try:
            with open(path) as fh:
                documents = list(yaml.safe_load_all(fh))
        except yaml.YAMLError:
            # yamllint owns syntax; skip rather than double-report.
            continue

        scanned += 1
        for doc in documents:
            name = ((doc or {}).get('metadata') or {}).get('name') \
                if isinstance(doc, dict) else None
            for problem in problems(doc):
                errors.append(f'{rel}: {name}: {problem}')

    for error in errors:
        print(f'FAIL :: {error}')
    if errors:
        return 1

    print(f'OK :: {scanned} manifest(s) scanned, '
          f'no ephemeral volume on a Longhorn StorageClass')
    return 0


if __name__ == '__main__':
    sys.exit(main())
