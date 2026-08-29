#!/usr/bin/env python3
"""Assert the Longhorn chart renders the cluster's live config, not new config.

Neither the StorageClass nor the settings is a chart object: the chart renders
each into a ConfigMap that longhorn-manager then applies, so a drifted render
reaches live config, and the class's `parameters` are immutable. See the chart
values section of cluster/longhorn/README.md.

Usage: check_longhorn_render.py <helm-template-output.yaml>
"""
import sys
from pathlib import Path

import yaml

CAPTURE = Path("cluster/helm/longhorn/live-state.yaml")
SC_CONFIGMAP = "longhorn-storageclass"
SETTINGS_CONFIGMAP = "longhorn-default-setting"


def rendered_configmaps(path):
    """Map ConfigMap name -> its single embedded YAML document, parsed."""
    out = {}
    for doc in yaml.safe_load_all(path.read_text()):
        if doc and doc.get("kind") == "ConfigMap":
            name = doc["metadata"]["name"]
            if name in (SC_CONFIGMAP, SETTINGS_CONFIGMAP):
                (embedded,) = doc["data"].values()
                out[name] = yaml.safe_load(embedded)
    return out


def storage_class_facts(sc):
    """The fields live-state.yaml records, from a rendered StorageClass."""
    annotations = sc.get("metadata", {}).get("annotations", {})
    return {
        "isDefaultClass": annotations.get("storageclass.kubernetes.io/is-default-class"),
        "provisioner": sc.get("provisioner"),
        "allowVolumeExpansion": sc.get("allowVolumeExpansion"),
        "reclaimPolicy": sc.get("reclaimPolicy"),
        "volumeBindingMode": sc.get("volumeBindingMode"),
        "parameters": sc.get("parameters"),
    }


def flatten(label, mapping):
    """`{"parameters": {"fsType": "ext4"}}` -> `{"sc.parameters.fsType": "ext4"}`."""
    flat = {}
    for key, value in mapping.items():
        if isinstance(value, dict):
            flat.update(flatten(f"{label}.{key}", value))
        else:
            flat[f"{label}.{key}"] = value
    return flat


def diff(label, live, rendered):
    """One line per key that parted, or an empty list."""
    live, rendered = flatten(label, live), flatten(label, rendered)
    return [
        f"  {key}: live {live.get(key)!r}, rendered {rendered.get(key)!r}"
        for key in sorted(set(live) | set(rendered))
        if live.get(key) != rendered.get(key)
    ]


def mismatches(capture, rendered):
    """Every way `rendered` parts from `capture`, as printable lines."""
    errors = []
    for name in (SC_CONFIGMAP, SETTINGS_CONFIGMAP):
        if name not in rendered:
            errors.append(f"  chart rendered no {name} ConfigMap")

    if SC_CONFIGMAP in rendered:
        errors += diff(
            "storageClass",
            capture["storageClass"],
            storage_class_facts(rendered[SC_CONFIGMAP]),
        )

    if SETTINGS_CONFIGMAP in rendered:
        # The ConfigMap is YAML, so `true` and `1024` parse as bool and int
        # while the Setting CRs hold every value as a string. Compare as text.
        errors += diff(
            "settings",
            {k: str(v) for k, v in capture["settings"].items()},
            {
                k: str(v).lower() if isinstance(v, bool) else str(v)
                for k, v in rendered[SETTINGS_CONFIGMAP].items()
            },
        )
    return errors


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    capture = yaml.safe_load(CAPTURE.read_text())
    errors = mismatches(capture, rendered_configmaps(Path(sys.argv[1])))
    if errors:
        print("Longhorn render no longer matches the live capture:", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        print(
            "\nFix cluster/helm/longhorn/values.yaml, or re-capture live-state.yaml"
            "\nif the cluster itself changed.",
            file=sys.stderr,
        )
        sys.exit(1)
    print("Longhorn render matches the live capture")


if __name__ == "__main__":
    main()
