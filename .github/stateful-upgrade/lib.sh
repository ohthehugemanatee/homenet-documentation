# shellcheck shell=bash
# Helpers for test-stateful-upgrade.yaml. Needs the job's env and the repo root as cwd.

kc() { kubectl -n "$NAMESPACE" "$@"; }

apply_version() { # old | new
  local dir="$RUNNER_TEMP/$1" path files=()
  for path in $MANIFESTS; do
    mkdir -p "$dir/$(dirname "$path")"
    if [ "$1" = old ]; then git show "$BASE_SHA:$path" > "$dir/$path"; else cp "$path" "$dir/$path"; fi
    files+=("$dir/$path")
  done
  python3 .github/scripts/stateful_upgrade_render.py "${files[@]}" | kc apply -f -
  kc rollout status "$WORKLOAD" --timeout="$ROLLOUT_TIMEOUT"
}

# mariadb has no readinessProbe, so rollout status returns before it answers queries.
run_check() {
  local script attempt
  script=$(cat "cluster/argocd/hooks/$APP/check.sh")
  for attempt in $(seq 1 60); do
    if kc exec "$POD" -c "$CONTAINER" -- sh -c "$script"; then return 0; fi
    echo "check.sh failed (attempt $attempt of 60)"
    sleep 5
  done
  return 1
}
