#!/usr/bin/env bash
# Unit tests for the Galaxy collection pins consumed by the Semaphore runner.
# Semaphore installs collections from <playbook_dir>/collections/requirements.yml
# before each run; CI installs from requirements.yaml. Both must agree, and both
# must exclude the kubernetes.core versions that crash instead of reporting a
# k8s_scale wait timeout.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANSIBLE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CI_REQUIREMENTS="${ANSIBLE_DIR}/requirements.yaml"
SEMAPHORE_REQUIREMENTS="${ANSIBLE_DIR}/collections/requirements.yml"

# Floor at which k8s_scale stopped splatting `duration` into ResourceTimeout.
MIN_KUBERNETES_CORE="3.0.0"

failures=0

check() {
  local desc=$1
  shift
  if "$@" >/dev/null 2>&1; then
    echo "  OK   $desc"
  else
    echo "  FAIL $desc"
    failures=$((failures + 1))
  fi
}

echo "Running collection requirements tests..."

check "Semaphore reads a requirements file at collections/requirements.yml" \
  test -f "$SEMAPHORE_REQUIREMENTS"

check "CI and Semaphore resolve to the same requirements file" \
  test "$SEMAPHORE_REQUIREMENTS" -ef "$CI_REQUIREMENTS"

check "kubernetes.core is pinned at >= ${MIN_KUBERNETES_CORE}" \
  python3 - "$SEMAPHORE_REQUIREMENTS" "$MIN_KUBERNETES_CORE" <<'PY'
import re
import sys

import yaml

requirements_path, minimum = sys.argv[1], sys.argv[2]
with open(requirements_path) as handle:
    collections = yaml.safe_load(handle)["collections"]

entries = [c for c in collections if isinstance(c, dict) and c.get("name") == "kubernetes.core"]
if not entries:
    sys.exit("kubernetes.core has no version constraint")

# A bare floor is enough; an added ceiling must not drop below it.
floors = re.findall(r">=\s*([0-9]+(?:\.[0-9]+)*)", entries[0].get("version", ""))
if not floors:
    sys.exit("kubernetes.core constraint has no >= floor")

to_tuple = lambda v: tuple(int(p) for p in v.split("."))
if to_tuple(floors[0]) < to_tuple(minimum):
    sys.exit(f"kubernetes.core floor {floors[0]} is below {minimum}")
PY

if [ "$failures" -ne 0 ]; then
  echo "${failures} test(s) failed."
  exit 1
fi

echo "All collection requirements tests passed."
